"""Song lyrics from LRCLIB (open data, free, no key), synced line by line when it has the times.

Spotify doesn't let other apps show its lyrics. Each song is asked once and kept in data/lyrics/<track id>.json;
a song LRCLIB doesn't have is asked again after a week. LRCLIB limits requests hard: after a "too many
requests" no lookup goes out until the pause it asked for is over.
"""
from __future__ import annotations

import http.client
import json
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Callable

from . import config, curation

API_URL = "https://lrclib.net/api"
USER_AGENT = "SalaDeEscuta/1.0 (+https://github.com/NejDev/sala-de-escuta)"
TIMEOUT_S = 15
MIN_PAUSE_S = 60  # after "too many requests", at least this long
MISSING_RETRY_S = 7 * 86400
LENGTH_SLACK_S = 3  # a search result counts when its length is this close to the song's
TRACK_ID = re.compile(r"[A-Za-z0-9]{1,40}")
LRC_TIME = re.compile(r"\[(\d+):(\d{1,2}(?:\.\d+)?)\]")


class LyricsError(RuntimeError):
    def __init__(self, kind: str) -> None:
        super().__init__(kind)
        self.kind = kind  # "busy" (LRCLIB asked for a pause) or "down"


def parse_lrc(text: str) -> list[list]:
    """[[ms, line], ...] in time order; a line with several times repeats; tags like [ar: ...] are dropped."""
    lines = []
    for raw in text.splitlines():
        times = LRC_TIME.findall(raw)
        if not times:
            continue
        words = LRC_TIME.sub("", raw).strip()
        for minutes, seconds in times:
            lines.append([round((int(minutes) * 60 + float(seconds)) * 1000), words])
    return sorted(lines, key=lambda line: line[0])


class Lrclib:
    def __init__(self, opener: Callable = urllib.request.urlopen, clock: Callable[[], float] = time.monotonic) -> None:
        self._opener = opener
        self._clock = clock
        self._lock = threading.Lock()
        self._paused_until = 0.0

    def find(self, artist: str, title: str, album: str, duration_s: int | None) -> dict | None:
        """LRCLIB's record of the song: the exact one, else a search result of about the same length."""
        exact = {"artist_name": artist, "track_name": title, "album_name": album}
        if duration_s:
            exact["duration"] = duration_s
        record = self._ask("get", exact)
        if isinstance(record, dict):
            return record
        results = self._ask("search", {"artist_name": artist, "track_name": title})
        return best_result(results if isinstance(results, list) else [], duration_s)

    def _ask(self, endpoint: str, params: dict) -> dict | list | None:
        with self._lock:
            if self._clock() < self._paused_until:
                raise LyricsError("busy")
        request = urllib.request.Request(f"{API_URL}/{endpoint}?{urllib.parse.urlencode(params)}",
                                         headers={"User-Agent": USER_AGENT})
        try:
            with self._opener(request, timeout=TIMEOUT_S) as response:
                return json.loads(response.read())
        except urllib.error.HTTPError as err:
            if err.code == 404:
                return None
            if err.code == 429:
                try:
                    wait = int(err.headers.get("Retry-After") or 0)
                except (TypeError, ValueError):
                    wait = 0
                with self._lock:
                    self._paused_until = self._clock() + max(wait, MIN_PAUSE_S)
                raise LyricsError("busy") from err
            raise LyricsError("down") from err
        except (OSError, http.client.HTTPException, ValueError) as err:  # URLError, timeouts, cut answers
            raise LyricsError("down") from err


def best_result(results: list, duration_s: int | None) -> dict | None:
    """The closest in length (within a few seconds), synced ones first; any one when the length is unknown."""
    fitting = [r for r in results if isinstance(r, dict) and (
        not duration_s or abs((r.get("duration") or 0) - duration_s) <= LENGTH_SLACK_S)]
    fitting.sort(key=lambda r: (not r.get("syncedLyrics"), abs((r.get("duration") or 0) - (duration_s or 0))))
    return fitting[0] if fitting else None


def entry_from(record: dict | None) -> dict:
    """What the panel shows: synced lines, plain text, instrumental or missing."""
    if record is None:
        return {"status": "missing"}
    lines = parse_lrc(record.get("syncedLyrics") or "")
    if any(text for _, text in lines):
        return {"status": "synced", "lines": lines}
    if (record.get("plainLyrics") or "").strip():
        return {"status": "plain", "text": record["plainLyrics"].strip()}
    return {"status": "instrumental"} if record.get("instrumental") else {"status": "missing"}


class Lyrics:
    """Lyrics per Spotify track, kept on disk; the same song is never asked twice (or once a week if missing)."""

    def __init__(self, client: Lrclib, folder: Path | None = None, now: Callable[[], float] = time.time) -> None:
        self.client = client
        self._folder = folder
        self._now = now

    def _file(self, track_id: str) -> Path:
        if not TRACK_ID.fullmatch(track_id):
            raise ValueError("not a track id")
        return (self._folder or config.DATA_DIR / "lyrics") / f"{track_id}.json"

    def get(self, track_id: str, artist: str, title: str, album: str, duration_ms: int | None) -> dict:
        path = self._file(track_id)
        try:
            kept = json.loads(path.read_text(encoding="utf-8"))
            if kept["status"] != "missing" or self._now() - kept["at"] < MISSING_RETRY_S:
                return {key: value for key, value in kept.items() if key != "at"}
        except (FileNotFoundError, ValueError, KeyError, TypeError):
            pass
        duration_s = round(duration_ms / 1000) if duration_ms else None
        entry = entry_from(self.client.find(artist, curation.base_title(title), album, duration_s))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({**entry, "at": self._now()}, ensure_ascii=False), encoding="utf-8")
        return entry
