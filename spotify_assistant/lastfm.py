"""Last.fm: how many people listened to a track (optional; needs LASTFM_API_KEY in .env).

Used by the discoveries' listener filter. Each track is asked once every 30 days and remembered in
data/lastfm-cache.json. Last.fm's terms ask for credit wherever its numbers show, with a link to the track.
"""
from __future__ import annotations

import http.client
import json
import threading
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from . import config, curation

API_URL = "https://ws.audioscrobbler.com/2.0/"
USER_AGENT = "SalaDeEscuta/1.0 (+https://github.com/NejDev/sala-de-escuta)"
MIN_INTERVAL_S = 0.25  # at most 4 requests per second for the whole panel (Last.fm no longer publishes a number)
TIMEOUT_S = 10
LIMIT_PAUSE_S = 10 * 60  # after Last.fm says "rate limit exceeded"
FRESH_S = 30 * 86400  # listener counts grow: ask again after a month
MAX_ENTRIES = 100_000  # about 15 MB; Last.fm's terms cap stored data at 100 MB
NOT_FOUND = 6
KEY_ERRORS = {10, 26}  # invalid or suspended key
RATE_LIMITED = 29


@dataclass(frozen=True)
class Listeners:
    count: int | None  # None: Last.fm has no record of the track
    url: str | None  # the track's page on Last.fm


class LastFmError(RuntimeError):
    def __init__(self, kind: str) -> None:
        super().__init__(kind)
        self.kind = kind  # "key" (not accepted), "limit" (paused for a while) or "down"


class LastFm:
    def __init__(
        self, key: str, opener: Callable = urllib.request.urlopen,
        clock: Callable[[], float] = time.monotonic, sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.key = key
        self._opener = opener
        self._clock = clock
        self._sleep = sleep
        self._lock = threading.Lock()
        self._last: float | None = None
        self._paused_until = 0.0

    def _wait_turn(self) -> None:
        """One request at a time, MIN_INTERVAL_S apart; none at all while Last.fm asked for a pause."""
        with self._lock:
            now = self._clock()
            if now < self._paused_until:
                raise LastFmError("limit")
            if self._last is not None and now < self._last + MIN_INTERVAL_S:
                self._sleep(self._last + MIN_INTERVAL_S - now)
                now = self._last + MIN_INTERVAL_S
            self._last = now

    def track(self, artist: str, title: str) -> Listeners:
        """Listeners of a track; the title goes without its version ("So What - Remastered" -> "So What")."""
        self._wait_turn()
        query = urllib.parse.urlencode({
            "method": "track.getInfo", "artist": artist, "track": curation.base_title(title),
            "autocorrect": 1, "format": "json", "api_key": self.key,
        })
        request = urllib.request.Request(f"{API_URL}?{query}", headers={"User-Agent": USER_AGENT})
        try:
            with self._opener(request, timeout=TIMEOUT_S) as response:
                data = json.loads(response.read())
        except urllib.error.HTTPError as err:  # Last.fm sends its errors as JSON with a 4xx status
            data = _error_body(err)
        except (OSError, http.client.HTTPException, ValueError) as err:  # URLError, timeouts, resets, cut answers
            raise LastFmError("down") from err
        if not isinstance(data, dict):
            raise LastFmError("down")
        code = data.get("error")
        if code == NOT_FOUND:
            return Listeners(None, None)
        if code in KEY_ERRORS:
            raise LastFmError("key")
        if code == RATE_LIMITED:
            with self._lock:
                self._paused_until = self._clock() + LIMIT_PAUSE_S
            raise LastFmError("limit")
        if code or not isinstance(data.get("track"), dict):
            raise LastFmError("down")
        track = data["track"]
        try:
            count = int(track.get("listeners") or 0)
        except (TypeError, ValueError):
            count = 0
        return Listeners(count, track.get("url"))


def _error_body(err: urllib.error.HTTPError) -> dict:
    try:
        data = json.loads(err.read())
    except ValueError:
        raise LastFmError("down") from err
    if not isinstance(data, dict) or "error" not in data:
        raise LastFmError("down") from err
    return data


def _fold(text: str) -> str:
    """Case and spacing don't count; unlike curation.normalize, Hangul, kana and Cyrillic survive."""
    return " ".join(unicodedata.normalize("NFKC", text).casefold().split())


def cache_key(artist: str, title: str) -> str:
    return f"{_fold(artist)}|{_fold(curation.base_title(title))}"


class ListenerCounts:
    """Cached lookups in front of the client: each track is asked once every 30 days."""

    def __init__(self, client: LastFm, path: Path | None = None, now: Callable[[], float] = time.time) -> None:
        self.client = client
        self._path = path
        self._now = now
        self._lock = threading.Lock()
        self._data: dict[str, dict] | None = None
        self._dirty = False

    def _file(self) -> Path:
        return self._path or config.LASTFM_CACHE_FILE

    def _entries(self) -> dict[str, dict]:
        """Called with the lock held."""
        if self._data is None:
            try:
                data = json.loads(self._file().read_text(encoding="utf-8"))
            except (FileNotFoundError, ValueError):
                data = {}
            self._data = data if isinstance(data, dict) else {}
        return self._data

    def get(self, artist: str, title: str, fresh_s: float = FRESH_S) -> Listeners:
        """`fresh_s`: how old a cached count may be (new releases ask for younger ones)."""
        key = cache_key(artist, title)
        with self._lock:
            entry = self._entries().get(key)
        if entry and self._now() - entry["at"] < fresh_s:
            return Listeners(entry["n"], entry["url"])
        found = self.client.track(artist, title)  # errors propagate and nothing is cached
        with self._lock:
            entries = self._entries()
            entries[key] = {"n": found.count, "url": found.url, "at": self._now()}
            if len(entries) > MAX_ENTRIES:  # keep the newest 90%, so trimming doesn't happen on every lookup
                newest = sorted(entries, key=lambda name: entries[name]["at"], reverse=True)[: int(MAX_ENTRIES * 0.9)]
                self._data = {name: entries[name] for name in newest}
            self._dirty = True
        return found

    def cached(self, artist: str, title: str) -> Listeners | None:
        """What the cache holds, however old; None when the track was never asked about. Never asks Last.fm."""
        with self._lock:
            entry = self._entries().get(cache_key(artist, title))
        return Listeners(entry["n"], entry["url"]) if entry else None

    def save(self) -> None:
        with self._lock:
            if not self._dirty or self._data is None:
                return
            path = self._file()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(self._data, ensure_ascii=False), encoding="utf-8")
            self._dirty = False
