"""People in the room: registration at login, browser sessions, and migration from the single-person version.

In Development Mode Spotify accepts up to 5 accounts, which the owner must allow
under "User Management" in Spotify for Developers. Anyone not allowed gets a 403 on /me.
"""
from __future__ import annotations

import json
import logging
import secrets
import shutil
import threading
import time
from dataclasses import dataclass

from . import config
from .api import Spotify, SpotifyError
from .auth import TokenManager, save_token
from .config import Settings

SESSION_DAYS = 90
PROFILE = "profile.json"  # display name, written at sign-in

log = logging.getLogger(__name__)


class NotInvited(Exception):
    """The account isn't on the app's list of allowed people."""


@dataclass(frozen=True)
class Person:
    id: str
    name: str


def register(token: dict, market: str = "BR") -> Person:
    """Finds out whose token it is, saves it in that person's folder, and sets the owner if there isn't one yet."""
    try:
        me = Spotify(lambda: token["access_token"], market).me()
    except SpotifyError as err:
        if err.status == 403:
            raise NotInvited() from None
        raise
    paths = config.user_paths(me["id"])
    save_token(token, paths.token)
    if config.owner_id() is None:
        config.set_owner(me["id"])
    person = Person(me["id"], me.get("display_name") or me["id"])
    _remember_name(person)
    log.info("%s joined the room.", person.name)
    return person


def display_name(user_id: str) -> str:
    try:
        return json.loads((config.user_paths(user_id).dir / PROFILE).read_text(encoding="utf-8"))["name"]
    except (FileNotFoundError, ValueError, KeyError):
        return user_id


def _remember_name(person: Person) -> None:
    profile = config.user_paths(person.id).dir / PROFILE
    profile.write_text(json.dumps({"name": person.name}, ensure_ascii=False), encoding="utf-8")


def migrate_legacy(settings: Settings) -> None:
    """The single-person version stored everything directly in data/: it becomes the owner's profile."""
    config.rename_legacy_files()
    if config.owner_id() or not config.TOKEN_FILE.exists():
        return
    tokens = TokenManager(settings, config.TOKEN_FILE)
    me = Spotify(tokens, "BR").me()
    paths = config.user_paths(me["id"])
    paths.dir.mkdir(parents=True, exist_ok=True)
    for old, new in ((config.TOKEN_FILE, paths.token), (config.STATE_FILE, paths.state), (config.BLOCKED_FILE, paths.blocked)):
        if old.exists() and not new.exists():
            shutil.move(str(old), str(new))
    config.set_owner(me["id"])
    _remember_name(Person(me["id"], me.get("display_name") or me["id"]))
    log.info("Old data moved to the profile of %s (room owner).", me.get("display_name") or me["id"])


class Sessions:
    """Browser cookie -> person. Stored on disk to survive panel restarts."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        try:
            self._data: dict[str, dict] = json.loads(config.sessions_file().read_text(encoding="utf-8"))
        except (FileNotFoundError, ValueError):
            self._data = {}

    def create(self, user_id: str) -> str:
        token = secrets.token_urlsafe(32)
        with self._lock:
            self._data[token] = {"user": user_id, "created": time.time()}
            self._save()
        return token

    def user(self, token: str | None) -> str | None:
        if not token:
            return None
        with self._lock:
            entry = self._data.get(token)
        if not entry or time.time() - entry["created"] > SESSION_DAYS * 86400:
            return None
        return entry["user"]

    def end(self, token: str | None) -> None:
        with self._lock:
            if token and self._data.pop(token, None) is not None:
                self._save()

    def end_all(self, user_id: str) -> None:
        with self._lock:
            self._data = {token: entry for token, entry in self._data.items() if entry["user"] != user_id}
            self._save()

    def _save(self) -> None:
        path = config.sessions_file()
        path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps(self._data), encoding="utf-8")
