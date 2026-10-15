"""OAuth login (Authorization Code + PKCE) and automatic token refresh.

With PKCE the Client Secret isn't needed: only the Client ID goes in .env.
Each person in the room has their own token file (data/users/<id>/token.json).
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
from pathlib import Path

from .api import SpotifyError, http_request
from .config import TOKEN_FILE, Settings
from .i18n import t

AUTHORIZE_URL = "https://accounts.spotify.com/authorize"
TOKEN_URL = "https://accounts.spotify.com/api/token"
PLAYER_SCOPES = "user-read-playback-state user-modify-playback-state user-read-currently-playing"
LIBRARY_SCOPES = "user-library-read user-library-modify"  # the heart: Liked Songs and saved episodes
SOCIAL_SCOPES = "user-read-recently-played"  # Friends: what each person listened to (only if they join)
TASTE_SCOPES = "user-top-read"  # Friends: most played artists, for the affinity (optional)
SCOPES = (
    f"playlist-read-private playlist-modify-private playlist-modify-public "
    f"{PLAYER_SCOPES} {LIBRARY_SCOPES} {SOCIAL_SCOPES} {TASTE_SCOPES}"
)
LOGIN_TIMEOUT_S = 300

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class AuthRequest:
    url: str
    verifier: str
    state: str
    redirect_uri: str
    created: float = 0.0


def start_authorization(settings: Settings, redirect_uri: str | None = None) -> AuthRequest:
    redirect_uri = redirect_uri or settings.redirect_uri
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    state = secrets.token_urlsafe(16)
    query = urllib.parse.urlencode({
        "client_id": settings.client_id,
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "code_challenge_method": "S256",
        "code_challenge": challenge,
        "scope": SCOPES,
        "state": state,
        "show_dialog": "true",  # allows switching accounts (useful when friends use the same PC)
    })
    return AuthRequest(f"{AUTHORIZE_URL}?{query}", verifier, state, redirect_uri, time.time())


def exchange_code(settings: Settings, request: AuthRequest, params: dict[str, str]) -> dict:
    """Exchanges the code returned by the login for a token (not saved yet)."""
    if params.get("state") != request.state:
        raise SystemExit(t("auth.bad_state"))
    if "error" in params:
        raise SystemExit(t("auth.refused", error=params["error"]))
    return http_request("POST", TOKEN_URL, form={
        "grant_type": "authorization_code",
        "code": params["code"],
        "redirect_uri": request.redirect_uri,
        "client_id": settings.client_id,
        "code_verifier": request.verifier,
    })


def login(settings: Settings) -> dict:
    """Login from the terminal (opens the browser and waits for the callback on 127.0.0.1)."""
    request = start_authorization(settings)
    return exchange_code(settings, request, _wait_for_callback(settings.redirect_uri, request.url))


def missing_scopes(token_file: Path | None = None, needed: str = SCOPES) -> set[str]:
    """Permissions (out of `needed`) the saved token doesn't have yet, e.g. player control."""
    try:
        granted = json.loads((token_file or TOKEN_FILE).read_text(encoding="utf-8")).get("scope", "")
    except FileNotFoundError:
        granted = ""
    return set(needed.split()) - set(granted.split())


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
            self.wfile.write(f"<h2>{t('auth.done_page')}</h2>".encode())

        def log_message(self, *args) -> None:
            pass

    with http.server.HTTPServer((target.hostname, target.port or 80), CallbackHandler) as server:
        server.timeout = 5
        log.info(t("auth.opening", url=authorize_url))
        webbrowser.open(authorize_url)
        deadline = time.monotonic() + LOGIN_TIMEOUT_S
        while not received:
            if time.monotonic() > deadline:
                raise SystemExit(t("auth.timeout"))
            server.handle_request()
    return received


class TokenManager:
    """Provides a valid access token, renewing it with the refresh token when it expires."""

    def __init__(self, settings: Settings, token_file: Path | None = None):
        self._settings = settings
        self._file = token_file or TOKEN_FILE
        self._token = load_token(self._file)
        # The panel makes requests in parallel; the refresh token rotates on every use,
        # so only one thread may renew it at a time.
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
                raise SystemExit(t("auth.expired")) from None
            raise
        # With PKCE Spotify usually rotates the refresh token; always keep the newest one.
        fresh.setdefault("refresh_token", self._token["refresh_token"])
        self._token = save_token(fresh, self._file)


def save_token(token: dict, path: Path) -> dict:
    record = {
        "access_token": token["access_token"],
        "refresh_token": token["refresh_token"],
        "expires_at": time.time() + token["expires_in"],
        "scope": token.get("scope", ""),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, indent=2), encoding="utf-8")
    return record


def load_token(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise SystemExit(t("auth.not_signed_in")) from None
