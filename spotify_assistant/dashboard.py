"""Painel visual local: python -m spotify_assistant ui

Servidor só com a biblioteca padrão, em 127.0.0.1 e na mesma porta do redirect
do OAuth, então o login acontece dentro do próprio painel.
"""
from __future__ import annotations

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
from pathlib import Path
from typing import Any

from . import discovery, tempo
from .api import Spotify, SpotifyError
from .auth import AuthRequest, TokenManager, finish_authorization, missing_scopes, start_authorization
from .config import Settings, load_playlists, load_sensations, load_state, save_playlists, save_state
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
    def __init__(self, job: Job):
        super().__init__()
        self.job = job

    def emit(self, record: logging.LogRecord) -> None:
        for line in record.getMessage().splitlines():
            if line.strip():
                self.job.lines.append(line.rstrip())


def playlist_kind(spec: dict) -> str:
    return "podcasts" if "podcasts" in spec else "mix" if "mix" in spec else "music"


def find_spec(config: dict, name: str) -> dict:
    for spec in config["playlists"]:
        if spec["name"] == name:
            return spec
    raise UserError(f"{name} não está no playlists.json.", 404)


def add_to_config(config: dict, playlist_name: str, entry: str) -> dict:
    """Acrescenta a faixa ("Artista - Título") ou o programa à seleção e devolve o spec."""
    spec = find_spec(config, playlist_name)
    kind = playlist_kind(spec)
    if kind == "mix":
        raise UserError(f"{playlist_name} é montada com faixas das outras playlists. Adicione em uma delas.")
    entries = spec["podcasts"]["shows"] if kind == "podcasts" else spec.setdefault("tracks", [])
    if entry in entries:
        raise UserError(f"{entry} já está em {playlist_name}.", 409)
    entries.append(entry)
    return spec


def spotify_message(err: SpotifyError) -> str:
    text = str(err)
    if err.status == 404 and "device" in text.lower():
        return "Nenhum Spotify ativo. Toque uma playlist daqui ou abra o app no PC ou no celular."
    if err.status == 403 and "premium" in text.lower():
        return "O controle do player exige Spotify Premium."
    return f"O Spotify recusou o pedido ({text})."


class App:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._tokens: TokenManager | None = None
        self._pending_auth: AuthRequest | None = None
        self._job: Job | None = None
        self._job_lock = threading.Lock()
        self._schedule: tuple[float, dict | None] = (float("-inf"), None)
        self._hunt: Hunt | None = None
        self._hunt_lock = threading.Lock()
        self._seeds: list[str] = []
        self.deezer = Deezer()

    # Sessão

    def spotify(self) -> Spotify:
        if self._tokens is None:
            try:
                self._tokens = TokenManager(self.settings)
            except SystemExit as exc:
                raise UserError(str(exc.code), 401, login=True) from None
        return Spotify(self._tokens, market=load_playlists().get("market", "BR"))

    def reset_session(self) -> None:
        self._tokens = None

    def login_url(self) -> str:
        self._pending_auth = start_authorization(self.settings)
        return self._pending_auth.url

    def finish_login(self, params: dict[str, str]) -> None:
        if self._pending_auth is None:
            raise UserError("O pedido de login expirou. Tente de novo.")
        finish_authorization(self.settings, self._pending_auth, params)
        self._pending_auth = None
        self._tokens = None

    # Leitura

    def overview(self) -> dict:
        sp = self.spotify()
        me = sp.me()
        owned = {playlist["id"]: playlist for playlist in sp.my_playlists()}
        ids = load_state().get("playlists", {})
        playlists = []
        for spec in load_playlists()["playlists"]:
            remote = owned.get(ids.get(spec["name"]))
            summary = {
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
        return {
            "user": me.get("display_name") or me["id"],
            "playlists": playlists,
            "player_ready": not missing_scopes(),
            "schedule": self.schedule(),
        }

    def playlist(self, name: str) -> dict:
        find_spec(load_playlists(), name)
        playlist_id = load_state().get("playlists", {}).get(name)
        items: list[dict] = []
        if playlist_id:
            try:
                items = self.spotify().playlist_items(playlist_id)
            except SpotifyError as err:
                if err.status != 404:
                    raise
        return {"name": name, "items": [item_row(item) for item in items]}

    def search(self, query: str, kind: str) -> dict:
        if kind not in ("track", "show"):
            raise UserError("Tipo de busca inválido.")
        if not query.strip():
            return {"results": []}
        results = []
        for item in self.spotify().search(query, kind):
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

    def player(self) -> dict:
        if missing_scopes():
            return {"needs_scope": True}
        data = self.spotify().playback()
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

    def player_action(self, body: dict) -> dict:
        if missing_scopes():
            raise UserError("Autorize o controle do player primeiro.", 403)
        sp = self.spotify()
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

    def start_hunt(self, body: dict) -> dict:
        kind = body.get("kind")
        sp = self.spotify()
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
                    discovery.sense(hunt, spec, sp, self.deezer, rng, cache)
                finally:
                    cache.save()
        elif kind == "roulette":
            hunt = Hunt("roulette", "Roleta")

            def task() -> None:
                discovery.roulette(hunt, sp, self.deezer, rng)
        elif kind == "rabbit":
            seed = (body.get("seed") or "").strip()
            hunt = Hunt("rabbit", "Toca do coelho")

            def task() -> None:
                seeds = [seed] if seed else self._seed_artists(sp)
                discovery.rabbit_hole(hunt, sp, self.deezer, rng, seeds)
        else:
            raise UserError("Tipo de descoberta inválido.")

        with self._hunt_lock:
            if self._hunt:
                self._hunt.cancelled = True  # a busca anterior para no próximo passo
            self._hunt = hunt
        threading.Thread(target=self._run_hunt, args=(hunt, task), daemon=True).start()
        return hunt.snapshot()

    def current_hunt(self) -> dict | None:
        return self._hunt.snapshot() if self._hunt else None

    def _run_hunt(self, hunt: Hunt, task) -> None:
        try:
            task()
            hunt.status = "cancelled" if hunt.cancelled else "done"
        except (SpotifyError, DeezerError) as err:
            hunt.status = "error"
            hunt.message = spotify_message(err) if isinstance(err, SpotifyError) else f"A busca de músicas novas falhou ({err}). Tente de novo."
        except SystemExit as exc:
            hunt.status = "error"
            hunt.message = str(exc.code)
        except Exception:
            log.exception("Falha na descoberta")
            hunt.status = "error"
            hunt.message = "Erro inesperado. Detalhes em data/assistant.log."

    def _seed_artists(self, sp: Spotify) -> list[str]:
        """Artistas das suas playlists de música: ponto de partida da toca do coelho."""
        if not self._seeds:
            ids = load_state().get("playlists", {})
            names: dict[str, None] = {}
            for spec in load_playlists()["playlists"]:
                if playlist_kind(spec) == "music" and ids.get(spec["name"]):
                    for item in sp.playlist_items(ids[spec["name"]]):
                        for artist in item.get("artists", [])[:1]:
                            if artist["name"] != "Various Artists":
                                names[artist["name"]] = None
            self._seeds = list(names)
        if not self._seeds:
            raise UserError("Crie suas playlists primeiro ou digite um artista para começar.")
        return self._seeds

    def save_hunt(self) -> dict:
        hunt = self._hunt
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
        sp = self.spotify()
        state = load_state()
        playlist_id = ensure_playlist(sp, playlist, state, owned_playlists(sp))
        sp.replace_items(playlist_id, [find.uri for find in hunt.finds])
        return {"message": f"Salva como {playlist['name']}.", "uri": f"spotify:playlist:{playlist_id}"}

    def keep_finds(self, body: dict) -> dict:
        uris = [uri for uri in body.get("uris") or [] if isinstance(uri, str) and uri.startswith("spotify:track:")]
        if not uris:
            raise UserError("Nada para guardar.")
        sp = self.spotify()
        state = load_state()
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

    def add_item(self, name: str, body: dict) -> dict:
        entry, uri = body.get("entry", "").strip(), body.get("uri", "")
        if not entry or not uri.startswith("spotify:"):
            raise UserError("Escolha um item da busca.")
        config = load_playlists()
        spec = add_to_config(config, name, entry)
        state = load_state()
        if playlist_kind(spec) == "podcasts":
            state.setdefault("shows", {})[entry] = uri.rsplit(":", 1)[-1]
            message = f"{entry} entra na {name} a partir da próxima atualização."
        else:
            playlist_id = state.get("playlists", {}).get(name)
            if playlist_id:
                self.spotify().add_items(playlist_id, [uri])
            message = f"Adicionada a {name}."
        save_playlists(config)
        save_state(state)
        return {"message": message}

    def start_job(self, body: dict) -> dict:
        name = body.get("playlist", "")
        find_spec(load_playlists(), name)
        dry_run = bool(body.get("dry_run"))
        sp = self.spotify()
        with self._job_lock:
            if self._job and self._job.status == "running":
                raise UserError("Já tem uma atualização em andamento.", 409)
            self._job = job = Job(f"{'Prévia de' if dry_run else 'Atualizando'} {name}", dry_run)
        threading.Thread(target=self._run_job, args=(job, sp, name), daemon=True).start()
        return job.snapshot()

    def current_job(self) -> dict | None:
        return self._job.snapshot() if self._job else None

    def _run_job(self, job: Job, sp: Spotify, name: str) -> None:
        handler = JobLogHandler(job)
        logger = logging.getLogger("spotify_assistant")
        logger.addHandler(handler)
        try:
            run(sp, load_playlists(), load_state(), only=[name], dry_run=job.dry_run)
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

    def _handle(self, method: str) -> None:
        # Bloqueia DNS rebinding e pedidos de outros sites para a API local.
        if self.headers.get("Host") not in self.server.allowed_hosts:
            self._send_json({"error": "Host não permitido."}, 403)
            return
        url = urllib.parse.urlsplit(self.path)
        if method == "GET" and not url.path.startswith("/api/"):
            self._serve_page(url)
            return
        if method == "POST" and self.headers.get("Content-Type", "").split(";")[0].strip() != "application/json":
            self._send_json({"error": "Envie JSON."}, 415)
            return
        try:
            body = self._read_json() if method == "POST" else {}
            query = dict(urllib.parse.parse_qsl(url.query))
            self._send_json(self._route(method, url.path, query, body))
        except UserError as err:
            self._send_json({"error": str(err), "login": err.login}, err.status)
        except SpotifyError as err:
            self._send_json({"error": spotify_message(err)}, 502)
        except DeezerError as err:
            self._send_json({"error": f"A busca de músicas novas falhou ({err}). Tente de novo."}, 502)
        except SystemExit as exc:  # sessão expirou durante a renovação do token
            self.server.app.reset_session()
            self._send_json({"error": str(exc.code), "login": True}, 401)
        except Exception:
            log.exception("Erro no painel")
            self._send_json({"error": "Erro inesperado. Detalhes em data/assistant.log."}, 500)

    def _route(self, method: str, path: str, query: dict[str, str], body: dict) -> Any:
        app = self.server.app
        if method == "GET" and path == "/api/overview":
            return app.overview()
        if method == "GET" and path == "/api/player":
            return app.player()
        if method == "POST" and path == "/api/player":
            return app.player_action(body)
        if method == "GET" and path == "/api/search":
            return app.search(query.get("q", ""), query.get("kind", "track"))
        if method == "POST" and path == "/api/jobs":
            return app.start_job(body)
        if method == "GET" and path == "/api/jobs/current":
            return app.current_job()
        if method == "GET" and path == "/api/sensations":
            return app.sensations()
        if method == "POST" and path == "/api/hunts":
            return app.start_hunt(body)
        if method == "GET" and path == "/api/hunts/current":
            return app.current_hunt()
        if method == "POST" and path == "/api/hunts/save":
            return app.save_hunt()
        if method == "POST" and path == "/api/finds/keep":
            return app.keep_finds(body)
        if match := PLAYLIST_PATH.fullmatch(path):
            name = urllib.parse.unquote(match["name"])
            if method == "GET" and not match["items"]:
                return app.playlist(name)
            if method == "POST" and match["items"]:
                return app.add_item(name, body)
        raise UserError("Endereço não encontrado.", 404)

    def _serve_page(self, url: urllib.parse.SplitResult) -> None:
        app = self.server.app
        if url.path == "/login":
            self._redirect(app.login_url())
            return
        if url.path == "/callback":
            try:
                app.finish_login(dict(urllib.parse.parse_qsl(url.query)))
            except SystemExit as exc:
                self._send_text(f"{exc.code} Volte para http://{self.headers['Host']}/", 400)
                return
            except (UserError, SpotifyError) as err:
                self._send_text(f"Não foi possível conectar: {err} Volte para http://{self.headers['Host']}/", 400)
                return
            self._redirect("/")
            return
        file = (STATIC_DIR / ("index.html" if url.path == "/" else url.path.lstrip("/"))).resolve()
        if file.parent != STATIC_DIR or file.suffix not in CONTENT_TYPES or not file.is_file():
            self._send_text("Não encontrado.", 404)
            return
        self._send(200, CONTENT_TYPES[file.suffix], file.read_bytes())

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY_BYTES:
            raise UserError("Pedido grande demais.", 413)
        data = json.loads(self.rfile.read(length) or b"{}")
        if not isinstance(data, dict):
            raise UserError("JSON inválido.")
        return data

    def _redirect(self, location: str) -> None:
        self.send_response(302)
        self.send_header("Location", location)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _send_json(self, payload: Any, status: int = 200) -> None:
        self._send(status, "application/json; charset=utf-8", json.dumps(payload, ensure_ascii=False).encode())

    def _send_text(self, text: str, status: int) -> None:
        self._send(status, "text/plain; charset=utf-8", text.encode())

    def _send(self, status: int, content_type: str, body: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
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
        self.allowed_hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}


def serve(settings: Settings, open_browser: bool = True) -> None:
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
    if open_browser:
        webbrowser.open(url)
    with server:
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            log.info("Painel encerrado.")
