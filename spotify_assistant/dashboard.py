"""Painel da Sala de escuta: python -m spotify_assistant ui

Servidor só com a biblioteca padrão. Roda no PC do dono em 127.0.0.1; os amigos
entram pelo endereço público do túnel (SALA_PUBLIC_URL no .env). Cada pessoa entra
com o próprio Spotify e tem player, buscas, playlists e bloqueados separados.
"""
from __future__ import annotations

import html
import http.cookies
import http.server
import json
import logging
import random
import re
import subprocess
import threading
import time
import urllib.parse
import webbrowser
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from . import accounts, config, curation, discovery, tempo
from .api import Spotify, SpotifyError, gate
from .auth import AuthRequest, TokenManager, exchange_code, missing_scopes, start_authorization
from .config import (
    Settings, load_blocked, load_playlists, load_sensations, load_state, save_blocked, save_playlists, save_state,
)
from .deezer import Deezer, DeezerError
from .discovery import Hunt
from .playlists import ensure_playlist, owned_playlists, run
from .views import item_row, pick_image

STATIC_DIR = Path(__file__).resolve().parent / "static"
CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".svg": "image/svg+xml",
}
PLAYLIST_PATH = re.compile(r"/api/playlists/(?P<name>[^/]+)(?P<items>/items)?")
FINDS_PLAYLIST = {
    "name": "Achados da Sala",
    "description": "Músicas descobertas na Sala de escuta: roleta, toca do coelho e sensações.",
    "public": False,
}
TASK_NAME = "Spotify Assistant - Tech Radar BR"  # mesmo nome do scripts/agendar-semanal.ps1
SCHEDULE_TTL_S = 60
MAX_BODY_BYTES = 64_000
COOKIE_NAME = "sala"
LIBRARY_SHELF_SIZE = 12  # playlists da própria conta que um amigo vê na estante
LIBRARY_KEY = re.compile(r"id:(?P<id>[A-Za-z0-9]{1,64})")
PENDING_LOGIN_TTL_S = 15 * 60

log = logging.getLogger(__name__)


class UserError(Exception):
    """Erro com mensagem pronta para mostrar no painel."""

    def __init__(self, message: str, status: int = 400, login: bool = False):
        super().__init__(message)
        self.status = status
        self.login = login


@dataclass
class Job:
    label: str
    dry_run: bool
    status: str = "running"
    lines: list[str] = field(default_factory=list)

    def snapshot(self) -> dict:
        return {"label": self.label, "dry_run": self.dry_run, "status": self.status, "lines": list(self.lines)}


class JobLogHandler(logging.Handler):
    """Leva para o painel só o log da thread da atualização (cada pessoa vê o seu)."""

    def __init__(self, job: Job):
        super().__init__()
        self.job = job
        self.thread = threading.get_ident()

    def emit(self, record: logging.LogRecord) -> None:
        if record.thread != self.thread:
            return
        for line in record.getMessage().splitlines():
            if line.strip():
                self.job.lines.append(line.rstrip())


@dataclass
class Profile:
    """Tudo o que é de uma pessoa enquanto o painel está aberto."""

    id: str
    paths: config.UserPaths
    tokens: TokenManager
    blocked: set[str]
    hunt: Hunt | None = None
    job: Job | None = None
    seeds: list[str] = field(default_factory=list)
    lock: threading.Lock = field(default_factory=threading.Lock)

    @property
    def is_owner(self) -> bool:
        return config.owner_id() == self.id


def playlist_kind(spec: dict) -> str:
    return "podcasts" if "podcasts" in spec else "mix" if "mix" in spec else "music"


def find_spec(config_data: dict, name: str) -> dict:
    for spec in config_data["playlists"]:
        if spec["name"] == name:
            return spec
    raise UserError(f"{name} não está no playlists.json.", 404)


def add_to_config(config_data: dict, playlist_name: str, entry: str) -> dict:
    """Acrescenta a faixa ("Artista - Título") ou o programa à seleção e devolve o spec."""
    spec = find_spec(config_data, playlist_name)
    kind = playlist_kind(spec)
    if kind == "mix":
        raise UserError(f"{playlist_name} é montada com faixas das outras playlists. Adicione em uma delas.")
    entries = spec["podcasts"]["shows"] if kind == "podcasts" else spec.setdefault("tracks", [])
    if entry in entries:
        raise UserError(f"{entry} já está em {playlist_name}.", 409)
    entries.append(entry)
    return spec


NEWS_PERIODS = (7, 14, 30, 90)
GENRE_MAX_CHARS = 40


def fan_range(body: dict) -> discovery.FanRange:
    """Tamanho do artista pedido no painel ("min_fans"/"max_fans"; vazio = sem limite)."""

    def number(key: str) -> int | None:
        raw = body.get(key)
        if raw in (None, ""):
            return None
        try:
            value = int(raw)
        except (TypeError, ValueError):
            raise UserError("Número de fãs inválido.") from None
        if value < 0:
            raise UserError("Número de fãs inválido.")
        return value

    low, high = number("min_fans") or 0, number("max_fans")
    if high is not None and high < low:
        raise UserError("O máximo de fãs precisa ser maior que o mínimo.")
    return discovery.FanRange(low, high)


def genre_from(body: dict, required: bool = False) -> str | None:
    genre = " ".join(str(body.get("genre") or "").split())[:GENRE_MAX_CHARS]
    if not genre:
        if required:
            raise UserError("Escolha um gênero para ver as novidades.")
        return None
    if discovery.is_religious(genre):
        raise UserError("Gêneros religiosos ficam fora da sala.")
    return genre


def pause_message(err: SpotifyError) -> str:
    """'A Spotify pausou as buscas deste app ... voltam por volta de 11:20 de amanhã.'"""
    what = "as buscas" if err.family == "search" else "esse tipo de pedido"
    if not err.retry_after:
        return f"A Spotify pausou {what} deste app por excesso de pedidos. Tente de novo daqui a pouco."
    back = datetime.now() + timedelta(seconds=err.retry_after)
    days = (back.date() - date.today()).days
    day = "hoje" if days == 0 else "amanhã" if days == 1 else f"em {back:%d/%m}"
    return f"A Spotify pausou {what} deste app por excesso de pedidos. Voltam por volta de {back:%H:%M} {day}."


def spotify_message(err: SpotifyError) -> str:
    if err.status == 429:
        return pause_message(err)
    text = str(err)
    if err.status == 404 and "device" in text.lower():
        return "Nenhum Spotify ativo. Toque uma playlist daqui ou abra o app no PC ou no celular."
    if err.status == 403 and "premium" in text.lower():
        return "O controle do player exige Spotify Premium."
    return f"O Spotify recusou o pedido ({text})."


class App:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.sessions = accounts.Sessions()
        self.deezer = Deezer()
        self._profiles: dict[str, Profile] = {}
        self._profiles_lock = threading.Lock()
        self._pending: dict[str, AuthRequest] = {}
        self._schedule: tuple[float, dict | None] = (float("-inf"), None)

    # Pessoas e login

    def profile(self, user_id: str) -> Profile:
        with self._profiles_lock:
            profile = self._profiles.get(user_id)
            if profile is None:
                paths = config.user_paths(user_id)
                try:
                    tokens = TokenManager(self.settings, paths.token)
                except SystemExit as exc:
                    raise UserError(str(exc.code), 401, login=True) from None
                # O conjunto de bloqueados é compartilhado com as buscas da pessoa: bloquear vale na hora.
                profile = Profile(user_id, paths, tokens, discovery.blocked_set(load_blocked(paths.blocked)))
                self._profiles[user_id] = profile
            return profile

    def forget(self, user_id: str) -> None:
        with self._profiles_lock:
            self._profiles.pop(user_id, None)

    def spotify(self, user: Profile) -> Spotify:
        return Spotify(user.tokens, market=load_playlists().get("market", "BR"))

    def login_url(self, redirect_uri: str) -> str:
        now = time.time()
        self._pending = {state: req for state, req in self._pending.items() if now - req.created < PENDING_LOGIN_TTL_S}
        request = start_authorization(self.settings, redirect_uri)
        self._pending[request.state] = request
        return request.url

    def finish_login(self, params: dict[str, str]) -> accounts.Person:
        request = self._pending.pop(params.get("state", ""), None)
        if request is None:
            raise UserError("O pedido de login expirou. Tente de novo.")
        token = exchange_code(self.settings, request, params)
        person = accounts.register(token, load_playlists().get("market", "BR"))
        self.forget(person.id)  # carrega o token novo na próxima requisição
        return person

    # Leitura

    def overview(self, user: Profile) -> dict:
        sp = self.spotify(user)
        library = list(sp.my_playlists())
        # A estante curada (playlists.json) é só do dono; cada amigo vê as playlists da própria conta.
        playlists = self._curated_shelf(user, library) if user.is_owner else self._library_shelf(user, library)
        return {
            "me": {"id": user.id, "name": accounts.display_name(user.id), "is_owner": user.is_owner},
            "playlists": playlists,
            "player_ready": not missing_scopes(user.paths.token),
            "search_paused_s": gate.remaining("search"),
            "schedule": self.schedule() if user.is_owner else None,
        }

    @staticmethod
    def _library_shelf(user: Profile, library: list[dict]) -> list[dict]:
        mine = [playlist for playlist in library if (playlist.get("owner") or {}).get("id") == user.id]
        return [
            {
                "key": f"id:{playlist['id']}",
                "name": playlist["name"],
                "kind": "library",
                "description": html.unescape(playlist.get("description") or ""),
                "color": None,
                "uri": playlist["uri"],
                "image": pick_image(playlist.get("images"), 300),
                "total": (playlist.get("items") or playlist.get("tracks") or {}).get("total", 0),
            }
            for playlist in mine[:LIBRARY_SHELF_SIZE]
        ]

    @staticmethod
    def _curated_shelf(user: Profile, library: list[dict]) -> list[dict]:
        owned = {playlist["id"]: playlist for playlist in library}
        ids = load_state(user.paths.state).get("playlists", {})
        playlists = []
        for spec in load_playlists()["playlists"]:
            remote = owned.get(ids.get(spec["name"]))
            summary = {
                "key": spec["name"],
                "name": spec["name"],
                "kind": playlist_kind(spec),
                "description": spec.get("description", ""),
                "color": spec.get("color"),
                "uri": None,
                "image": None,
                "total": 0,
            }
            if "mix" in spec:
                summary["sources"] = spec["mix"]["from"]
            if remote:
                summary.update(
                    uri=remote["uri"],
                    image=pick_image(remote.get("images"), 300),
                    total=(remote.get("items") or remote.get("tracks") or {}).get("total", 0),
                )
            playlists.append(summary)
        return playlists

    @staticmethod
    def _require_owner(user: Profile) -> None:
        """A estante curada e a seleção base são do dono: amigos nem veem."""
        if not user.is_owner:
            raise UserError("Playlist não encontrada.", 404)

    def playlist(self, user: Profile, name: str) -> dict:
        if match := LIBRARY_KEY.fullmatch(name):
            playlist_id = match["id"]
        else:
            self._require_owner(user)
            find_spec(load_playlists(), name)
            playlist_id = load_state(user.paths.state).get("playlists", {}).get(name)
        items: list[dict] = []
        if playlist_id:
            try:
                items = self.spotify(user).playlist_items(playlist_id)
            except SpotifyError as err:
                if err.status != 404:
                    raise
        return {"name": name, "items": [item_row(item) for item in items]}

    def search(self, user: Profile, query: str, kind: str) -> dict:
        if kind not in ("track", "show"):
            raise UserError("Tipo de busca inválido.")
        if not query.strip():
            return {"results": []}
        results = []
        for item in self.spotify(user).search(query, kind):
            if kind == "track":
                row = item_row(item)
                row["entry"] = f"{item['artists'][0]['name']} - {item['name']}"
            else:
                description = (item.get("description") or "").strip()
                row = {
                    "uri": item["uri"],
                    "type": "show",
                    "title": item["name"],
                    "subtitle": description[:110] + ("…" if len(description) > 110 else ""),
                    "image": pick_image(item.get("images"), 64),
                    "entry": item["name"],
                }
            results.append(row)
        return {"results": results}

    def schedule(self) -> dict | None:
        cached_at, value = self._schedule
        if time.monotonic() - cached_at > SCHEDULE_TTL_S:
            value = read_schedule()
            self._schedule = (time.monotonic(), value)
        return value

    # Player

    def player(self, user: Profile) -> dict:
        if missing_scopes(user.paths.token):
            return {"needs_scope": True}
        data = self.spotify(user).playback()
        if not data or not data.get("item"):
            return {"item": None}
        device = data.get("device") or {}
        return {
            "item": item_row(data["item"], image_size=120),
            "is_playing": data.get("is_playing", False),
            "progress_ms": data.get("progress_ms") or 0,
            "shuffle": data.get("shuffle_state", False),
            "context_uri": (data.get("context") or {}).get("uri"),
            "device": {"name": device.get("name"), "volume": device.get("volume_percent")},
        }

    def player_action(self, user: Profile, body: dict) -> dict:
        if missing_scopes(user.paths.token):
            raise UserError("Autorize o controle do player primeiro.", 403)
        sp = self.spotify(user)
        action, value = body.get("action"), body.get("value")
        if action == "play":
            uris = [uri for uri in body.get("uris") or [] if isinstance(uri, str) and uri.startswith("spotify:")]
            self._play(sp, body.get("context_uri"), uris, body.get("offset_uri"))
        elif action == "pause":
            sp.pause()
        elif action in ("next", "previous"):
            sp.skip(action)
        elif action == "seek":
            sp.seek(int(value))
        elif action == "volume":
            sp.set_volume(int(value))
        elif action == "shuffle":
            sp.set_shuffle(bool(value))
        else:
            raise UserError(f"Ação desconhecida: {action}")
        return {"ok": True}

    @staticmethod
    def _play(sp: Spotify, context_uri: str | None, uris: list[str], offset_uri: str | None) -> None:
        try:
            sp.play(context_uri=context_uri, uris=uris, offset_uri=offset_uri)
        except SpotifyError as err:
            if err.status != 404:
                raise
            # Nenhum dispositivo ativo: acorda o Spotify aberto (de preferência o do PC).
            devices = sp.devices()
            if not devices:
                raise UserError("Nenhum Spotify aberto. Abra o app no PC ou no celular e tente de novo.", 409) from None
            device = next((d for d in devices if d.get("type") == "Computer"), devices[0])
            sp.play(context_uri=context_uri, uris=uris, offset_uri=offset_uri, device_id=device["id"])

    # Sensações e Descobrir

    def sensations(self) -> dict:
        return {"sensations": load_sensations(), "tempo_ready": tempo.available()}

    def start_hunt(self, user: Profile, body: dict) -> dict:
        # Toda descoberta termina localizando músicas na busca da Spotify: se ela está pausada, avisa já.
        paused = gate.remaining("search")
        if paused:
            raise UserError(pause_message(SpotifyError(429, "pausado", retry_after=paused, family="search")), 429)
        kind = body.get("kind")
        sp = self.spotify(user)
        rng = random.Random()
        if kind == "sense":
            text = " ".join((body.get("text") or "").split())
            if len(text) > 60:
                raise UserError("Escreva algo mais curto, até 60 letras.")
            if text:
                spec = discovery.spec_from_text(text)
            else:
                spec = next((s for s in load_sensations() if s["name"] == body.get("name")), None)
                if spec is None:
                    raise UserError("Sensação não encontrada no sensacoes.json.", 404)
            if not tempo.available():
                raise UserError("Para medir o BPM, instale o decodificador: pip install miniaudio", 409)
            hunt = Hunt("sense", spec["name"], color=spec.get("color"), spec=spec)
            cache = discovery.TempoCache()

            def task() -> None:
                try:
                    discovery.sense(hunt, spec, sp, self.deezer, rng, cache, blocked=user.blocked)
                finally:
                    cache.save()
        elif kind == "roulette":
            genre, size = genre_from(body), fan_range(body)
            hunt = Hunt("roulette", f"Roleta: {genre}" if genre else "Roleta")

            def task() -> None:
                discovery.roulette(hunt, sp, self.deezer, rng, blocked=user.blocked, genre=genre, size=size)
        elif kind == "rabbit":
            seed = (body.get("seed") or "").strip()
            size = fan_range(body)
            hunt = Hunt("rabbit", "Toca do coelho")

            def task() -> None:
                seeds = [seed] if seed else self._seed_artists(user, sp)
                discovery.rabbit_hole(hunt, sp, self.deezer, rng, seeds, blocked=user.blocked, size=size)
        elif kind == "news":
            genre, size = genre_from(body, required=True), fan_range(body)
            try:
                days = int(body.get("days") or 30)
            except (TypeError, ValueError):
                days = 0
            if days not in NEWS_PERIODS:
                raise UserError("Período inválido.")
            hunt = Hunt("news", f"Novidades: {genre}")

            def task() -> None:
                discovery.news(hunt, sp, self.deezer, genre, size, days, blocked=user.blocked)
        else:
            raise UserError("Tipo de descoberta inválido.")

        with user.lock:
            if user.hunt:
                user.hunt.cancelled = True  # a busca anterior para no próximo passo
            user.hunt = hunt
        threading.Thread(target=self._run_hunt, args=(hunt, task), daemon=True).start()
        return hunt.snapshot()

    @staticmethod
    def current_hunt(user: Profile) -> dict | None:
        return user.hunt.snapshot() if user.hunt else None

    @staticmethod
    def _run_hunt(hunt: Hunt, task) -> None:
        try:
            task()
            hunt.status = "cancelled" if hunt.cancelled else "done"
        except (SpotifyError, DeezerError) as err:
            hunt.status = "error"
            hunt.message = (
                spotify_message(err) if isinstance(err, SpotifyError)
                else f"A busca de músicas novas falhou ({err}). Tente de novo."
            )
        except UserError as err:
            hunt.status = "error"
            hunt.message = str(err)
        except SystemExit as exc:
            hunt.status = "error"
            hunt.message = str(exc.code)
        except Exception:
            log.exception("Falha na descoberta")
            hunt.status = "error"
            hunt.message = "Erro inesperado. Detalhes em data/assistant.log."
        finally:
            discovery.matches.save()

    @staticmethod
    def _seed_artists(user: Profile, sp: Spotify) -> list[str]:
        """Artistas das playlists da própria pessoa: ponto de partida da toca do coelho."""
        if not user.seeds:
            if user.is_owner:
                ids = load_state(user.paths.state).get("playlists", {})
                sources = [ids[spec["name"]] for spec in load_playlists()["playlists"]
                           if playlist_kind(spec) == "music" and ids.get(spec["name"])]
            else:
                sources = [p["id"] for p in sp.my_playlists() if (p.get("owner") or {}).get("id") == user.id][:4]
            names: dict[str, None] = {}
            for playlist_id in sources:
                for item in sp.playlist_items(playlist_id):
                    for artist in item.get("artists", [])[:1]:
                        if artist["name"] != "Various Artists":
                            names[artist["name"]] = None
            user.seeds = list(names)
        if not user.seeds:
            raise UserError("Digite um artista para começar a descer a toca.")
        return user.seeds

    def save_hunt(self, user: Profile) -> dict:
        hunt = user.hunt
        if not hunt or hunt.kind != "sense" or not hunt.finds:
            raise UserError("Gere uma sensação antes de salvar.")
        spec = hunt.spec or {}
        rhythm = (
            f"Entre {spec['bpm'][0]} e {spec['bpm'][1]} BPM, medidos pela Sala de escuta."
            if spec.get("bpm") else "Ritmo aprendido pela Sala de escuta com playlists sobre isso."
        )
        playlist = {
            "name": f"Sensação: {hunt.label}",
            "description": f"{spec.get('description', '')} {rhythm}".strip(),
            "public": False,
        }
        sp = self.spotify(user)
        state = load_state(user.paths.state)
        playlist_id = ensure_playlist(sp, playlist, state, owned_playlists(sp))
        sp.replace_items(playlist_id, [find.uri for find in hunt.finds])
        return {"message": f"Salva como {playlist['name']}.", "uri": f"spotify:playlist:{playlist_id}"}

    @staticmethod
    def blocked_artists(user: Profile) -> dict:
        return {"artists": load_blocked(user.paths.blocked)}

    def set_blocked(self, user: Profile, body: dict) -> dict:
        artist = " ".join(str(body.get("artist") or "").split())
        if not artist:
            raise UserError("Diga qual artista.")
        names = load_blocked(user.paths.blocked)
        key = curation.normalize(artist)
        if body.get("blocked", True):
            if key not in discovery.blocked_set(names):
                names.append(artist)
            user.blocked.add(key)
            self._drop_artist_from_hunt(user, key)
            message = f"{artist} não aparece mais nas suas descobertas."
        else:
            names = [name for name in names if curation.normalize(name) != key]
            user.blocked.discard(key)
            message = f"{artist} pode aparecer de novo."
        save_blocked(names, user.paths.blocked)
        return {"message": message, "artists": load_blocked(user.paths.blocked)}

    @staticmethod
    def _drop_artist_from_hunt(user: Profile, key: str) -> None:
        """Tira o artista recém-bloqueado do resultado que está na tela."""
        hunt = user.hunt
        if not hunt:
            return

        def keep(find) -> bool:
            return all(curation.normalize(name) != key for name in find.artists)

        hunt.finds = [find for find in hunt.finds if keep(find)]
        for chain in hunt.chains:
            chain["finds"] = [find for find in chain["finds"] if keep(find)]
        hunt.chains = [chain for chain in hunt.chains if chain["finds"]]

    def keep_finds(self, user: Profile, body: dict) -> dict:
        uris = [uri for uri in body.get("uris") or [] if isinstance(uri, str) and uri.startswith("spotify:track:")]
        if not uris:
            raise UserError("Nada para guardar.")
        sp = self.spotify(user)
        state = load_state(user.paths.state)
        playlist_id = ensure_playlist(sp, FINDS_PLAYLIST, state, owned_playlists(sp))
        existing = {item["uri"] for item in sp.playlist_items(playlist_id)}
        fresh = [uri for uri in dict.fromkeys(uris) if uri not in existing]
        if fresh:
            sp.add_items(playlist_id, fresh)
        name = FINDS_PLAYLIST["name"]
        if not fresh:
            message = f"Já estava nos {name}."
        elif len(fresh) == 1:
            message = f"Guardada nos {name}."
        else:
            message = f"{len(fresh)} músicas guardadas nos {name}."
        return {"message": message}

    # Edição

    def add_item(self, user: Profile, name: str, body: dict) -> dict:
        entry, uri = body.get("entry", "").strip(), body.get("uri", "")
        if not entry or not uri.startswith("spotify:"):
            raise UserError("Escolha um item da busca.")
        if match := LIBRARY_KEY.fullmatch(name):
            # Playlist da própria conta: só vai para o Spotify (a Spotify recusa se não for da pessoa).
            try:
                self.spotify(user).add_items(match["id"], [uri])
            except SpotifyError as err:
                if err.status in (403, 404):
                    raise UserError("Você só pode adicionar em playlists que são suas.", 403) from None
                raise
            return {"message": "Adicionada."}
        self._require_owner(user)
        config_data = load_playlists()
        spec = find_spec(config_data, name)
        state = load_state(user.paths.state)
        playlist_id = state.get("playlists", {}).get(name)
        add_to_config(config_data, name, entry)
        if playlist_kind(spec) == "podcasts":
            state.setdefault("shows", {})[entry] = uri.rsplit(":", 1)[-1]
            message = f"{entry} entra na {name} a partir da próxima atualização."
        else:
            if playlist_id:
                self.spotify(user).add_items(playlist_id, [uri])
            message = f"Adicionada a {name}."
        save_playlists(config_data)
        save_state(state)
        return {"message": message}

    def start_job(self, user: Profile, body: dict) -> dict:
        self._require_owner(user)
        name = body.get("playlist", "")
        find_spec(load_playlists(), name)
        dry_run = bool(body.get("dry_run"))
        sp = self.spotify(user)
        with user.lock:
            if user.job and user.job.status == "running":
                raise UserError("Já tem uma atualização sua em andamento.", 409)
            user.job = job = Job(f"{'Prévia de' if dry_run else 'Atualizando'} {name}", dry_run)
        threading.Thread(target=self._run_job, args=(job, sp, user, name), daemon=True).start()
        return job.snapshot()

    @staticmethod
    def current_job(user: Profile) -> dict | None:
        return user.job.snapshot() if user.job else None

    @staticmethod
    def _run_job(job: Job, sp: Spotify, user: Profile, name: str) -> None:
        handler = JobLogHandler(job)
        logger = logging.getLogger("spotify_assistant")
        logger.addHandler(handler)
        try:
            run(sp, load_playlists(), load_state(user.paths.state), only=[name], dry_run=job.dry_run)
            job.status = "done"
        except SystemExit as exc:
            job.lines.append(str(exc.code))
            job.status = "error"
        except SpotifyError as err:
            job.lines.append(spotify_message(err))
            job.status = "error"
        except Exception:
            log.exception("Falha na atualização")
            job.status = "error"
        finally:
            logger.removeHandler(handler)


def read_schedule() -> dict | None:
    """Próxima/última execução da tarefa semanal no Agendador do Windows."""
    script = (
        f"$i = Get-ScheduledTaskInfo -TaskName '{TASK_NAME}' -ErrorAction Stop; "
        "@{ next = if ($i.NextRunTime) { $i.NextRunTime.ToString('s') } else { $null }; "
        "last = if ($i.LastRunTime) { $i.LastRunTime.ToString('s') } else { $null }; "
        "result = $i.LastTaskResult } | ConvertTo-Json -Compress"
    )
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True,
            text=True,
            timeout=20,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return {"scheduled": False}
    data = json.loads(result.stdout)
    # 0 = sucesso; 0x41301 = rodando agora; 0x41303 = ainda não rodou
    ok = data["result"] in (0, 0x41301, 0x41303)
    return {"scheduled": True, "next": data["next"], "last": data["last"], "ok": ok}


class Handler(http.server.BaseHTTPRequestHandler):
    server: DashboardServer

    def do_GET(self) -> None:
        self._handle("GET")

    def do_POST(self) -> None:
        self._handle("POST")

    def log_message(self, *args) -> None:
        pass

    # Quem está pedindo

    def _cookie(self) -> str | None:
        jar = http.cookies.SimpleCookie()
        try:
            jar.load(self.headers.get("Cookie", ""))
        except http.cookies.CookieError:
            return None
        morsel = jar.get(COOKIE_NAME)
        return morsel.value if morsel else None

    def _user(self) -> Profile:
        user_id = self.server.app.sessions.user(self._cookie())
        if not user_id:
            raise UserError("Entre com o seu Spotify para continuar.", 401, login=True)
        return self.server.app.profile(user_id)

    def _host(self) -> str:
        """Endereço que o navegador usou. Túneis às vezes reescrevem o Host e mandam o original aqui."""
        forwarded = self.headers.get("X-Forwarded-Host", "").split(",")[0].strip()
        return forwarded or self.headers.get("Host", "")

    def _is_public(self) -> bool:
        return bool(self.server.public_host) and self._host() == self.server.public_host

    def _is_https(self) -> bool:
        return self.headers.get("X-Forwarded-Proto") == "https" or self._is_public()

    def _redirect_uri(self) -> str:
        settings = self.server.app.settings
        return f"{settings.public_url}/callback" if self._is_public() else settings.redirect_uri

    def _session_cookie(self, value: str, max_age: int) -> str:
        cookie = f"{COOKIE_NAME}={value}; Path=/; Max-Age={max_age}; HttpOnly; SameSite=Lax"
        return cookie + "; Secure" if self._is_https() else cookie

    # Despacho

    def _handle(self, method: str) -> None:
        # Bloqueia DNS rebinding e pedidos de outros sites.
        if self._host() not in self.server.allowed_hosts:
            self._send_json({"error": "Host não permitido."}, 403)
            return
        url = urllib.parse.urlsplit(self.path)
        if method == "GET" and not url.path.startswith("/api/"):
            self._serve_page(url)
            return
        # JSON obrigatório: outro site não consegue mandar isso sem a permissão (CORS) que nunca damos.
        if method == "POST" and self.headers.get("Content-Type", "").split(";")[0].strip() != "application/json":
            self._send_json({"error": "Envie JSON."}, 415)
            return
        try:
            body = self._read_json() if method == "POST" else {}
            query = dict(urllib.parse.parse_qsl(url.query))
            if method == "POST" and url.path == "/api/logout":
                self._logout()
                return
            self._send_json(self._route(method, url.path, query, body))
        except UserError as err:
            self._send_json({"error": str(err), "login": err.login}, err.status)
        except SpotifyError as err:
            self._send_json({"error": spotify_message(err)}, 502)
        except DeezerError as err:
            self._send_json({"error": f"A busca de músicas novas falhou ({err}). Tente de novo."}, 502)
        except SystemExit as exc:  # o Spotify da pessoa não aceita mais o token: entrar de novo
            user_id = self.server.app.sessions.user(self._cookie())
            if user_id:
                self.server.app.forget(user_id)
            self.server.app.sessions.end(self._cookie())
            self._send_json({"error": str(exc.code), "login": True}, 401)
        except Exception:
            log.exception("Erro no painel")
            self._send_json({"error": "Erro inesperado. Detalhes em data/assistant.log."}, 500)

    def _route(self, method: str, path: str, query: dict[str, str], body: dict) -> Any:
        app = self.server.app
        if method == "GET" and path == "/api/sensations":
            return app.sensations()
        user = self._user()
        if method == "GET" and path == "/api/overview":
            return app.overview(user)
        if method == "GET" and path == "/api/player":
            return app.player(user)
        if method == "POST" and path == "/api/player":
            return app.player_action(user, body)
        if method == "GET" and path == "/api/search":
            return app.search(user, query.get("q", ""), query.get("kind", "track"))
        if method == "POST" and path == "/api/jobs":
            return app.start_job(user, body)
        if method == "GET" and path == "/api/jobs/current":
            return app.current_job(user)
        if method == "POST" and path == "/api/hunts":
            return app.start_hunt(user, body)
        if method == "GET" and path == "/api/hunts/current":
            return app.current_hunt(user)
        if method == "POST" and path == "/api/hunts/save":
            return app.save_hunt(user)
        if method == "GET" and path == "/api/blocked":
            return app.blocked_artists(user)
        if method == "POST" and path == "/api/blocked":
            return app.set_blocked(user, body)
        if method == "POST" and path == "/api/finds/keep":
            return app.keep_finds(user, body)
        if match := PLAYLIST_PATH.fullmatch(path):
            name = urllib.parse.unquote(match["name"])
            if method == "GET" and not match["items"]:
                return app.playlist(user, name)
            if method == "POST" and match["items"]:
                return app.add_item(user, name, body)
        raise UserError("Endereço não encontrado.", 404)

    def _logout(self) -> None:
        self.server.app.sessions.end(self._cookie())
        self._send_json({"ok": True}, headers={"Set-Cookie": self._session_cookie("", 0)})

    def _serve_page(self, url: urllib.parse.SplitResult) -> None:
        app = self.server.app
        if url.path == "/login":
            self._redirect(app.login_url(self._redirect_uri()))
            return
        if url.path == "/callback":
            self._finish_login(dict(urllib.parse.parse_qsl(url.query)))
            return
        file = (STATIC_DIR / ("index.html" if url.path == "/" else url.path.lstrip("/"))).resolve()
        if file.parent != STATIC_DIR or file.suffix not in CONTENT_TYPES or not file.is_file():
            self._send_text("Não encontrado.", 404)
            return
        self._send(200, CONTENT_TYPES[file.suffix], file.read_bytes())

    def _finish_login(self, params: dict[str, str]) -> None:
        app = self.server.app
        try:
            person = app.finish_login(params)
        except accounts.NotInvited:
            owner = config.owner_id()
            who = accounts.display_name(owner) if owner else "o dono da sala"
            self._send_message_page(
                "Sua conta ainda não foi liberada",
                f"A Spotify só deixa entrar quem foi convidado. Peça para {who} adicionar o e-mail da sua conta "
                "do Spotify em User Management, no Spotify for Developers. Depois é só entrar de novo.",
                403,
            )
            return
        except SystemExit as exc:
            self._send_message_page("Não deu para entrar", str(exc.code), 400)
            return
        except (UserError, SpotifyError) as err:
            self._send_message_page("Não deu para entrar", str(err), 400)
            return
        token = app.sessions.create(person.id)
        self._redirect("/", headers={"Set-Cookie": self._session_cookie(token, accounts.SESSION_DAYS * 86400)})

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY_BYTES:
            raise UserError("Pedido grande demais.", 413)
        data = json.loads(self.rfile.read(length) or b"{}")
        if not isinstance(data, dict):
            raise UserError("JSON inválido.")
        return data

    def _redirect(self, location: str, headers: dict[str, str] | None = None) -> None:
        self.send_response(302)
        self.send_header("Location", location)
        self.send_header("Content-Length", "0")
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()

    def _send_message_page(self, title: str, message: str, status: int) -> None:
        page = (
            '<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width, initial-scale=1">'
            f"<title>{html.escape(title)}</title><link rel=\"stylesheet\" href=\"/app.css\"></head>"
            f'<body><section class="gate"><h1 class="gate-title">{html.escape(title)}</h1>'
            f'<p class="gate-text">{html.escape(message)}</p>'
            '<a class="play-button" href="/">Voltar para a sala</a></section></body></html>'
        )
        self._send(status, CONTENT_TYPES[".html"], page.encode())

    def _send_json(self, payload: Any, status: int = 200, headers: dict[str, str] | None = None) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode()
        self._send(status, "application/json; charset=utf-8", body, headers)

    def _send_text(self, text: str, status: int) -> None:
        self._send(status, "text/plain; charset=utf-8", text.encode())

    def _send(self, status: int, content_type: str, body: bytes, headers: dict[str, str] | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)


class DashboardServer(http.server.ThreadingHTTPServer):
    daemon_threads = True
    # No Windows, SO_REUSEADDR deixaria dois painéis ouvindo a mesma porta.
    allow_reuse_address = False

    def __init__(self, address: tuple[str, int], app: App):
        super().__init__(address, Handler)
        self.app = app
        port = self.server_address[1]
        self.public_host = urllib.parse.urlsplit(app.settings.public_url).netloc
        self.allowed_hosts = {f"127.0.0.1:{port}", f"localhost:{port}"} | ({self.public_host} - {""})


def serve(settings: Settings, open_browser: bool = True) -> None:
    accounts.migrate_legacy(settings)
    target = urllib.parse.urlsplit(settings.redirect_uri)
    host, port = target.hostname or "127.0.0.1", target.port or 8888
    url = f"http://{host}:{port}/"
    app = App(settings)
    try:
        server = DashboardServer((host, port), app)
    except OSError:
        log.info("A porta %s já está em uso; o painel provavelmente já está aberto em %s", port, url)
        if open_browser:
            webbrowser.open(url)
        return
    threading.Thread(target=app.schedule, daemon=True).start()  # o PowerShell leva ~1s; já deixa pronto
    log.info("Painel aberto em %s  (Ctrl+C ou feche esta janela para encerrar)", url)
    if settings.public_url:
        log.info("Endereço para os amigos: %s", settings.public_url)
    if open_browser:
        webbrowser.open(url)
    with server:
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            log.info("Painel encerrado.")
