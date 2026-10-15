"""Artists: everything a band or artist released, its members' solo work and their features.

The band and its members (and subunits) come from MusicBrainz, with their Spotify profiles;
each one's releases come from Spotify: their own (albums, singles and EPs, compilations) and
the ones they appear on (features, soundtracks). Everything is merged into one list.
"""
from __future__ import annotations

import logging
import threading
import time

from . import curation
from .api import Spotify, SpotifyError
from .discovery import Hunt, is_religious
from .i18n import t
from .musicbrainz import MusicBrainz, MusicBrainzError
from .views import pick_image

OWN = "album,single,compilation"
FEATURES = "appears_on"
MAX_PEOPLE = 16  # the artist plus members and subunits read in one search
MAX_CANDIDATES = 8  # "which one?" cards when several artists share a name
CACHE_TTL_S = 6 * 3600  # releases don't change by the minute; repeated searches cost nothing

log = logging.getLogger(__name__)
_cache: dict[tuple[str, str], tuple[float, list[dict]]] = {}
_cache_lock = threading.Lock()


def releases_of(sp: Spotify, artist_id: str, groups: str) -> list[dict]:
    with _cache_lock:
        hit = _cache.get((artist_id, groups))
    if hit and time.time() - hit[0] < CACHE_TTL_S:
        return hit[1]
    albums = sp.artist_albums(artist_id, groups)
    with _cache_lock:
        _cache[(artist_id, groups)] = (time.time(), albums)
    return albums


def spotify_artist(sp: Spotify, name: str, unique: bool = False) -> dict | None:
    """Spotify search by name; for members, only an unambiguous exact match (there are many "MINA"s)."""
    found = sp.search(name, "artist")
    exact = [artist for artist in found if curation.normalize(artist.get("name", "")) == curation.normalize(name)]
    if unique:
        return exact[0] if len(exact) == 1 else None
    return (exact or found or [None])[0]


def candidate(sp: Spotify, artist: dict) -> dict:
    """A card for "which one?": photo, genres and their latest release, so the person recognizes them."""
    latest = None
    try:
        albums = sp.artist_albums(artist["id"], "album,single", max_pages=1)
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
            for member in info["members"][:MAX_PEOPLE]:
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
                hunt.candidates = [candidate(sp, artist) for artist in (exact or found)[:MAX_CANDIDATES]]
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
    profile = sp.artist(person["spotify"]) or {}
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
        for groups, feature in ((OWN, False), (FEATURES, True)):
            for album in releases_of(sp, who["spotify"], groups):
                _add(by_key, album, who, feature)
        hunt.progress = index
        hunt.releases = sorted(by_key.values(), key=lambda release: release["date"], reverse=True)
    count = len(hunt.releases)
    if not count:
        hunt.message = t("artists.none", name=display)
    else:
        hunt.message = t("artists.done_group" if people else "artists.done", count=count, name=display)
