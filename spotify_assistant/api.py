"""Cliente mínimo da Spotify Web API (só biblioteca padrão).

Segue as regras do Development Mode de fev/2026: criação via POST /me/playlists,
itens em /playlists/{id}/items e busca limitada a 10 resultados.
"""
from __future__ import annotations

import json
import logging
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable, Iterator

from . import config

API_BASE = "https://api.spotify.com/v1"
MAX_ATTEMPTS = 5
MAX_RETRY_WAIT_S = 120
SEARCH_LIMIT = 10
ITEMS_PER_REQUEST = 100
# Freio global: no máximo ~4 pedidos por segundo para a Spotify, somando tudo (player, buscas...).
MIN_INTERVAL_S = 0.25

log = logging.getLogger(__name__)


class SpotifyError(RuntimeError):
    def __init__(self, status: int, message: str, retry_after: int | None = None, family: str = ""):
        super().__init__(f"HTTP {status}: {message}")
        self.status = status
        self.retry_after = retry_after  # segundos até a Spotify aceitar de novo (429)
        self.family = family  # tipo de pedido pausado: "search", "me/player"...


def endpoint_family(url_or_path: str) -> str:
    """'/search?q=x' -> 'search'; '/me/player/next' -> 'me/player'; '/albums/1/tracks' -> 'albums'."""
    path = urllib.parse.urlsplit(url_or_path).path
    parts = [part for part in path.split("/") if part and part != "v1"]
    if not parts:
        return ""
    return "/".join(parts[:2]) if parts[0] == "me" and len(parts) > 1 else parts[0]


class _Gate:
    """Espaça os pedidos e lembra as pausas que a Spotify impôs (sobrevive a reinícios)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._next_slot = 0.0
        self._paused: dict[str, float] | None = None  # família -> horário (epoch) em que volta

    def _load(self) -> dict[str, float]:
        if self._paused is None:
            try:
                self._paused = json.loads(config.SPOTIFY_PAUSES_FILE.read_text(encoding="utf-8"))
            except (FileNotFoundError, ValueError):
                self._paused = {}
        return self._paused

    def remaining(self, family: str) -> int:
        with self._lock:
            until = self._load().get(family, 0)
        return max(0, int(until - time.time()))

    def pause(self, family: str, seconds: int) -> None:
        with self._lock:
            paused = self._load()
            paused[family] = time.time() + seconds
            paused = {key: value for key, value in paused.items() if value > time.time()}
            self._paused = paused
            config.DATA_DIR.mkdir(exist_ok=True)
            config.SPOTIFY_PAUSES_FILE.write_text(json.dumps(paused), encoding="utf-8")
        log.warning("Spotify pausou '%s' por %ss", family, seconds)

    def wait_turn(self) -> None:
        with self._lock:
            now = time.monotonic()
            slot = max(now, self._next_slot)
            self._next_slot = slot + MIN_INTERVAL_S
        if slot > now:
            time.sleep(slot - now)


gate = _Gate()


def http_request(
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    params: dict[str, Any] | None = None,
    form: dict[str, str] | None = None,
    json_body: Any = None,
) -> Any:
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"
    headers = dict(headers or {})
    data = None
    if form is not None:
        data = urllib.parse.urlencode(form).encode()
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    elif json_body is not None:
        data = json.dumps(json_body).encode()
        headers["Content-Type"] = "application/json"
    elif method in ("POST", "PUT", "DELETE"):
        data = b""  # o Spotify recusa POST/PUT sem Content-Length (411)

    for attempt in range(1, MAX_ATTEMPTS + 1):
        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                raw = response.read()
            if not raw.strip():
                return None
            try:
                return json.loads(raw)
            except ValueError:
                # Comandos do player (próxima, anterior...) às vezes respondem 200 com texto solto.
                log.debug("Resposta não-JSON de %s %s: %r", method, url, raw[:80])
                return None
        except urllib.error.HTTPError as err:
            body = err.read().decode(errors="replace")
            if (err.code == 429 or err.code >= 500) and attempt < MAX_ATTEMPTS:
                wait = int(err.headers.get("Retry-After") or 2**attempt)
                if wait > MAX_RETRY_WAIT_S:
                    raise SpotifyError(
                        err.code, f"limite de requisições; tente de novo em {wait}s",
                        retry_after=wait, family=endpoint_family(url),
                    ) from None
                log.warning("Spotify respondeu %s; nova tentativa em %ss", err.code, wait)
                time.sleep(wait)
                continue
            raise SpotifyError(err.code, _error_message(body)) from None
        except urllib.error.URLError as err:
            if attempt < MAX_ATTEMPTS:
                time.sleep(2**attempt)
                continue
            raise SpotifyError(0, f"sem conexão: {err.reason}") from None


def _error_message(body: str) -> str:
    try:
        payload = json.loads(body)
    except ValueError:
        return body[:200] or "sem detalhes"
    error = payload.get("error")
    if isinstance(error, dict):
        return error.get("message") or str(error)
    return payload.get("error_description") or str(error or payload)


class Spotify:
    def __init__(self, access_token: Callable[[], str], market: str):
        self._access_token = access_token
        self.market = market

    def _call(self, method: str, path: str, *, params: dict | None = None, body: Any = None) -> Any:
        url = path if path.startswith("https://") else API_BASE + path
        family = endpoint_family(url)
        # Pausado pela Spotify: nem tenta, para não esticar o castigo.
        remaining = gate.remaining(family)
        if remaining:
            raise SpotifyError(429, "pausado pela Spotify", retry_after=remaining, family=family)
        gate.wait_turn()
        headers = {"Authorization": f"Bearer {self._access_token()}"}
        try:
            return http_request(method, url, headers=headers, params=params, json_body=body)
        except SpotifyError as err:
            if err.status == 429 and err.retry_after:
                gate.pause(family, err.retry_after)
            raise

    def me(self) -> dict:
        return self._call("GET", "/me")

    def search(self, query: str, kind: str, offset: int = 0) -> list[dict]:
        params = {"q": query, "type": kind, "limit": SEARCH_LIMIT, "market": self.market}
        if offset:
            params["offset"] = offset
        data = self._call("GET", "/search", params=params)
        return [item for item in data[f"{kind}s"]["items"] if item]

    def album_tracks(self, album_id: str) -> list[dict]:
        data = self._call("GET", f"/albums/{album_id}/tracks", params={"limit": 50, "market": self.market})
        return [track for track in data["items"] if track]

    def my_playlists(self) -> Iterator[dict]:
        page = self._call("GET", "/me/playlists", params={"limit": 50})
        while page:
            yield from (playlist for playlist in page["items"] if playlist)
            page = self._call("GET", page["next"]) if page.get("next") else None

    def create_playlist(self, name: str, description: str, public: bool) -> dict:
        body = {"name": name, "description": description, "public": public}
        return self._call("POST", "/me/playlists", body=body)

    def update_details(self, playlist_id: str, **fields: Any) -> None:
        self._call("PUT", f"/playlists/{playlist_id}", body=fields)

    def replace_items(self, playlist_id: str, uris: list[str]) -> None:
        chunks = [uris[i : i + ITEMS_PER_REQUEST] for i in range(0, len(uris), ITEMS_PER_REQUEST)] or [[]]
        self._call("PUT", f"/playlists/{playlist_id}/items", body={"uris": chunks[0]})
        for chunk in chunks[1:]:
            self._call("POST", f"/playlists/{playlist_id}/items", body={"uris": chunk})

    def show_episodes(self, show_id: str, limit: int = 10) -> list[dict]:
        params = {"limit": limit, "market": self.market}
        data = self._call("GET", f"/shows/{show_id}/episodes", params=params)
        return [episode for episode in data["items"] if episode]

    def playlist_items(self, playlist_id: str) -> list[dict]:
        """Faixas/episódios da playlist (o objeto vem em 'item'; 'track' é o nome antigo)."""
        # Sem additional_types=episode, episódios vêm "disfarçados" de faixa, sem programa nem data.
        params = {"limit": 50, "market": self.market, "additional_types": "episode"}
        page = self._call("GET", f"/playlists/{playlist_id}/items", params=params)
        items = []
        while page:
            for entry in page["items"]:
                item = entry and (entry.get("item") or entry.get("track"))
                if item:
                    items.append(item)
            page = self._call("GET", page["next"]) if page.get("next") else None
        return items

    def add_items(self, playlist_id: str, uris: list[str]) -> None:
        self._call("POST", f"/playlists/{playlist_id}/items", body={"uris": uris})

    # Player: exige Premium e uma sessão do Spotify aberta (PC, celular...).

    def playback(self) -> dict | None:
        return self._call("GET", "/me/player", params={"additional_types": "episode"})

    def devices(self) -> list[dict]:
        return self._call("GET", "/me/player/devices")["devices"]

    def play(
        self,
        *,
        context_uri: str | None = None,
        uris: list[str] | None = None,
        offset_uri: str | None = None,
        device_id: str | None = None,
    ) -> None:
        body: dict[str, Any] = {}
        if context_uri:
            body["context_uri"] = context_uri
        elif uris:
            body["uris"] = uris[:ITEMS_PER_REQUEST]
        if offset_uri:
            body["offset"] = {"uri": offset_uri}
        params = {"device_id": device_id} if device_id else None
        self._call("PUT", "/me/player/play", params=params, body=body)

    def pause(self) -> None:
        self._call("PUT", "/me/player/pause")

    def skip(self, direction: str) -> None:
        self._call("POST", f"/me/player/{direction}")

    def seek(self, position_ms: int) -> None:
        self._call("PUT", "/me/player/seek", params={"position_ms": position_ms})

    def set_volume(self, percent: int) -> None:
        self._call("PUT", "/me/player/volume", params={"volume_percent": max(0, min(100, percent))})

    def set_shuffle(self, enabled: bool) -> None:
        self._call("PUT", "/me/player/shuffle", params={"state": "true" if enabled else "false"})
