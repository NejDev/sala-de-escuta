"""Artists: everything a band or artist released, its members' solo work and their features.

The band and its members (and subunits) come from MusicBrainz, with their Spotify profiles;
each one's releases come from Spotify: their own (albums, singles and EPs) and the ones they
appear on (features, soundtracks). Everything is merged into one list.

Spotify punishes bursts on these endpoints hard (one big band once paused them for ~23 hours), so
requests go out slowly (api.SLOW_FAMILIES) and everything read is kept on disk: the first search of a
big band takes a couple of minutes, and the next ones only ask for what came out since.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from collections.abc import Iterator
from pathlib import Path

from . import config, curation
from .api import Spotify, SpotifyError
from .discovery import Hunt, is_religious
from .i18n import t
from .musicbrainz import MusicBrainz, MusicBrainzError, unique_members
from .views import pick_image

# Each list is read on its own, newest first, so a later search can stop as soon as it reaches what it knows.
GROUPS = (("album", False), ("single", False), ("compilation", False), ("appears_on", True))
LATEST_GROUPS = "album,single"  # one page is enough for the "which one?" cards
PAGE = 10  # the most Spotify gives per page for an artist's releases in Development Mode
MAX_PEOPLE = 16  # the artist plus members and subunits read in one search
MAX_CANDIDATES = 8  # "which one?" cards when several artists share a name
CANDIDATES_WITH_LATEST = 4  # only the first cards ask Spotify for their latest release
RECHECK_S = 86400  # a complete list is trusted for a day; then a search only reads what came out since
REREAD_S = 30 * 86400  # once a month a list is read again from scratch (Spotify fixes old entries)
PROFILE_TTL_S = 7 * 86400

log = logging.getLogger(__name__)
_cache: dict[str, dict] | None = None  # key -> {"at", "value"}; loaded from disk on first use
_cache_lock = threading.Lock()


def _cache_file() -> Path:
    return config.DATA_DIR / "artists-cache.json"


def _entries() -> dict[str, dict]:
    """The cache (call with the lock held)."""
    global _cache
    if _cache is None:
        try:
            _cache = json.loads(_cache_file().read_text(encoding="utf-8"))
        except (FileNotFoundError, ValueError):
            _cache = {}
    return _cache


def _get(key: str) -> dict | None:
    with _cache_lock:
        return _entries().get(key)


def _put(key: str, value) -> None:
    global _cache
    with _cache_lock:
        now = time.time()
        _cache = {k: v for k, v in _entries().items() if now - v["at"] < REREAD_S}
        _cache[key] = {"at": now, "value": value}
        config.DATA_DIR.mkdir(exist_ok=True)
        _cache_file().write_text(json.dumps(_cache, ensure_ascii=False), encoding="utf-8")


def _remembered(key: str, ttl_s: float, load):
    hit = _get(key)
    if hit and time.time() - hit["at"] < ttl_s:
        return hit["value"]
    value = load()
    _put(key, value)
    return value


def _slim(album: dict) -> dict:
    keep = ("id", "uri", "name", "album_type", "release_date", "images", "total_tracks")
    return {**{key: album.get(key) for key in keep}, "artists": [{"name": a.get("name", "")} for a in album.get("artists", [])]}


def releases(sp: Spotify, artist_id: str, group: str, cancelled=lambda: False) -> Iterator[list[dict]]:
    """Every release in one of an artist's lists (album, single, compilation, appears_on), in batches.

    The first read goes page by page, saved after each page, so a pause from Spotify or a cancel
    picks up where it stopped. A complete list is trusted for a day; after that only the newest
    pages are read, until one has something already known.
    """
    key = f"releases|{artist_id}|{group}"
    hit = _get(key)
    now = time.time()
    state = hit["value"] if hit and now - hit["value"]["read_at"] < REREAD_S else None
    state = state or {"albums": [], "offset": 0, "complete": False, "read_at": now}
    if state["albums"]:
        yield state["albums"]
    if state["complete"]:
        if now - hit["at"] < RECHECK_S:
            return
        known, new, offset = {album["id"] for album in state["albums"]}, [], 0
        while not cancelled():
            items, more = sp.artist_albums_page(artist_id, group, offset)
            fresh = [_slim(album) for album in items if album["id"] not in known]
            new += fresh
            if len(fresh) < len(items) or not more:  # reached what was already there
                if new:
                    yield new
                _put(key, {**state, "albums": new + state["albums"]})
                return
            offset += PAGE
        return  # cancelled halfway: nothing saved, the next search checks again
    while not cancelled():
        items, more = sp.artist_albums_page(artist_id, group, state["offset"])
        known = {album["id"] for album in state["albums"]}
        batch = [_slim(album) for album in items if album["id"] not in known]
        state = {**state, "albums": state["albums"] + batch, "offset": state["offset"] + PAGE, "complete": not more}
        _put(key, state)
        if batch:
            yield batch
        if not more:
            return


def profile_of(sp: Spotify, artist_id: str) -> dict:
    def load() -> dict:
        profile = sp.artist(artist_id) or {}
        return {"name": profile.get("name"), "images": profile.get("images") or []}

    return _remembered(f"profile|{artist_id}", PROFILE_TTL_S, load)


def spotify_artist(sp: Spotify, name: str, unique: bool = False) -> dict | None:
    """Spotify search by name; for members, only an unambiguous exact match (there are many "MINA"s)."""
    found = sp.search(name, "artist")
    exact = [artist for artist in found if curation.normalize(artist.get("name", "")) == curation.normalize(name)]
    if unique:
        return exact[0] if len(exact) == 1 else None
    return (exact or found or [None])[0]


def candidate(sp: Spotify, artist: dict, with_latest: bool = True) -> dict:
    """A card for "which one?": photo, genres and their latest release, so the person recognizes them."""
    latest = None
    try:
        albums = _remembered(f"latest|{artist['id']}", PROFILE_TTL_S, lambda: [
            _slim(album) for album in sp.artist_albums_page(artist["id"], LATEST_GROUPS)[0]]) if with_latest else []
        newest = max(albums, key=lambda album: album.get("release_date", ""), default=None)
        if newest:
            latest = {"name": newest.get("name", ""), "year": newest.get("release_date", "")[:4]}
    except SpotifyError as err:
        log.warning("Couldn't read %s's releases: %s", artist.get("name"), err)
    return {
        "id": artist["id"],
        "name": artist.get("name", ""),
        "image": pick_image(artist.get("images"), 160),
        "genres": (artist.get("genres") or [])[:3],
        "latest": latest,
    }


def resolve(sp: Spotify, mb: MusicBrainz, name: str, spotify_id: str | None = None) -> tuple[dict | None, list[dict]]:
    """The artist ({name, spotify}) and the people and units around them ({name, spotify, role, former})."""
    person, people = ({"name": name, "spotify": spotify_id} if spotify_id else None), []
    try:
        # The exact Spotify profile when we have it; otherwise the name (when Spotify search is paused).
        mbid = mb.by_spotify(spotify_id) if spotify_id else mb.find(name)
        if mbid:
            info = mb.artist(mbid)
            person = person or {"name": info["name"], "spotify": info["spotify"]}
            for member in unique_members(info["members"])[:MAX_PEOPLE]:  # also what was cached before
                people.append({**member, "spotify": mb.artist(member["mbid"])["spotify"]})
    except MusicBrainzError as err:
        log.warning("MusicBrainz: %s", err)  # without line-ups, the search still finds the artist
    if not person or not person["spotify"]:
        found = spotify_artist(sp, name)
        if not found:
            return None, []
        person = {"name": found["name"], "spotify": found["id"]}
    for member in people:
        if not member["spotify"]:
            try:
                match = spotify_artist(sp, member["name"], unique=True)
            except SpotifyError as err:  # e.g. search paused: this member is left out, not the whole search
                log.warning("Couldn't look up %s on Spotify: %s", member["name"], err)
                match = None
            member["spotify"] = match["id"] if match else None
    return person, [member for member in people if member["spotify"] and member["spotify"] != person["spotify"]]


def _add(by_key: dict, album: dict, who: dict, feature: bool) -> None:
    names = [artist.get("name", "") for artist in album.get("artists", [])]
    if is_religious(album.get("name", ""), *names):
        return
    album_type = album.get("album_type", "album")
    kind = "compilation" if album_type == "compilation" else "feature" if feature else album_type
    # Editions of the same release (Korean/Japanese, clean, deluxe on the same day) count once.
    key = (curation.normalize(curation.base_title(album.get("name", ""))), album.get("release_date", ""))
    entry = by_key.get(key)
    if entry is None:
        entry = by_key[key] = {
            "id": album["id"],
            "uri": album["uri"],
            "name": album.get("name", ""),
            "type": kind,
            "date": album.get("release_date", ""),
            "artists": names,
            "image": pick_image(album.get("images"), 64),
            "tracks": album.get("total_tracks", 0),
            "who": [],
        }
    elif entry["type"] == "feature" and not feature:
        entry["type"] = kind  # also one of their own releases
    if all(person["id"] != who["spotify"] for person in entry["who"]):
        entry["who"].append({"id": who["spotify"], "name": who["name"]})


def discography(hunt: Hunt, sp: Spotify, mb: MusicBrainz, name: str, spotify_id: str | None = None) -> None:
    hunt.message = t("artists.looking", name=name)
    if spotify_id is None:
        try:
            found = sp.search(name, "artist")
        except SpotifyError as err:
            if err.status != 429:
                raise
            found = None  # Spotify search paused: go by the name through MusicBrainz
        if found is not None:
            exact = [artist for artist in found if curation.normalize(artist.get("name", "")) == curation.normalize(name)]
            if len(exact) == 1:
                spotify_id = exact[0]["id"]
            elif found:  # several with this name (or none exactly): the person picks
                hunt.candidates = [candidate(sp, artist, index < CANDIDATES_WITH_LATEST)
                                   for index, artist in enumerate((exact or found)[:MAX_CANDIDATES])]
                hunt.message = t("artists.choose", name=name)
                return
            else:
                hunt.message = t("artists.not_found", name=name)
                return
    person, people = resolve(sp, mb, name, spotify_id)
    if hunt.cancelled:
        return
    if not person:
        hunt.message = t("artists.not_found", name=name)
        return
    profile = profile_of(sp, person["spotify"])
    display = profile.get("name") or person["name"]
    hunt.label = display
    everyone = [{"name": display, "spotify": person["spotify"], "role": "main", "former": False}, *people]
    hunt.artist = {
        "name": display,
        "image": pick_image(profile.get("images"), 160),
        "uri": f"spotify:artist:{person['spotify']}",
        "people": [{key: who[key] for key in ("name", "spotify", "role", "former")} for who in everyone],
    }
    hunt.total = len(everyone)
    by_key: dict[tuple[str, str], dict] = {}
    for index, who in enumerate(everyone, start=1):
        if hunt.cancelled:
            return
        for group, feature in GROUPS:
            hunt.message = t("artists.reading", name=who["name"], progress=index, total=len(everyone),
                             count=len(by_key))
            for batch in releases(sp, who["spotify"], group, lambda: hunt.cancelled):
                for album in batch:
                    _add(by_key, album, who, feature)
                hunt.releases = sorted(by_key.values(), key=lambda release: release["date"], reverse=True)
                hunt.message = t("artists.reading", name=who["name"], progress=index, total=len(everyone),
                                 count=len(by_key))
            if hunt.cancelled:
                return
        hunt.progress = index
    count = len(hunt.releases)
    if not count:
        hunt.message = t("artists.none", name=display)
    else:
        hunt.message = t("artists.done_group" if people else "artists.done", count=count, name=display)
