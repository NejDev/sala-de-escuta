"""Favorites (the playlists in the top bar, which rebuild themselves) and recent finds.

Each person has data/users/<id>/favorites.json. A favorite is either one of the owner's
curated playlists (playlists.json) or a playlist created from a discovery together with its
"recipe": the same parameters the panel sends to start that discovery. Every favorite has a
frequency (daily, weekly or monthly); on each update its songs are replaced with a fresh selection.

recent.json keeps the last songs the person saved or added, for the home screen.
"""
from __future__ import annotations

import json
import secrets
import threading
import time
from pathlib import Path
from typing import Callable

from . import config

EVERY = {"daily": 86400, "weekly": 7 * 86400, "monthly": 30 * 86400}
MAX_FAVORITES = 8  # made from discoveries; the owner's curated playlists don't count
RECENT_MAX = 30
# Bar color for favorites made from discoveries (sensations use their own color).
KIND_COLORS = {"sense": "#7FB7BE", "roulette": "#F2C14E", "rabbit": "#9DB4E6", "news": "#E3909E"}

_lock = threading.Lock()  # the panel's requests and the scheduler write these files


def _read(path: Path, key: str) -> list[dict]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))[key]
    except (FileNotFoundError, ValueError, KeyError):
        return []


def _write(path: Path, key: str, items: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({key: items}, indent=2, ensure_ascii=False), encoding="utf-8")


def load(user_id: str) -> list[dict]:
    return _read(config.user_paths(user_id).favorites, "favorites")


def change(user_id: str, edit: Callable[[list[dict]], object]) -> object:
    """Reads, edits and saves the person's favorites under one lock; returns what edit returns."""
    path = config.user_paths(user_id).favorites
    with _lock:
        items = _read(path, "favorites")
        result = edit(items)
        _write(path, "favorites", items)
    return result


def new(kind: str, name: str, every: str, *, playlist_id: str | None = None, recipe: dict | None = None,
        color: str | None = None, lang: str = "en", filled: bool = True, now: float | None = None) -> dict:
    now = time.time() if now is None else now
    return {
        "id": secrets.token_hex(6),
        "kind": kind,  # curated | discovery
        "name": name,
        "every": every,
        "playlist_id": playlist_id,
        "recipe": recipe,
        "color": color,
        "lang": lang,  # language of the messages and descriptions of automatic updates
        "created": now,
        "last_run": now,  # the schedule counts from here: the first update comes one period later
        "updated": now if filled else None,  # when the songs were last replaced (shown as "last updated")
        "status": "ok",
        "message": "",
    }


def next_run(fav: dict) -> float:
    last = fav.get("last_run")
    return (fav["created"] if last is None else last) + EVERY[fav["every"]]


def is_due(fav: dict, now: float) -> bool:
    return now >= next_run(fav)


def sync_curated(user_id: str, specs: list[dict], now: float | None = None) -> list[dict]:
    """The owner gets one favorite per curated playlist, following playlists.json as it changes."""
    now = time.time() if now is None else now
    names = {spec["name"] for spec in specs}
    path = config.user_paths(user_id).favorites
    with _lock:
        items = _read(path, "favorites")
        kept = [fav for fav in items if fav["kind"] != "curated" or fav["name"] in names]
        have = {fav["name"] for fav in kept if fav["kind"] == "curated"}
        added = [
            new("curated", spec["name"], "weekly" if spec.get("refresh") == "weekly" else "monthly",
                filled=False, now=now)
            for spec in specs if spec["name"] not in have
        ]
        # Curated first, in playlists.json order, then the ones made from discoveries.
        order = {spec["name"]: index for index, spec in enumerate(specs)}
        result = sorted([*kept, *added], key=lambda fav: (fav["kind"] != "curated", order.get(fav["name"], 0)))
        if result != items:
            _write(path, "favorites", result)
    return result


# ---------- Recent finds


def recent(user_id: str) -> list[dict]:
    return _read(config.user_paths(user_id).recent, "finds")


def remember(user_id: str, finds: list[dict], playlist: str, now: float | None = None) -> None:
    """Newest first; a song saved again moves back to the top."""
    if not finds:
        return
    now = time.time() if now is None else now
    path = config.user_paths(user_id).recent
    keys = ("uri", "title", "subtitle", "image", "duration_ms")
    fresh = [{**{key: find.get(key) for key in keys}, "playlist": playlist, "at": now} for find in finds]
    uris = {find["uri"] for find in fresh}
    with _lock:
        older = [find for find in _read(path, "finds") if find["uri"] not in uris]
        _write(path, "finds", (fresh + older)[:RECENT_MAX])
