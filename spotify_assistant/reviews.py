"""Album reviews, Letterboxd style: a rating in half stars and a few words, private or open to the room.

Each person's reviews live in data/users/<id>/reviews.json, one per album. A private review never
leaves its author's screen; an open one shows up for everyone in the room, with the author's name.
"""
from __future__ import annotations

import json
import re
import threading
import time
from pathlib import Path

from . import config

MAX_TEXT = 2000
ROOM_SIZE = 60  # newest open reviews on the Reviews page
ALBUM_ID = re.compile(r"[A-Za-z0-9]{22}")
ALBUM_LINK = re.compile(r"(?:open\.spotify\.com/(?:intl-[a-z-]+/)?album/|spotify:album:)([A-Za-z0-9]{22})")

_lock = threading.Lock()


def album_id(text: str) -> str | None:
    """The album id in a Spotify link, a spotify:album: URI or the bare id."""
    text = (text or "").strip()
    if ALBUM_ID.fullmatch(text):
        return text
    found = ALBUM_LINK.search(text)
    return found.group(1) if found else None


def rating(value) -> float | None:
    """Half stars from 0.5 to 5; nothing (None, 0, "") means no rating. Raises ValueError otherwise."""
    if value in (None, "", 0):
        return None
    number = float(value)
    if not 0.5 <= number <= 5 or number * 2 != int(number * 2):
        raise ValueError(value)
    return number


def _file(user_id: str) -> Path:
    return config.user_paths(user_id).dir / "reviews.json"


def mine(user_id: str) -> dict[str, dict]:
    """album id -> review, private ones included (only for their author)."""
    try:
        return json.loads(_file(user_id).read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return {}


def save(user_id: str, album: dict, stars: float | None, text: str, public: bool, now: float | None = None) -> dict:
    now = time.time() if now is None else now
    with _lock:
        reviews = mine(user_id)
        old = reviews.get(album["id"])
        review = {"album": album, "rating": stars, "text": text, "public": public,
                  "at": old["at"] if old else now, "updated": now}
        reviews[album["id"]] = review
        path = _file(user_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(reviews, ensure_ascii=False), encoding="utf-8")
    return review


def delete(user_id: str, album: str) -> bool:
    with _lock:
        reviews = mine(user_id)
        if reviews.pop(album, None) is None:
            return False
        _file(user_id).write_text(json.dumps(reviews, ensure_ascii=False), encoding="utf-8")
    return True


def known_album(album: str, users: list[str]) -> dict | None:
    """The album's details as saved with someone's review, so Spotify isn't asked again."""
    for user_id in users:
        review = mine(user_id).get(album)
        if review:
            return review["album"]
    return None


def _shown(review: dict, author: str, names: dict[str, str], viewer: str) -> dict:
    return {**review, "author": names.get(author, ""), "own": author == viewer}


def room(viewer: str, users: list[str], names: dict[str, str]) -> list[dict]:
    """Open reviews from everyone in the room (the viewer's open ones too), newest first."""
    found = [_shown(review, user_id, names, viewer)
             for user_id in users for review in mine(user_id).values() if review["public"]]
    return sorted(found, key=lambda review: review["updated"], reverse=True)[:ROOM_SIZE]


def own(viewer: str, names: dict[str, str]) -> list[dict]:
    found = [_shown(review, viewer, names, viewer) for review in mine(viewer).values()]
    return sorted(found, key=lambda review: review["updated"], reverse=True)


def of_album(album: str, viewer: str, users: list[str], names: dict[str, str]) -> dict:
    """The viewer's review (open or not), everyone else's open reviews, and the average of open ratings."""
    own_review = mine(viewer).get(album)
    others = []
    for user_id in users:
        review = mine(user_id).get(album) if user_id != viewer else None
        if review and review["public"]:
            others.append(_shown(review, user_id, names, viewer))
    others.sort(key=lambda review: review["updated"], reverse=True)
    open_reviews = others + ([own_review] if own_review and own_review["public"] else [])
    ratings = [review["rating"] for review in open_reviews if review["rating"]]
    return {
        "mine": _shown(own_review, viewer, names, viewer) if own_review else None,
        "room": others,
        "average": round(sum(ratings) / len(ratings), 1) if ratings else None,
        "count": len(ratings),
    }
