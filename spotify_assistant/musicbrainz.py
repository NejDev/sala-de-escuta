"""MusicBrainz: who is in a band (members and subunits) and their Spotify profiles.

Spotify doesn't say who is in a group; MusicBrainz (open data, no key) does, and it often
links each artist to their Spotify profile, which avoids guessing by name. Its rules: at most
one request per second and a User-Agent that says who is asking. Answers are kept on disk
for a month (band line-ups rarely change).
"""
from __future__ import annotations

import json
import logging
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from . import config, curation

API = "https://musicbrainz.org/ws/2"
USER_AGENT = "SalaDeEscuta/1.0 ( https://github.com/NejDev/sala-de-escuta )"
MIN_INTERVAL_S = 1.1
CACHE_TTL_S = 30 * 86400
MIN_SCORE = 90  # search confidence (0-100) to accept an artist
SPOTIFY_ARTIST = re.compile(r"open\.spotify\.com/artist/(?P<id>[A-Za-z0-9]+)")

log = logging.getLogger(__name__)


class MusicBrainzError(Exception):
    pass


class MusicBrainz:
    def __init__(self, fetch=None) -> None:
        self._fetch = fetch or self._http
        self._lock = threading.Lock()
        self._last = 0.0
        self._cache: dict | None = None

    # ---------- plumbing

    def _http(self, url: str) -> dict:
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
        for attempt in range(3):
            with self._lock:  # one request at a time, spaced out
                wait = self._last + MIN_INTERVAL_S - time.monotonic()
                if wait > 0:
                    time.sleep(wait)
                try:
                    with urllib.request.urlopen(request, timeout=20) as response:
                        return json.loads(response.read())
                except urllib.error.HTTPError as err:
                    if err.code != 503 or attempt == 2:  # 503 = slow down
                        raise MusicBrainzError(f"HTTP {err.code}") from None
                except (urllib.error.URLError, TimeoutError, ValueError) as err:
                    if attempt == 2:
                        raise MusicBrainzError(str(err)) from None
                finally:
                    self._last = time.monotonic()
            time.sleep(1 + attempt)
        raise MusicBrainzError("no answer")

    def _cached(self, key: str, load) -> dict | None:
        with self._lock:
            if self._cache is None:
                try:
                    self._cache = json.loads(config.MUSICBRAINZ_CACHE_FILE.read_text(encoding="utf-8"))
                except (FileNotFoundError, ValueError):
                    self._cache = {}
            entry = self._cache.get(key)
        if entry and time.time() - entry["at"] < CACHE_TTL_S:
            return entry["value"]
        value = load()
        with self._lock:
            self._cache[key] = {"at": time.time(), "value": value}
            config.DATA_DIR.mkdir(exist_ok=True)
            config.MUSICBRAINZ_CACHE_FILE.write_text(json.dumps(self._cache, ensure_ascii=False), encoding="utf-8")
        return value

    # ---------- what the Sala asks

    def find(self, name: str) -> str | None:
        """MusicBrainz id of the artist or band with this name (None when unsure)."""
        def load() -> str | None:
            query = urllib.parse.quote(f'artist:"{name.replace(chr(34), "")}"')
            data = self._fetch(f"{API}/artist?query={query}&fmt=json&limit=5")
            return best_match(name, data.get("artists", []))

        return self._cached(f"find:{curation.normalize(name)}", load)

    def by_spotify(self, spotify_id: str) -> str | None:
        """MusicBrainz id of the artist linked to this Spotify profile (exact, no guessing by name)."""
        def load() -> str | None:
            url = urllib.parse.quote(f"https://open.spotify.com/artist/{spotify_id}", safe="")
            try:
                data = self._fetch(f"{API}/url?resource={url}&inc=artist-rels&fmt=json")
            except MusicBrainzError as err:
                if "404" in str(err):  # nobody linked this profile
                    return None
                raise
            return next((r["artist"]["id"] for r in data.get("relations", []) if r.get("artist")), None)

        return self._cached(f"spotify:{spotify_id}", load)

    def artist(self, mbid: str) -> dict:
        """Name, Spotify id and, for a band, its members and subunits."""
        return self._cached(f"artist:{mbid}", lambda: parse_artist(
            self._fetch(f"{API}/artist/{mbid}?inc=artist-rels+url-rels&fmt=json")))


def latin_name(name: str, sort_name: str) -> str:
    """The name as Spotify likely writes it: 다현 / もも become their Latin sort names (DAHYUN, MOMO)."""
    if re.search(r"[A-Za-z]", name) or not sort_name:
        return name
    if ", " in sort_name:  # "Park, Jin Young" -> "Jin Young Park"
        last, _, first = sort_name.partition(", ")
        return f"{first} {last}"
    return sort_name


def best_match(name: str, artists: list[dict]) -> str | None:
    wanted = curation.normalize(name)
    for artist in sorted(artists, key=lambda a: -int(a.get("score", 0))):
        names = {curation.normalize(artist.get("name", "")), curation.normalize(artist.get("sort-name", ""))}
        names |= {curation.normalize(alias.get("name", "")) for alias in artist.get("aliases", [])}
        if int(artist.get("score", 0)) >= MIN_SCORE and wanted in names:
            return artist["id"]
    return None


def spotify_id(relations: list[dict]) -> str | None:
    for relation in relations:
        match = SPOTIFY_ARTIST.search((relation.get("url") or {}).get("resource", ""))
        if match:
            return match["id"]
    return None


def parse_artist(data: dict) -> dict:
    relations = data.get("relations", [])
    members = []
    for relation in relations:
        kind = {"member of band": "member", "subgroup": "subgroup"}.get(relation.get("type"))
        other = relation.get("artist") or {}
        # "backward": the other artist belongs to this one (a member of this band, a subunit of it).
        if kind and relation.get("direction") == "backward" and other.get("id"):
            members.append({
                "mbid": other["id"],
                "name": latin_name(other.get("name", ""), other.get("sort-name", "")),
                "role": kind,
                "former": bool(relation.get("ended")),
            })
    return {
        "mbid": data.get("id"),
        "name": latin_name(data.get("name", ""), data.get("sort-name", "")),
        "type": data.get("type"),
        "spotify": spotify_id(relations),
        "members": unique_members(members),
    }


def unique_members(members: list[dict]) -> list[dict]:
    """One entry per person: MusicBrainz has one relation per instrument or period (Mike Shinoda x3).
    Former only when every one of their relations ended."""
    merged: dict[str, dict] = {}
    for member in members:
        entry = merged.setdefault(member["mbid"], dict(member))
        entry["former"] = entry["former"] and member["former"]
    return list(merged.values())
