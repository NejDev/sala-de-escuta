"""Cliente mínimo da API pública do Deezer (sem chave).

Usado só para descoberta: playlists montadas por pessoas para cada momento,
artistas relacionados com número de fãs e prévias de 30 s para medir o BPM.
As faixas encontradas são levadas para o Spotify pelo ISRC.
"""
from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import deque

from .curation import normalize

API_BASE = "https://api.deezer.com"
# Limite do Deezer: 50 requisições a cada 5 s por IP. Ficamos um pouco abaixo.
WINDOW_S = 5.0
MAX_PER_WINDOW = 40
QUOTA_ERROR_CODE = 4


class DeezerError(RuntimeError):
    pass


class Deezer:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._sent: deque[float] = deque()

    def _throttle(self) -> None:
        with self._lock:
            while True:
                now = time.monotonic()
                while self._sent and now - self._sent[0] > WINDOW_S:
                    self._sent.popleft()
                if len(self._sent) < MAX_PER_WINDOW:
                    self._sent.append(now)
                    return
                time.sleep(WINDOW_S - (now - self._sent[0]) + 0.05)

    def get(self, path: str, **params) -> dict:
        url = f"{API_BASE}{path}"
        if params:
            url = f"{url}?{urllib.parse.urlencode(params)}"
        for attempt in range(3):
            self._throttle()
            try:
                with urllib.request.urlopen(url, timeout=20) as response:
                    data = json.loads(response.read())
            except (urllib.error.URLError, TimeoutError) as err:
                if attempt == 2:
                    raise DeezerError(f"sem conexão com o Deezer: {err}") from None
                time.sleep(1 + attempt)
                continue
            error = data.get("error") if isinstance(data, dict) else None
            if not error:
                return data
            if error.get("code") == QUOTA_ERROR_CODE and attempt < 2:
                time.sleep(WINDOW_S)
                continue
            raise DeezerError(error.get("message", "erro do Deezer"))
        raise DeezerError("o Deezer não respondeu")

    def search_playlists(self, query: str, limit: int = 8) -> list[dict]:
        return self.get("/search/playlist", q=query, limit=limit).get("data", [])

    def playlist_tracks(self, playlist_id: int, limit: int = 100) -> list[dict]:
        return self.get(f"/playlist/{playlist_id}/tracks", limit=limit).get("data", [])

    def search_tracks(self, query: str, limit: int = 50) -> list[dict]:
        return self.get("/search", q=query, limit=limit).get("data", [])

    def search_artist(self, name: str) -> dict | None:
        """O perfil com mais fãs entre os de mesmo nome (o Deezer tem muitos perfis duplicados)."""
        found = self.get("/search/artist", q=name, limit=10).get("data", [])
        wanted = normalize(name)
        same_name = [artist for artist in found if normalize(artist["name"]) == wanted]
        return max(same_name or found[:1], key=lambda artist: artist.get("nb_fan", 0), default=None)

    def artist(self, artist_id: int) -> dict:
        """Artista completo (inclui nb_fan, o número de fãs)."""
        return self.get(f"/artist/{artist_id}")

    def artist_albums(self, artist_id: int, limit: int = 25) -> list[dict]:
        """Discos do artista com release_date e record_type (single, ep, album). Sem ordem garantida."""
        return self.get(f"/artist/{artist_id}/albums", limit=limit).get("data", [])

    def album_tracks(self, album_id: int) -> list[dict]:
        return self.get(f"/album/{album_id}/tracks", limit=50).get("data", [])

    def related(self, artist_id: int, limit: int = 20) -> list[dict]:
        return self.get(f"/artist/{artist_id}/related", limit=limit).get("data", [])

    def top_tracks(self, artist_id: int, limit: int = 5) -> list[dict]:
        return self.get(f"/artist/{artist_id}/top", limit=limit).get("data", [])

    def track(self, track_id: int) -> dict:
        return self.get(f"/track/{track_id}")

    @staticmethod
    def preview(url: str) -> bytes:
        """Prévias vêm da CDN, fora do limite da API."""
        with urllib.request.urlopen(url, timeout=20) as response:
            return response.read()
