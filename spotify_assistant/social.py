"""Friends: musical affinity and matches (the same song, close in time) among people who join.

The affinity compares taste profiles: Spotify's most played artists, the artists in the playlists the
person made and in their liked songs (taste.json, rebuilt every 3 days in the background), plus what
they played in the last 30 days. Only the artists two people have in common are ever named.

Only for people who turn it on (data/users/<id>/social.json); everyone else stays invisible.
What a friend plays alone is never shown, only the songs you both played.
The owner decides who may use it at all (data/room.json): per person, plus a default for people
who join the room later.
Plays come from Spotify's recently played list (the last 50), read every 15 minutes while the
panel is open, and are kept for 90 days in plays.json.
"""
from __future__ import annotations

import json
import logging
import math
import threading
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

from . import config
from .api import Spotify, SpotifyError
from .views import pick_image

KEEP_DAYS = 90
AFFINITY_DAYS = 30
MIN_PLAYS = 10  # recent plays count only from this many on
MIN_ARTISTS = 5  # below this an affinity number would be noise
MATCH_WINDOW_S = 6 * 3600  # same song within 6 hours of each other
MATCH_DAYS = 7
FEED_SIZE = 40
COLLECT_EVERY_S = 15 * 60
DAY = 86400
TASTE_EVERY_S = 3 * DAY  # most played, playlists and likes change slowly
TASTE_PLAYLISTS = 20  # the person's own playlists read, in their library's order
TASTE_PLAYLIST_ITEMS = 100
TASTE_LIKED = 100
TASTE_PAUSE_S = 1.5  # between requests: it runs in the background, no hurry
TOP_RANGES = {"short_term": 0.3, "medium_term": 0.4, "long_term": 0.3}
# How much each source counts (a source someone doesn't have just drops out).
SOURCE_WEIGHTS = {"top": 0.4, "playlists": 0.25, "liked": 0.2, "plays": 0.15}

log = logging.getLogger(__name__)
_lock = threading.Lock()


def _paths(user_id: str) -> tuple[Path, Path]:
    folder = config.user_paths(user_id).dir
    return folder / "social.json", folder / "plays.json"


def _taste_file(user_id: str) -> Path:
    return config.user_paths(user_id).dir / "taste.json"


def _read(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return default


# ---------- who may use Friends (the owner decides)


def _room_file() -> Path:
    return config.DATA_DIR / "room.json"


def access() -> dict:
    """{"new": allow people who join later, "people": {user id: allowed}} (the owner is always allowed)."""
    room = _read(_room_file(), {})
    return {"new": room.get("friends_new", True), "people": room.get("friends_people", {})}


def allowed(user_id: str) -> bool:
    if user_id == config.owner_id():
        return True
    rules = access()
    return bool(rules["people"].get(user_id, rules["new"]))


def _save_access(rules: dict) -> None:
    room = _read(_room_file(), {})
    room.update(friends_new=rules["new"], friends_people=rules["people"])
    config.DATA_DIR.mkdir(exist_ok=True)
    _room_file().write_text(json.dumps(room, indent=2), encoding="utf-8")


def set_allowed(user_id: str, allow: bool) -> None:
    with _lock:
        rules = access()
        rules["people"][user_id] = allow
        _save_access(rules)
    if not allow:
        set_share(user_id, False, forget=True)  # out of Friends: their plays stop showing and are deleted


def set_new(allow: bool, current_users: list[str]) -> None:
    """Changing the default doesn't touch people already in the room: they keep what they had."""
    with _lock:
        rules = access()
        for user_id in current_users:
            if user_id != config.owner_id():
                rules["people"].setdefault(user_id, rules["new"])
        rules["new"] = allow
        _save_access(rules)


# ---------- each person's choice and plays


def settings(user_id: str) -> dict:
    return _read(_paths(user_id)[0], {"share": False, "after": None})


def sharing(user_id: str) -> bool:
    return bool(settings(user_id).get("share"))


def set_share(user_id: str, share: bool, forget: bool = False) -> None:
    social_file, plays_file = _paths(user_id)
    with _lock:
        current = _read(social_file, {"share": False, "after": None})
        current["share"] = share
        if forget:
            current["after"] = None
            plays_file.unlink(missing_ok=True)
            _taste_file(user_id).unlink(missing_ok=True)
        social_file.parent.mkdir(parents=True, exist_ok=True)
        social_file.write_text(json.dumps(current), encoding="utf-8")


def plays(user_id: str) -> list[dict]:
    return _read(_paths(user_id)[1], [])


def _play(item: dict) -> dict | None:
    track = item.get("track") or {}
    if not track.get("uri"):
        return None
    when = datetime.fromisoformat(item["played_at"].replace("Z", "+00:00")).timestamp()
    album = track.get("album") or {}
    context = item.get("context") or {}
    return {
        "uri": track["uri"],
        "title": track.get("name", ""),
        "artists": [{"id": a.get("id"), "name": a.get("name", "")} for a in track.get("artists", [])],
        "image": pick_image(album.get("images"), 64),
        "duration_ms": track.get("duration_ms") or 0,
        "at": when,
        # For achievements (already in the answer; older plays don't have them).
        "album": {"id": album.get("id"), "name": album.get("name", ""), "type": album.get("album_type"),
                  "release": album.get("release_date"), "tracks": album.get("total_tracks")},
        "track_number": track.get("track_number"),
        "context": {"type": context["type"], "uri": context.get("uri")} if context.get("type") else None,
    }


def collect(sp: Spotify, user_id: str, now: float | None = None) -> int:
    """Adds what the person listened to since the last read; returns how many plays are new."""
    now = time.time() if now is None else now
    items = sp.recently_played(after=settings(user_id).get("after"))
    fresh = [play for play in map(_play, items) if play]
    social_file, plays_file = _paths(user_id)
    with _lock:
        known = _read(plays_file, [])
        seen = {(play["uri"], play["at"]) for play in known}
        added = [play for play in fresh if (play["uri"], play["at"]) not in seen]
        kept = [play for play in known + added if play["at"] >= now - KEEP_DAYS * DAY]
        kept.sort(key=lambda play: play["at"])
        plays_file.parent.mkdir(parents=True, exist_ok=True)
        plays_file.write_text(json.dumps(kept, ensure_ascii=False), encoding="utf-8")
        current = _read(social_file, {"share": False, "after": None})
        if fresh:
            current["after"] = int(max(play["at"] for play in fresh) * 1000)
        current["collected"] = now
        social_file.write_text(json.dumps(current), encoding="utf-8")
    return len(added)


def _recent(items: list[dict], now: float, days: int) -> list[dict]:
    return [play for play in items if play["at"] >= now - days * DAY]


# ---------- taste: what a person likes beyond their last 50 songs


def taste(user_id: str) -> dict:
    return _read(_taste_file(user_id), {})


def taste_due(user_id: str, with_top: bool, now: float | None = None) -> bool:
    now = time.time() if now is None else now
    known = taste(user_id)
    return not known or now - known.get("at", 0) > TASTE_EVERY_S or (with_top and not known.get("top_tried"))


def build_taste(sp: Spotify, user_id: str, with_top: bool, pause=time.sleep, now: float | None = None) -> dict:
    """Most played artists (4 weeks, 6 months, a year), and the artists in the playlists the person made
    and in their liked songs. A source that fails is just left out."""
    sources: dict[str, dict[str, float]] = {}
    names: dict[str, str] = {}

    def weights(tracks: list[dict]) -> dict[str, float]:
        counts: Counter = Counter()
        for track in tracks:
            if track.get("type", "track") != "track":
                continue  # podcast episodes say nothing about music taste
            for artist in track.get("artists", []):
                if artist.get("id"):
                    counts[artist["id"]] += 1
                    names[artist["id"]] = artist.get("name", "")
        return {key: math.log1p(count) for key, count in counts.items()}  # one artist on repeat doesn't drown the rest

    if with_top:
        top: Counter = Counter()
        for time_range, weight in TOP_RANGES.items():
            try:
                found = sp.top_artists(time_range)
            except SpotifyError as err:
                log.warning("Couldn't read %s's most played (%s): %s", user_id, time_range, err)
                continue
            finally:
                pause(TASTE_PAUSE_S)
            for rank, artist in enumerate(found):
                top[artist["id"]] += weight * (1 - rank / len(found))
                names[artist["id"]] = artist.get("name", "")
        if top:
            sources["top"] = dict(top)
    tracks: list[dict] = []
    try:
        own = [playlist for playlist in sp.my_playlists() if (playlist.get("owner") or {}).get("id") == user_id]
        for playlist in own[:TASTE_PLAYLISTS]:
            pause(TASTE_PAUSE_S)
            try:
                tracks += sp.playlist_items(playlist["id"], max_items=TASTE_PLAYLIST_ITEMS)
            except SpotifyError as err:
                log.warning("Couldn't read playlist %s: %s", playlist.get("id"), err)
    except SpotifyError as err:
        log.warning("Couldn't list %s's playlists: %s", user_id, err)
    if found_weights := weights(tracks):
        sources["playlists"] = found_weights
    try:
        pause(TASTE_PAUSE_S)
        if found_weights := weights(sp.saved_tracks(TASTE_LIKED)):
            sources["liked"] = found_weights
    except SpotifyError as err:
        log.warning("Couldn't read %s's liked songs: %s", user_id, err)
    result = {"at": time.time() if now is None else now, "top_tried": with_top, "sources": sources, "names": names}
    with _lock:
        path = _taste_file(user_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    return result


def _unit(weights: dict[str, float]) -> dict[str, float]:
    norm = math.sqrt(sum(value * value for value in weights.values()))
    return {key: value / norm for key, value in weights.items()} if norm else {}


def profile(user_plays: list[dict], user_taste: dict, now: float | None = None) -> dict[str, float]:
    """One vector of the artists a person likes, mixing every source they have."""
    now = time.time() if now is None else now
    sources = dict(user_taste.get("sources") or {})
    recent = _recent(user_plays, now, AFFINITY_DAYS)
    if len(recent) >= MIN_PLAYS:
        counts = Counter(artist["id"] for play in recent for artist in play["artists"][:1])
        sources["plays"] = {key: math.log1p(count) for key, count in counts.items()}
    combined: Counter = Counter()
    for source, weights in sources.items():
        for key, value in _unit(weights).items():
            combined[key] += SOURCE_WEIGHTS.get(source, 0) * value
    return dict(combined)


def artist_names(user_plays: list[dict], user_taste: dict) -> dict[str, str]:
    names = dict(user_taste.get("names") or {})
    names.update({artist["id"]: artist["name"] for play in user_plays for artist in play["artists"]})
    return names


def affinity(mine: dict[str, float], theirs: dict[str, float], names: dict[str, str]) -> dict | None:
    """Musical affinity (0-100) between two taste profiles, and the artists they have in common."""
    if len(mine) < MIN_ARTISTS or len(theirs) < MIN_ARTISTS:
        return None
    common = mine.keys() & theirs.keys()
    dot = sum(mine[key] * theirs[key] for key in common)
    norm = math.sqrt(sum(v * v for v in mine.values())) * math.sqrt(sum(v * v for v in theirs.values()))
    score = dot / norm if norm else 0.0
    shared = [names[key] for key in sorted(common, key=lambda key: -min(mine[key], theirs[key])) if names.get(key)]
    # A gentle curve: even close friends share a small part of everything they like.
    return {"percent": round(100 * min(1.0, score) ** 0.6), "shared": shared[:3]}


def matches(mine: list[dict], theirs: list[dict], now: float | None = None) -> list[dict]:
    """Songs both played within 6 hours of each other in the last week (the latest time for each song)."""
    now = time.time() if now is None else now
    found: dict[str, dict] = {}
    recent_theirs = _recent(theirs, now, MATCH_DAYS)
    for play in _recent(mine, now, MATCH_DAYS):
        for other in recent_theirs:
            gap = abs(play["at"] - other["at"])
            if other["uri"] == play["uri"] and gap <= MATCH_WINDOW_S:
                at = max(play["at"], other["at"])
                if at > found.get(play["uri"], {}).get("at", 0):
                    found[play["uri"]] = {"track": play, "at": at, "gap_s": gap}
    return list(found.values())


def stats(items: list[dict], now: float | None = None) -> dict:
    now = time.time() if now is None else now
    week = _recent(items, now, 7)
    last = max(items, key=lambda play: play["at"], default=None)
    return {"plays_7d": len(week), "last": last}


def feed(friends: dict[str, list[dict]], names: dict[str, str], me: str, now: float | None = None) -> list[dict]:
    """Matches between me and each friend in the last week, newest first."""
    now = time.time() if now is None else now
    events = []
    for friend, items in friends.items():
        if friend == me:
            continue
        for match in matches(friends.get(me, []), items, now):
            events.append({"friend": names[friend], "at": match["at"], "gap_s": match["gap_s"], "track": match["track"]})
    events.sort(key=lambda event: event["at"], reverse=True)
    return events[:FEED_SIZE]
