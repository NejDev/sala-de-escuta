"""Project paths and loading of .env, playlists.json, and local state."""
from __future__ import annotations

import json
import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

from . import i18n
from .i18n import t

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
TOKEN_FILE = DATA_DIR / "token.json"
STATE_FILE = DATA_DIR / "state.json"
LOG_FILE = DATA_DIR / "assistant.log"
PLAYLISTS_FILE = ROOT / "playlists.json"  # your curation; not in git (the panel writes to it)
PLAYLISTS_EXAMPLE_FILE = ROOT / "playlists.example.json"  # starting point, copied on first run
SENSATIONS_FILE = ROOT / "sensations.json"
BLOCKED_FILE = ROOT / "bloqueados.json"  # legacy single-user file, moved on startup
TEMPO_CACHE_FILE = DATA_DIR / "tempo-cache.json"
MATCH_CACHE_FILE = DATA_DIR / "spotify-matches.json"
SPOTIFY_PAUSES_FILE = DATA_DIR / "spotify-pauses.json"
DEFAULT_REDIRECT_URI = "http://127.0.0.1:8888/callback"


@dataclass(frozen=True)
class Settings:
    client_id: str
    redirect_uri: str  # login callback when the panel is opened on the host PC itself
    public_url: str = ""  # public address (tunnel) that friends use to get in, no trailing slash


@dataclass(frozen=True)
class UserPaths:
    """Files for one person in the room: data/users/<Spotify id>/."""

    id: str
    dir: Path

    @property
    def token(self) -> Path:
        return self.dir / "token.json"

    @property
    def state(self) -> Path:
        return self.dir / "state.json"

    @property
    def blocked(self) -> Path:
        return self.dir / "blocked.json"

    @property
    def favorites(self) -> Path:
        return self.dir / "favorites.json"

    @property
    def recent(self) -> Path:
        return self.dir / "recent.json"


def user_paths(user_id: str) -> UserPaths:
    # Spotify IDs are alphanumeric; anything else could escape the folder.
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,64}", user_id) or user_id.startswith("."):
        raise ValueError(f"invalid user id: {user_id!r}")
    return UserPaths(user_id, DATA_DIR / "users" / user_id)


# Data files from the Portuguese version -> current names (renamed on startup).
RENAMED_FILES = {"bloqueados.json": "blocked.json", "perfil.json": "profile.json"}


def rename_legacy_files() -> None:
    old_pauses = DATA_DIR / "spotify-pausas.json"
    if old_pauses.exists() and not SPOTIFY_PAUSES_FILE.exists():
        old_pauses.rename(SPOTIFY_PAUSES_FILE)
    for folder in (DATA_DIR / "users").glob("*"):
        for old, new in RENAMED_FILES.items():
            if (folder / old).exists() and not (folder / new).exists():
                (folder / old).rename(folder / new)


def list_users() -> list[str]:
    users_dir = DATA_DIR / "users"
    if not users_dir.exists():
        return []
    return sorted(entry.name for entry in users_dir.iterdir() if (entry / "token.json").exists())


def owner_id() -> str | None:
    try:
        return (DATA_DIR / "owner.txt").read_text(encoding="utf-8").strip() or None
    except FileNotFoundError:
        return None


def set_owner(user_id: str) -> None:
    DATA_DIR.mkdir(exist_ok=True)
    (DATA_DIR / "owner.txt").write_text(user_id, encoding="utf-8")


def sessions_file() -> Path:
    return DATA_DIR / "sessions.json"


def parse_env(text: str) -> dict[str, str]:
    values = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip().strip("\"'")
    return values


def load_env() -> None:
    """Reads .env into the environment and sets the command-line language (SALA_LANG)."""
    env_file = ROOT / ".env"
    if env_file.exists():
        # utf-8-sig: Notepad sometimes saves with a BOM
        for key, value in parse_env(env_file.read_text(encoding="utf-8-sig")).items():
            os.environ.setdefault(key, value)
    i18n.use(os.environ.get("SALA_LANG", "").strip().lower()[:2] or None)


def load_settings() -> Settings:
    load_env()
    client_id = os.environ.get("SPOTIFY_CLIENT_ID", "")
    if not client_id:
        raise SystemExit(t("config.no_client_id"))
    return Settings(
        client_id,
        os.environ.get("SPOTIFY_REDIRECT_URI") or DEFAULT_REDIRECT_URI,
        os.environ.get("SALA_PUBLIC_URL", "").strip().rstrip("/"),
    )


def load_playlists() -> dict:
    if not PLAYLISTS_FILE.exists():
        shutil.copyfile(PLAYLISTS_EXAMPLE_FILE, PLAYLISTS_FILE)
    return json.loads(PLAYLISTS_FILE.read_text(encoding="utf-8"))


def load_sensations() -> list[dict]:
    return json.loads(SENSATIONS_FILE.read_text(encoding="utf-8"))["sensations"]


def load_blocked(path: Path | None = None) -> list[str]:
    """Artists that must never show up in discoveries (each person has their own list)."""
    try:
        data = json.loads((path or BLOCKED_FILE).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []
    return data.get("artists", data.get("artistas", []))  # "artistas": files from the Portuguese version


def save_blocked(artists: list[str], path: Path | None = None) -> None:
    path = path or BLOCKED_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {"artists": sorted(set(artists), key=str.casefold)}
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def save_playlists(config: dict) -> None:
    PLAYLISTS_FILE.write_text(json.dumps(config, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


class State(dict):
    """A person's state (playlist IDs...) and the file it came from."""

    path: Path | None = None


def load_state(path: Path | None = None) -> State:
    path = path or STATE_FILE
    try:
        state = State(json.loads(path.read_text(encoding="utf-8")))
    except FileNotFoundError:
        state = State()
    state.path = path
    return state


def save_state(state: dict) -> None:
    path = getattr(state, "path", None) or STATE_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
