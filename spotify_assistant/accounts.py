"""Pessoas da sala: cadastro no login, sessões do navegador e migração da versão de uma pessoa só.

No Development Mode a Spotify aceita até 5 contas, que precisam ser liberadas pelo dono
em "User Management" no Spotify for Developers. Quem não foi liberado recebe 403 no /me.
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

log = logging.getLogger(__name__)


class NotInvited(Exception):
    """A conta não está na lista de pessoas liberadas do app."""


@dataclass(frozen=True)
class Person:
    id: str
    name: str


def register(token: dict, market: str = "BR") -> Person:
    """Descobre de quem é o token, guarda na pasta da pessoa e define o dono se ainda não houver."""
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
    log.info("%s entrou na sala.", person.name)
    return person


def display_name(user_id: str) -> str:
    try:
        return json.loads((config.user_paths(user_id).dir / "perfil.json").read_text(encoding="utf-8"))["name"]
    except (FileNotFoundError, ValueError, KeyError):
        return user_id


def _remember_name(person: Person) -> None:
    profile = config.user_paths(person.id).dir / "perfil.json"
    profile.write_text(json.dumps({"name": person.name}, ensure_ascii=False), encoding="utf-8")


def migrate_legacy(settings: Settings) -> None:
    """A versão de uma pessoa só guardava tudo direto em data/: vira o perfil do dono."""
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
    log.info("Dados antigos movidos para o perfil de %s (dono da sala).", me.get("display_name") or me["id"])


class Sessions:
    """Cookie do navegador -> pessoa. Guardado em disco para sobreviver a reinícios do painel."""

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
