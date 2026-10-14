"""Caminhos do projeto, leitura do .env, do playlists.json e do estado local."""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
TOKEN_FILE = DATA_DIR / "token.json"
STATE_FILE = DATA_DIR / "state.json"
LOG_FILE = DATA_DIR / "assistant.log"
PLAYLISTS_FILE = ROOT / "playlists.json"
SENSATIONS_FILE = ROOT / "sensacoes.json"
BLOCKED_FILE = ROOT / "bloqueados.json"
TEMPO_CACHE_FILE = DATA_DIR / "tempo-cache.json"
MATCH_CACHE_FILE = DATA_DIR / "spotify-matches.json"
SPOTIFY_PAUSES_FILE = DATA_DIR / "spotify-pausas.json"
DEFAULT_REDIRECT_URI = "http://127.0.0.1:8888/callback"


@dataclass(frozen=True)
class Settings:
    client_id: str
    redirect_uri: str  # volta do login quando o painel é aberto no próprio PC
    public_url: str = ""  # endereço público (túnel) por onde os amigos entram, sem barra no fim


@dataclass(frozen=True)
class UserPaths:
    """Arquivos de uma pessoa da sala: data/users/<id do Spotify>/."""

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
        return self.dir / "bloqueados.json"


def user_paths(user_id: str) -> UserPaths:
    # IDs do Spotify são alfanuméricos; qualquer outra coisa poderia escapar da pasta.
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,64}", user_id) or user_id.startswith("."):
        raise ValueError(f"id de usuário inválido: {user_id!r}")
    return UserPaths(user_id, DATA_DIR / "users" / user_id)


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


def load_settings() -> Settings:
    env_file = ROOT / ".env"
    if env_file.exists():
        # utf-8-sig: o Bloco de Notas às vezes salva com BOM
        for key, value in parse_env(env_file.read_text(encoding="utf-8-sig")).items():
            os.environ.setdefault(key, value)
    client_id = os.environ.get("SPOTIFY_CLIENT_ID", "")
    if not client_id:
        raise SystemExit("Defina SPOTIFY_CLIENT_ID no arquivo .env (veja .env.example).")
    return Settings(
        client_id,
        os.environ.get("SPOTIFY_REDIRECT_URI") or DEFAULT_REDIRECT_URI,
        os.environ.get("SALA_PUBLIC_URL", "").strip().rstrip("/"),
    )


def load_playlists() -> dict:
    return json.loads(PLAYLISTS_FILE.read_text(encoding="utf-8"))


def load_sensations() -> list[dict]:
    return json.loads(SENSATIONS_FILE.read_text(encoding="utf-8"))["sensacoes"]


def load_blocked(path: Path | None = None) -> list[str]:
    """Artistas que nunca devem aparecer nas descobertas (cada pessoa tem a sua lista)."""
    try:
        return json.loads((path or BLOCKED_FILE).read_text(encoding="utf-8"))["artistas"]
    except FileNotFoundError:
        return []


def save_blocked(artists: list[str], path: Path | None = None) -> None:
    path = path or BLOCKED_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {"artistas": sorted(set(artists), key=str.casefold)}
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def save_playlists(config: dict) -> None:
    PLAYLISTS_FILE.write_text(json.dumps(config, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


class State(dict):
    """O estado de uma pessoa (IDs das playlists...) e o arquivo de onde ele veio."""

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
