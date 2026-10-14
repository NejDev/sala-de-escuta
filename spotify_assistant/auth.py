"""Login OAuth (Authorization Code + PKCE) e renovação automática do token.

Com PKCE o Client Secret não é necessário: só o Client ID fica no .env.
"""
from __future__ import annotations

import base64
import hashlib
import http.server
import json
import logging
import secrets
import threading
import time
import urllib.parse
import webbrowser
from dataclasses import dataclass

from .api import SpotifyError, http_request
from .config import TOKEN_FILE, Settings

AUTHORIZE_URL = "https://accounts.spotify.com/authorize"
TOKEN_URL = "https://accounts.spotify.com/api/token"
SCOPES = (
    "playlist-read-private playlist-modify-private playlist-modify-public "
    "user-read-playback-state user-modify-playback-state user-read-currently-playing"
)
LOGIN_TIMEOUT_S = 300
RELOGIN_HINT = "Rode: python -m spotify_assistant login"

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class AuthRequest:
    url: str
    verifier: str
    state: str


def start_authorization(settings: Settings) -> AuthRequest:
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    state = secrets.token_urlsafe(16)
    query = urllib.parse.urlencode({
        "client_id": settings.client_id,
        "response_type": "code",
        "redirect_uri": settings.redirect_uri,
        "code_challenge_method": "S256",
        "code_challenge": challenge,
        "scope": SCOPES,
        "state": state,
    })
    return AuthRequest(f"{AUTHORIZE_URL}?{query}", verifier, state)


def finish_authorization(settings: Settings, request: AuthRequest, params: dict[str, str]) -> None:
    if params.get("state") != request.state:
        raise SystemExit("Resposta de login inválida (state não confere). Tente de novo.")
    if "error" in params:
        raise SystemExit(f"Login recusado pelo Spotify: {params['error']}")
    token = http_request("POST", TOKEN_URL, form={
        "grant_type": "authorization_code",
        "code": params["code"],
        "redirect_uri": settings.redirect_uri,
        "client_id": settings.client_id,
        "code_verifier": request.verifier,
    })
    _save(token)


def login(settings: Settings) -> None:
    request = start_authorization(settings)
    finish_authorization(settings, request, _wait_for_callback(settings.redirect_uri, request.url))


def missing_scopes() -> set[str]:
    """Permissões que o token salvo ainda não tem (ex.: controle do player)."""
    try:
        granted = json.loads(TOKEN_FILE.read_text(encoding="utf-8")).get("scope", "")
    except FileNotFoundError:
        granted = ""
    return set(SCOPES.split()) - set(granted.split())


def _wait_for_callback(redirect_uri: str, authorize_url: str) -> dict[str, str]:
    target = urllib.parse.urlsplit(redirect_uri)
    received: dict[str, str] = {}

    class CallbackHandler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            url = urllib.parse.urlsplit(self.path)
            if url.path != target.path:
                self.send_error(404)
                return
            received.update(urllib.parse.parse_qsl(url.query))
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write("<h2>Pronto! Pode fechar esta aba e voltar ao terminal.</h2>".encode())

        def log_message(self, *args) -> None:
            pass

    with http.server.HTTPServer((target.hostname, target.port or 80), CallbackHandler) as server:
        server.timeout = 5
        log.info("Abrindo o navegador para autorizar. Se não abrir, acesse:\n%s", authorize_url)
        webbrowser.open(authorize_url)
        deadline = time.monotonic() + LOGIN_TIMEOUT_S
        while not received:
            if time.monotonic() > deadline:
                raise SystemExit("Tempo esgotado esperando a autorização no navegador.")
            server.handle_request()
    return received


class TokenManager:
    """Entrega um access token válido, renovando com o refresh token quando expira."""

    def __init__(self, settings: Settings):
        self._settings = settings
        self._token = _load()
        # O painel faz requisições em paralelo; o refresh token gira a cada uso,
        # então só uma thread pode renovar por vez.
        self._lock = threading.Lock()

    def __call__(self) -> str:
        with self._lock:
            if self._token["expires_at"] - 60 < time.time():
                self._refresh()
            return self._token["access_token"]

    def _refresh(self) -> None:
        try:
            fresh = http_request("POST", TOKEN_URL, form={
                "grant_type": "refresh_token",
                "refresh_token": self._token["refresh_token"],
                "client_id": self._settings.client_id,
            })
        except SpotifyError as err:
            if err.status in (400, 401):
                raise SystemExit(f"A sessão do Spotify expirou ({err}). {RELOGIN_HINT}") from None
            raise
        # Com PKCE o Spotify costuma girar o refresh token; guarda sempre o mais novo.
        fresh.setdefault("refresh_token", self._token["refresh_token"])
        self._token = _save(fresh)


def _save(token: dict) -> dict:
    record = {
        "access_token": token["access_token"],
        "refresh_token": token["refresh_token"],
        "expires_at": time.time() + token["expires_in"],
        "scope": token.get("scope", ""),
    }
    TOKEN_FILE.parent.mkdir(exist_ok=True)
    TOKEN_FILE.write_text(json.dumps(record, indent=2), encoding="utf-8")
    return record


def _load() -> dict:
    try:
        return json.loads(TOKEN_FILE.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise SystemExit(f"Você ainda não fez login. {RELOGIN_HINT}") from None
