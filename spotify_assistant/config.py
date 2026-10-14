"""Caminhos do projeto, leitura do .env, do playlists.json e do estado local."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
TOKEN_FILE = DATA_DIR / "token.json"
STATE_FILE = DATA_DIR / "state.json"
LOG_FILE = DATA_DIR / "assistant.log"
PLAYLISTS_FILE = ROOT / "playlists.json"
SENSATIONS_FILE = ROOT / "sensacoes.json"
TEMPO_CACHE_FILE = DATA_DIR / "tempo-cache.json"
DEFAULT_REDIRECT_URI = "http://127.0.0.1:8888/callback"


@dataclass(frozen=True)
class Settings:
    client_id: str
    redirect_uri: str


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
    return Settings(client_id, os.environ.get("SPOTIFY_REDIRECT_URI") or DEFAULT_REDIRECT_URI)


def load_playlists() -> dict:
    return json.loads(PLAYLISTS_FILE.read_text(encoding="utf-8"))


def load_sensations() -> list[dict]:
    return json.loads(SENSATIONS_FILE.read_text(encoding="utf-8"))["sensacoes"]


def save_playlists(config: dict) -> None:
    PLAYLISTS_FILE.write_text(json.dumps(config, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def load_state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}


def save_state(state: dict) -> None:
    DATA_DIR.mkdir(exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
