"""Artists: everything a band or artist released, its members' solo work and their features.

The band and its members (and subunits) come from MusicBrainz, with their Spotify profiles;
each one's releases come from Spotify: their own (albums, singles and EPs) and the ones they
appear on (features, soundtracks). Everything is merged into one list.

Spotify punishes bursts on these endpoints hard (one big band once paused them for ~23 hours), so a
search reads only the newest pages of each person, and what it read is kept on disk for 3 days.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path

from . import config, curation
from .api import Spotify, SpotifyError
from .discovery import Hunt, is_religious
from .i18n import t
from .musicbrainz import MusicBrainz, MusicBrainzError, unique_members
from .views import pick_image

OWN = "album,single"  # their own compilations only repeat songs from the albums
FEATURES = "appears_on"
# Pages of 10 read per person, newest first: the artist searched, and each member or subunit.
MAIN_PAGES = {OWN: 5, FEATURES: 3}
MEMBER_PAGES = {OWN: 2, FEATURES: 1}
MAX_PEOPLE = 12  # the artist plus members and subunits read in one search
MAX_CANDIDATES = 8  # "which one?" cards when several artists share a name
CANDIDATES_WITH_LATEST = 4  # only the first cards ask Spotify for their latest release
CACHE_TTL_S = 3 * 86400  # releases don't change by the minute; kept on disk so restarts don't ask again

log = logging.getLogger(__name__)
_cache: dict[str, dict] | None = None  # "kind|id|groups" -> {"at", "value"}; loaded from disk on first use
_cache_lock = threading.Lock()


def _cache_file() -> Path:
    return config.DATA_DIR / "artists-cache.json"


def _remembered(key: str, fresh_enough, load):
    """The cached value for key when it is recent and fresh_enough(value) holds; otherwise load() and keep it."""
    global _cache
    with _cache_lock:
        if _cache is None:
            try:
                _cache = json.loads(_cache_file().read_text(encoding="utf-8"))
            except (FileNotFoundError, ValueError):
                _cache = {}
        hit = _cache.get(key)
    if hit and time.time() - hit["at"] < CACHE_TTL_S and fresh_enough(hit["value"]):
        return hit["value"]
    value = load()
    with _cache_lock:
        now = time.time()
        _cache = {k: v for k, v in _cache.items() if now - v["at"] < CACHE_TTL_S}
        _cache[key] = {"at": now, "value": value}
        config.DATA_DIR.mkdir(exist_ok=True)
        _cache_file().write_text(json.dumps(_cache, ensure_ascii=False), encoding="utf-8")
    return value


def _slim(album: dict) -> dict:
    keep = ("id", "uri", "name", "album_type", "release_date", "images", "total_tracks")
    return {**{key: album.get(key) for key in keep}, "artists": [{"name": a.get("name", "")} for a in album.get("artists", [])]}


def releases_of(sp: Spotify, artist_id: str, groups: str, pages: int) -> list[dict]:
    """The newest `pages` pages of an artist's releases (reuses a read of as many pages or more)."""
    def load() -> dict:
        return {"pages": pages, "albums": [_slim(album) for album in sp.artist_albums(artist_id, groups, max_pages=pages)]}

    return _remembered(f"releases|{artist_id}|{groups}", lambda hit: hit["pages"] >= pages, load)["albums"]


def profile_of(sp: Spotify, artist_id: str) -> dict:
    def load() -> dict:
        profile = sp.artist(artist_id) or {}
        return {"name": profile.get("name"), "images": profile.get("images") or []}

    return _remembered(f"profile|{artist_id}", lambda hit: True, load)


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
        albums = releases_of(sp, artist["id"], OWN, 1) if with_latest else []
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
        hunt.message = t("artists.reading", name=who["name"], progress=index, total=len(everyone))
        pages = MAIN_PAGES if who["role"] == "main" else MEMBER_PAGES
        for groups, feature in ((OWN, False), (FEATURES, True)):
            for album in releases_of(sp, who["spotify"], groups, pages[groups]):
                _add(by_key, album, who, feature)
        hunt.progress = index
        hunt.releases = sorted(by_key.values(), key=lambda release: release["date"], reverse=True)
    count = len(hunt.releases)
    if not count:
        hunt.message = t("artists.none", name=display)
    else:
        hunt.message = t("artists.done_group" if people else "artists.done", count=count, name=display)
