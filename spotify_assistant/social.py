"""Friends: musical affinity and matches (the same song, close in time) among people who join.

Only for people who turn it on (data/users/<id>/social.json); everyone else stays invisible.
What a friend plays alone is never shown, only the songs you both played.
The owner decides who may use it at all (data/room.json): per person, plus a default for people
who join the room later.
Plays come from Spotify's recently played list (the last 50), read every 15 minutes while the
panel is open, and are kept for 90 days in plays.json.
"""
from __future__ import annotations

import json
import math
import threading
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

from . import config
from .api import Spotify
from .views import pick_image

KEEP_DAYS = 90
AFFINITY_DAYS = 30
MIN_PLAYS = 10  # below this an affinity number would be noise
MATCH_WINDOW_S = 6 * 3600  # same song within 6 hours of each other
MATCH_DAYS = 7
FEED_SIZE = 40
COLLECT_EVERY_S = 15 * 60
DAY = 86400

_lock = threading.Lock()


def _paths(user_id: str) -> tuple[Path, Path]:
    folder = config.user_paths(user_id).dir
    return folder / "social.json", folder / "plays.json"


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
        social_file.parent.mkdir(parents=True, exist_ok=True)
        social_file.write_text(json.dumps(current), encoding="utf-8")


def plays(user_id: str) -> list[dict]:
    return _read(_paths(user_id)[1], [])


def _play(item: dict) -> dict | None:
    track = item.get("track") or {}
    if not track.get("uri"):
        return None
    when = datetime.fromisoformat(item["played_at"].replace("Z", "+00:00")).timestamp()
    return {
        "uri": track["uri"],
        "title": track.get("name", ""),
        "artists": [{"id": a.get("id"), "name": a.get("name", "")} for a in track.get("artists", [])],
        "image": pick_image((track.get("album") or {}).get("images"), 64),
        "duration_ms": track.get("duration_ms") or 0,
        "at": when,
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


def _cosine(a: Counter, b: Counter) -> float:
    # log scale: one artist on repeat doesn't drown out everything else
    wa = {key: math.log1p(count) for key, count in a.items()}
    wb = {key: math.log1p(count) for key, count in b.items()}
    dot = sum(wa[key] * wb[key] for key in wa.keys() & wb.keys())
    norm = math.sqrt(sum(v * v for v in wa.values())) * math.sqrt(sum(v * v for v in wb.values()))
    return dot / norm if norm else 0.0


def affinity(mine: list[dict], theirs: list[dict], now: float | None = None) -> dict | None:
    """Musical affinity (0-100) over the last 30 days: mostly shared artists, partly shared songs."""
    now = time.time() if now is None else now
    a, b = _recent(mine, now, AFFINITY_DAYS), _recent(theirs, now, AFFINITY_DAYS)
    if len(a) < MIN_PLAYS or len(b) < MIN_PLAYS:
        return None
    artists_a = Counter(artist["id"] for play in a for artist in play["artists"][:1])
    artists_b = Counter(artist["id"] for play in b for artist in play["artists"][:1])
    tracks_a, tracks_b = Counter(play["uri"] for play in a), Counter(play["uri"] for play in b)
    score = 0.7 * _cosine(artists_a, artists_b) + 0.3 * _cosine(tracks_a, tracks_b)
    names = {artist["id"]: artist["name"] for play in a + b for artist in play["artists"][:1]}
    shared = sorted(artists_a.keys() & artists_b.keys(), key=lambda key: -min(artists_a[key], artists_b[key]))
    # A gentle curve: people with similar taste rarely overlap song by song, so raw cosine undersells it.
    return {"percent": round(100 * min(1.0, score) ** 0.6), "shared": [names[key] for key in shared[:3]]}


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
