"""Sala de escuta panel: python -m spotify_assistant ui

Standard-library-only server. It runs on the owner's PC at 127.0.0.1; friends come
in through the tunnel's public address (SALA_PUBLIC_URL in .env). Each person signs
in with their own Spotify and gets their own player, discoveries, playlists and
blocked artists.
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

from . import accounts, config, curation, discovery, i18n, tempo
from .api import Spotify, SpotifyError, gate
from .auth import AuthRequest, TokenManager, exchange_code, missing_scopes, start_authorization
from .config import (
    Settings, load_blocked, load_playlists, load_sensations, load_state, save_blocked, save_playlists, save_state,
)
from .deezer import Deezer, DeezerError
from .discovery import Hunt
from .i18n import t
from .playlists import owned_playlists, run
from .views import item_row, pick_image

STATIC_DIR = Path(__file__).resolve().parent / "static"
CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".svg": "image/svg+xml",
    ".webp": "image/webp",
    ".png": "image/png",
}
IMAGE_SUFFIXES = {".svg", ".webp", ".png"}  # the mascot never changes: the browser may keep it
PLAYLIST_PATH = re.compile(r"/api/playlists/(?P<name>[^/]+)(?P<items>/items)?")
# The "finds" playlist is stored under a fixed key, so switching languages doesn't create a second one.
FINDS_KEY = "_finds"
FINDS_NAMES = {i18n.MESSAGES[lang]["finds.name"] for lang in i18n.LANGUAGES}
TASK_NAME = "Spotify Assistant - Tech Radar BR"  # same name as in scripts/agendar-semanal.ps1
SCHEDULE_TTL_S = 60
MAX_BODY_BYTES = 64_000
COOKIE_NAME = "sala"
LIBRARY_SHELF_SIZE = 12  # playlists from their own account that a friend sees on the shelf
LIBRARY_KEY = re.compile(r"id:(?P<id>[A-Za-z0-9]{1,64})")
TRACK_URI = re.compile(r"spotify:track:[A-Za-z0-9]{1,64}")
PLAYLIST_NAME_MAX = 100
SAVE_MAX_TRACKS = 500
ITEMS_PER_ADD = 100  # Spotify's limit per request
FEELING_MAX_CHARS = 60
REPEAT_MODES = ("off", "context", "track")
PENDING_LOGIN_TTL_S = 15 * 60

log = logging.getLogger(__name__)


class UserError(Exception):
    """Error whose message is ready to show in the panel."""

    def __init__(self, message: str, status: int = 400, login: bool = False, **extra: Any):
        super().__init__(message)
        self.status = status
        self.login = login
        self.extra = extra  # extra response fields (e.g. exists=True when the name is taken)


@dataclass
class Job:
    label: str
    dry_run: bool
    name: str = ""  # the playlist being updated
    status: str = "running"
    lines: list[str] = field(default_factory=list)

    def snapshot(self) -> dict:
        return {
            "label": self.label, "name": self.name, "dry_run": self.dry_run, "status": self.status,
            "lines": list(self.lines),
        }


class JobLogHandler(logging.Handler):
    """Sends to the panel only the log of the update's own thread (each person sees theirs)."""

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
    """Everything that belongs to one person while the panel is open."""

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
    raise UserError(t("err.not_in_config", name=name), 404)


def add_to_config(config_data: dict, playlist_name: str, entry: str) -> dict:
    """Appends the track ("Artist - Title") or the show to the selection and returns the spec."""
    spec = find_spec(config_data, playlist_name)
    kind = playlist_kind(spec)
    if kind == "mix":
        raise UserError(t("err.mix_add", name=playlist_name))
    entries = spec["podcasts"]["shows"] if kind == "podcasts" else spec.setdefault("tracks", [])
    if entry in entries:
        raise UserError(t("err.already_in", entry=entry, name=playlist_name), 409)
    entries.append(entry)
    return spec


def localized(spec: dict) -> dict:
    """Sensation preset with name and description in the current language."""
    lang = i18n.current()

    def pick(value: Any) -> Any:
        return value.get(lang) or value.get(i18n.DEFAULT) if isinstance(value, dict) else value

    return {**spec, "name": pick(spec.get("name")), "description": pick(spec.get("description", ""))}


NEWS_PERIODS = (7, 14, 30, 90)
GENRE_MAX_CHARS = 40


def fan_range(body: dict) -> discovery.FanRange:
    """Artist size asked for in the panel ("min_fans"/"max_fans"; empty = no limit)."""

    def number(key: str) -> int | None:
        raw = body.get(key)
        if raw in (None, ""):
            return None
        try:
            value = int(raw)
        except (TypeError, ValueError):
            raise UserError(t("err.fans_invalid")) from None
        if value < 0:
            raise UserError(t("err.fans_invalid"))
        return value

    low, high = number("min_fans") or 0, number("max_fans")
    if high is not None and high < low:
        raise UserError(t("err.fans_order"))
    return discovery.FanRange(low, high)


def genre_from(body: dict, required: bool = False) -> str | None:
    genre = " ".join(str(body.get("genre") or "").split())[:GENRE_MAX_CHARS]
    if not genre:
        if required:
            raise UserError(t("err.genre_required"))
        return None
    if discovery.is_religious(genre):
        raise UserError(t("err.genre_religious"))
    return genre


def pause_message(err: SpotifyError) -> str:
    """'Spotify paused this app's searches ... They're back around 11:20 AM tomorrow.'"""
    what = "search" if err.family == "search" else "other"
    if not err.retry_after:
        return t(f"pause.{what}.soon")
    back = datetime.now() + timedelta(seconds=err.retry_after)
    days = (back.date() - date.today()).days
    day = t("day.today") if days == 0 else t("day.tomorrow") if days == 1 else t("day.on", date=i18n.short_date(back))
    return t(f"pause.{what}.until", time=i18n.clock(back), day=day)


def spotify_message(err: SpotifyError) -> str:
    if err.status == 429:
        return pause_message(err)
    text = str(err)
    if err.status == 404 and "device" in text.lower():
        return t("spotify.no_device")
    if err.status == 403 and "premium" in text.lower():
        return t("spotify.premium")
    return t("spotify.refused", text=text)


class App:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.sessions = accounts.Sessions()
        self.deezer = Deezer()
        self._profiles: dict[str, Profile] = {}
        self._profiles_lock = threading.Lock()
        self._pending: dict[str, AuthRequest] = {}
        self._schedule: tuple[float, dict | None] = (float("-inf"), None)

    # People and sign-in

    def profile(self, user_id: str) -> Profile:
        with self._profiles_lock:
            profile = self._profiles.get(user_id)
            if profile is None:
                paths = config.user_paths(user_id)
                try:
                    tokens = TokenManager(self.settings, paths.token)
                except SystemExit as exc:
                    raise UserError(str(exc.code), 401, login=True, expired=True) from None
                # The blocked set is shared with the person's discoveries: blocking takes effect right away.
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
            raise UserError(t("err.login_expired"))
        token = exchange_code(self.settings, request, params)
        person = accounts.register(token, load_playlists().get("market", "BR"))
        self.forget(person.id)  # the new token is loaded on the next request
        return person

    # Reading

    def overview(self, user: Profile) -> dict:
        sp = self.spotify(user)
        library = list(sp.my_playlists())
        # The curated shelf (playlists.json) is the owner's only; each friend sees their own account's playlists.
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
        """The curated shelf and its base selection belong to the owner: friends don't even see them."""
        if not user.is_owner:
            raise UserError(t("err.playlist_not_found"), 404)

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
            raise UserError(t("err.search_kind"))
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
            "repeat": data.get("repeat_state", "off"),
            "context_uri": (data.get("context") or {}).get("uri"),
            "device": {"name": device.get("name"), "volume": device.get("volume_percent")},
        }

    def player_action(self, user: Profile, body: dict) -> dict:
        if missing_scopes(user.paths.token):
            raise UserError(t("err.player_scope"), 403)
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
        elif action == "repeat" and value in REPEAT_MODES:
            sp.set_repeat(value)
        else:
            raise UserError(t("err.unknown_action", action=action))
        return {"ok": True}

    @staticmethod
    def _play(sp: Spotify, context_uri: str | None, uris: list[str], offset_uri: str | None) -> None:
        try:
            sp.play(context_uri=context_uri, uris=uris, offset_uri=offset_uri)
        except SpotifyError as err:
            if err.status != 404:
                raise
            # No active device: wake the open Spotify (preferably the computer's).
            devices = sp.devices()
            if not devices:
                raise UserError(t("err.no_device_open"), 409) from None
            device = next((d for d in devices if d.get("type") == "Computer"), devices[0])
            sp.play(context_uri=context_uri, uris=uris, offset_uri=offset_uri, device_id=device["id"])

    # Sensations and Discover

    @staticmethod
    def sensations() -> dict:
        presets = [
            {key: spec[key] for key in ("id", "name", "description", "color", "bpm")}
            for spec in map(localized, load_sensations())
        ]
        return {"sensations": presets, "tempo_ready": tempo.available()}

    @staticmethod
    def _preset(body: dict) -> dict:
        wanted = body.get("id")
        for spec in load_sensations():
            names = spec["name"].values() if isinstance(spec["name"], dict) else [spec["name"]]
            if (wanted and spec.get("id") == wanted) or (not wanted and body.get("name") in names):
                return localized(spec)
        raise UserError(t("err.sensation_not_found"), 404)

    def start_hunt(self, user: Profile, body: dict) -> dict:
        # Every discovery ends up finding songs through Spotify search: if it's paused, say so now.
        paused = gate.remaining("search")
        if paused:
            raise UserError(pause_message(SpotifyError(429, "paused", retry_after=paused, family="search")), 429)
        kind = body.get("kind")
        sp = self.spotify(user)
        rng = random.Random()
        if kind == "sense":
            text = " ".join((body.get("text") or "").split())
            if len(text) > FEELING_MAX_CHARS:
                raise UserError(t("err.feeling_too_long", max=FEELING_MAX_CHARS))
            spec = discovery.spec_from_text(text) if text else self._preset(body)
            if not tempo.available():
                raise UserError(t("err.tempo_missing"), 409)
            size = fan_range(body)
            hunt = Hunt("sense", spec["name"], color=spec.get("color"), spec=spec)
            cache = discovery.TempoCache()

            def task() -> None:
                try:
                    discovery.sense(hunt, spec, sp, self.deezer, rng, cache, blocked=user.blocked, size=size)
                finally:
                    cache.save()
        elif kind == "roulette":
            genre, size = genre_from(body), fan_range(body)
            hunt = Hunt("roulette", t("label.roulette_genre", genre=genre) if genre else t("label.roulette"))

            def task() -> None:
                discovery.roulette(hunt, sp, self.deezer, rng, blocked=user.blocked, genre=genre, size=size)
        elif kind == "rabbit":
            seed = (body.get("seed") or "").strip()
            size = fan_range(body)
            hunt = Hunt("rabbit", t("label.rabbit"))

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
                raise UserError(t("err.period"))
            hunt = Hunt("news", t("label.news", genre=genre))

            def task() -> None:
                discovery.news(hunt, sp, self.deezer, genre, size, days, blocked=user.blocked)
        else:
            raise UserError(t("err.hunt_kind"))

        with user.lock:
            if user.hunt:
                user.hunt.cancelled = True  # the previous discovery stops at its next step
            user.hunt = hunt
        threading.Thread(target=self._run_hunt, args=(hunt, task, i18n.current()), daemon=True).start()
        return hunt.snapshot()

    @staticmethod
    def current_hunt(user: Profile) -> dict | None:
        return user.hunt.snapshot() if user.hunt else None

    @staticmethod
    def _run_hunt(hunt: Hunt, task, lang: str = i18n.DEFAULT) -> None:
        i18n.use(lang)  # progress messages and reasons come out in the language of whoever started it
        try:
            task()
            hunt.status = "cancelled" if hunt.cancelled else "done"
        except (SpotifyError, DeezerError) as err:
            hunt.status = "error"
            hunt.message = (
                spotify_message(err) if isinstance(err, SpotifyError) else t("err.discovery_failed", error=err)
            )
        except UserError as err:
            hunt.status = "error"
            hunt.message = str(err)
        except SystemExit as exc:
            hunt.status = "error"
            hunt.message = str(exc.code)
        except Exception:
            log.exception("Discovery failed")
            hunt.status = "error"
            hunt.message = t("err.unexpected")
        finally:
            discovery.matches.save()

    @staticmethod
    def _seed_artists(user: Profile, sp: Spotify) -> list[str]:
        """Artists from the person's own playlists: where the rabbit hole starts."""
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
            raise UserError(t("err.rabbit_seed"))
        return user.seeds

    @staticmethod
    def blocked_artists(user: Profile) -> dict:
        return {"artists": load_blocked(user.paths.blocked)}

    def set_blocked(self, user: Profile, body: dict) -> dict:
        artist = " ".join(str(body.get("artist") or "").split())
        if not artist:
            raise UserError(t("err.which_artist"))
        names = load_blocked(user.paths.blocked)
        key = curation.normalize(artist)
        if body.get("blocked", True):
            if key not in discovery.blocked_set(names):
                names.append(artist)
            user.blocked.add(key)
            self._drop_artist_from_hunt(user, key)
            message = t("blocked.on", artist=artist)
        else:
            names = [name for name in names if curation.normalize(name) != key]
            user.blocked.discard(key)
            message = t("blocked.off", artist=artist)
        save_blocked(names, user.paths.blocked)
        return {"message": message, "artists": load_blocked(user.paths.blocked)}

    @staticmethod
    def _drop_artist_from_hunt(user: Profile, key: str) -> None:
        """Removes the artist that was just blocked from the result on screen."""
        hunt = user.hunt
        if not hunt:
            return

        def keep(find) -> bool:
            return all(curation.normalize(name) != key for name in find.artists)

        hunt.finds = [find for find in hunt.finds if keep(find)]
        for chain in hunt.chains:
            chain["finds"] = [find for find in chain["finds"] if keep(find)]
        hunt.chains = [chain for chain in hunt.chains if chain["finds"]]

    # Saving what the person liked

    @staticmethod
    def _owned(user: Profile, sp: Spotify) -> list[dict]:
        return [playlist for playlist in sp.my_playlists() if (playlist.get("owner") or {}).get("id") == user.id]

    @staticmethod
    def _rebuilt_ids(user: Profile) -> dict[str, str]:
        """id -> name of the playlists the Sala rebuilds by itself (owner's curation): edits there get lost."""
        if not user.is_owner:
            return {}
        ids = load_state(user.paths.state).get("playlists", {})
        return {ids[spec["name"]]: spec["name"] for spec in load_playlists()["playlists"]
                if playlist_kind(spec) != "music" and ids.get(spec["name"])}

    @staticmethod
    def _track_uris(body: dict) -> list[str]:
        uris = [uri for uri in body.get("uris") or [] if isinstance(uri, str) and TRACK_URI.fullmatch(uri)]
        uris = list(dict.fromkeys(uris))
        if not uris:
            raise UserError(t("save.none"))
        if len(uris) > SAVE_MAX_TRACKS:
            raise UserError(t("save.too_many", max=SAVE_MAX_TRACKS))
        return uris

    @staticmethod
    def _finds_id(ids: dict[str, str]) -> str | None:
        # Older versions stored it under its Portuguese name.
        return ids.get(FINDS_KEY) or next((ids[name] for name in FINDS_NAMES if name in ids), None)

    def _finds_playlist(self, user: Profile, sp: Spotify) -> tuple[str, str]:
        """(id, current name) of the person's finds playlist, created on first use."""
        state = load_state(user.paths.state)
        ids = state.setdefault("playlists", {})
        owned = owned_playlists(sp)
        playlist_id = self._finds_id(ids)
        if playlist_id not in owned:  # deleted in the app, or first time
            playlist_id = next((pid for pid, name in owned.items() if name in FINDS_NAMES), None)
        if playlist_id is None:
            playlist_id = sp.create_playlist(t("finds.name"), t("finds.description"), False)["id"]
            owned[playlist_id] = t("finds.name")
        for name in FINDS_NAMES:
            ids.pop(name, None)
        ids[FINDS_KEY] = playlist_id
        save_state(state)
        return playlist_id, owned[playlist_id]

    def my_playlists(self, user: Profile) -> dict:
        """The person's playlists where songs can go (the ones the Sala rebuilds are left out)."""
        sp = self.spotify(user)
        skip = set(self._rebuilt_ids(user))
        finds_id = self._finds_id(load_state(user.paths.state).get("playlists", {}))
        return {
            "finds": t("finds.name"),
            "playlists": [
                {
                    "id": playlist["id"],
                    "name": playlist["name"],
                    "image": pick_image(playlist.get("images"), 64),
                    "total": (playlist.get("items") or playlist.get("tracks") or {}).get("total", 0),
                }
                for playlist in self._owned(user, sp)
                if playlist["id"] not in skip and playlist["id"] != finds_id and playlist["name"] not in FINDS_NAMES
            ],
        }

    @staticmethod
    def _description(user: Profile, uris: list[str]) -> str:
        hunt = user.hunt
        if not hunt or not set(uris) <= {find.uri for find in hunt.finds}:
            return t("desc.default")
        if hunt.kind == "sense":
            spec = hunt.spec or {}
            rhythm = (
                t("desc.sense_bpm", low=spec["bpm"][0], high=spec["bpm"][1])
                if spec.get("bpm") else t("desc.sense_learned")
            )
            return f"{spec.get('description', '')} {rhythm}".strip()
        return {
            "roulette": t("desc.roulette"),
            "rabbit": t("desc.rabbit"),
            "news": t("desc.news", label=hunt.label),
        }.get(hunt.kind, t("desc.default"))

    def create_playlist(self, user: Profile, body: dict) -> dict:
        name = " ".join(str(body.get("name") or "").split())
        if not name:
            raise UserError(t("save.name_required"))
        if len(name) > PLAYLIST_NAME_MAX:
            raise UserError(t("save.name_long", max=PLAYLIST_NAME_MAX))
        uris = self._track_uris(body)
        if user.is_owner and any(spec["name"] == name for spec in load_playlists()["playlists"]):
            raise UserError(t("save.curated_name", name=name), 409)
        sp = self.spotify(user)
        same = next((playlist for playlist in self._owned(user, sp) if playlist["name"] == name), None)
        if same:
            # Same name: the songs are only swapped if the person confirms (the old list is gone).
            if not body.get("replace"):
                raise UserError(t("save.exists", name=name), 409, exists=True)
            sp.replace_items(same["id"], uris)
            return {"message": t("save.replaced", name=name, count=len(uris)), "uri": same["uri"], "id": same["id"]}
        created = sp.create_playlist(name, self._description(user, uris), False)
        sp.replace_items(created["id"], uris)
        return {"message": t("save.created", name=name, count=len(uris)), "uri": created["uri"], "id": created["id"]}

    def add_to_playlist(self, user: Profile, body: dict) -> dict:
        uris = self._track_uris(body)
        target = str(body.get("playlist") or "")
        sp = self.spotify(user)
        if target == "finds":
            playlist_id, name = self._finds_playlist(user, sp)
        else:
            playlist = next((p for p in self._owned(user, sp) if p["id"] == target), None)
            if playlist is None:
                raise UserError(t("save.not_yours"), 403)
            if playlist["id"] in self._rebuilt_ids(user):
                raise UserError(t("save.rebuilt", name=playlist["name"]), 409)
            playlist_id, name = playlist["id"], playlist["name"]
        existing = {item["uri"] for item in sp.playlist_items(playlist_id)}
        fresh = [uri for uri in uris if uri not in existing]
        for start in range(0, len(fresh), ITEMS_PER_ADD):
            sp.add_items(playlist_id, fresh[start : start + ITEMS_PER_ADD])
        if fresh:
            self._remember_in_curation(user, playlist_id, fresh)
        return {"message": self._added_message(name, len(uris), len(fresh)), "added": len(fresh)}

    @staticmethod
    def _added_message(name: str, asked: int, added: int) -> str:
        if not added:
            return t("added.already_one", name=name) if asked == 1 else t("added.already_all", name=name)
        if asked == 1:
            return t("added.one", name=name)
        message = t("added.many", count=added, name=name)
        if added < asked:
            message += " " + t("added.some_there", count=asked - added)
        return message

    @staticmethod
    def _remember_in_curation(user: Profile, playlist_id: str, uris: list[str]) -> None:
        """Owner's curated playlist: the song also goes into playlists.json, or it vanishes on the next rebuild."""
        if not user.is_owner:
            return
        ids = load_state(user.paths.state).get("playlists", {})
        name = next((n for n, pid in ids.items() if pid == playlist_id), None)
        config_data = load_playlists()
        spec = next((s for s in config_data["playlists"] if s["name"] == name), None)
        if spec is None or playlist_kind(spec) != "music":
            return
        finds = {find.uri: find for find in (user.hunt.finds if user.hunt else [])}
        entries = spec.setdefault("tracks", [])
        for uri in uris:
            find = finds.get(uri)
            entry = find and find.artists and f"{find.artists[0]} - {find.title}"
            if entry and entry not in entries:
                entries.append(entry)
        save_playlists(config_data)

    # Editing

    def add_item(self, user: Profile, name: str, body: dict) -> dict:
        entry, uri = body.get("entry", "").strip(), body.get("uri", "")
        if not entry or not uri.startswith("spotify:"):
            raise UserError(t("err.pick_result"))
        if match := LIBRARY_KEY.fullmatch(name):
            # A playlist from their own account: it only goes to Spotify (which refuses if it isn't theirs).
            try:
                self.spotify(user).add_items(match["id"], [uri])
            except SpotifyError as err:
                if err.status in (403, 404):
                    raise UserError(t("save.not_yours"), 403) from None
                raise
            return {"message": t("added.plain")}
        self._require_owner(user)
        config_data = load_playlists()
        spec = find_spec(config_data, name)
        state = load_state(user.paths.state)
        playlist_id = state.get("playlists", {}).get(name)
        add_to_config(config_data, name, entry)
        if playlist_kind(spec) == "podcasts":
            state.setdefault("shows", {})[entry] = uri.rsplit(":", 1)[-1]
            message = t("added.show_next", entry=entry, name=name)
        else:
            if playlist_id:
                self.spotify(user).add_items(playlist_id, [uri])
            message = t("added.one", name=name)
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
                raise UserError(t("err.job_running"), 409)
            user.job = job = Job(t("job.preview" if dry_run else "job.update", name=name), dry_run, name)
        threading.Thread(target=self._run_job, args=(job, sp, user, name, i18n.current()), daemon=True).start()
        return job.snapshot()

    @staticmethod
    def current_job(user: Profile) -> dict | None:
        return user.job.snapshot() if user.job else None

    @staticmethod
    def _run_job(job: Job, sp: Spotify, user: Profile, name: str, lang: str = i18n.DEFAULT) -> None:
        i18n.use(lang)
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
            log.exception("Update failed")
            job.status = "error"
        finally:
            logger.removeHandler(handler)


def read_schedule() -> dict | None:
    """Next/last run of the weekly task in the Windows Task Scheduler."""
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
    # 0 = success; 0x41301 = running now; 0x41303 = hasn't run yet
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

    # Who is asking

    def _cookie(self, name: str = COOKIE_NAME) -> str | None:
        jar = http.cookies.SimpleCookie()
        try:
            jar.load(self.headers.get("Cookie", ""))
        except http.cookies.CookieError:
            return None
        morsel = jar.get(name)
        return morsel.value if morsel else None

    def _user(self) -> Profile:
        user_id = self.server.app.sessions.user(self._cookie())
        if not user_id:
            raise UserError(t("err.login_required"), 401, login=True)
        return self.server.app.profile(user_id)

    def _host(self) -> str:
        """Address the browser used. Tunnels sometimes rewrite Host and send the original here."""
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

    # Dispatch

    def _handle(self, method: str) -> None:
        i18n.use(i18n.pick(self._cookie(i18n.COOKIE), self.headers.get("Accept-Language")))
        # Blocks DNS rebinding and requests from other sites.
        if self._host() not in self.server.allowed_hosts:
            self._send_json({"error": t("err.host")}, 403)
            return
        url = urllib.parse.urlsplit(self.path)
        if method == "GET" and not url.path.startswith("/api/"):
            self._serve_page(url)
            return
        # JSON only: another site can't send that without the CORS permission we never grant.
        if method == "POST" and self.headers.get("Content-Type", "").split(";")[0].strip() != "application/json":
            self._send_json({"error": t("err.json_required")}, 415)
            return
        try:
            body = self._read_json() if method == "POST" else {}
            query = dict(urllib.parse.parse_qsl(url.query))
            if method == "POST" and url.path == "/api/logout":
                self._logout()
                return
            self._send_json(self._route(method, url.path, query, body))
        except UserError as err:
            self._send_json({"error": str(err), "login": err.login, **err.extra}, err.status)
        except SpotifyError as err:
            self._send_json({"error": spotify_message(err)}, 502)
        except DeezerError as err:
            self._send_json({"error": t("err.discovery_failed", error=err)}, 502)
        except SystemExit as exc:  # the person's Spotify no longer accepts the token: sign in again
            user_id = self.server.app.sessions.user(self._cookie())
            if user_id:
                self.server.app.forget(user_id)
            self.server.app.sessions.end(self._cookie())
            self._send_json({"error": str(exc.code), "login": True, "expired": True}, 401)
        except Exception:
            log.exception("Panel error")
            self._send_json({"error": t("err.unexpected")}, 500)

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
        if method == "GET" and path == "/api/blocked":
            return app.blocked_artists(user)
        if method == "POST" and path == "/api/blocked":
            return app.set_blocked(user, body)
        if method == "GET" and path == "/api/my-playlists":
            return app.my_playlists(user)
        if method == "POST" and path == "/api/playlists/new":
            return app.create_playlist(user, body)
        if method == "POST" and path == "/api/playlists/add":
            return app.add_to_playlist(user, body)
        if match := PLAYLIST_PATH.fullmatch(path):
            name = urllib.parse.unquote(match["name"])
            if method == "GET" and not match["items"]:
                return app.playlist(user, name)
            if method == "POST" and match["items"]:
                return app.add_item(user, name, body)
        raise UserError(t("err.route"), 404)

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
            self._send_text(t("err.not_found"), 404)
            return
        cache = "public, max-age=604800" if file.suffix in IMAGE_SUFFIXES else "no-store"
        self._send(200, CONTENT_TYPES[file.suffix], file.read_bytes(), cache=cache)

    def _finish_login(self, params: dict[str, str]) -> None:
        app = self.server.app
        try:
            person = app.finish_login(params)
        except accounts.NotInvited:
            owner = config.owner_id()
            who = accounts.display_name(owner) if owner else t("page.owner")
            self._send_message_page(t("page.not_invited.title"), t("page.not_invited.text", who=who), 403)
            return
        except SystemExit as exc:
            self._send_message_page(t("page.login_failed"), str(exc.code), 400)
            return
        except (UserError, SpotifyError) as err:
            self._send_message_page(t("page.login_failed"), str(err), 400)
            return
        token = app.sessions.create(person.id)
        self._redirect("/", headers={"Set-Cookie": self._session_cookie(token, accounts.SESSION_DAYS * 86400)})

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY_BYTES:
            raise UserError(t("err.body_too_big"), 413)
        data = json.loads(self.rfile.read(length) or b"{}")
        if not isinstance(data, dict):
            raise UserError(t("err.json_invalid"))
        return data

    def _redirect(self, location: str, headers: dict[str, str] | None = None) -> None:
        self.send_response(302)
        self.send_header("Location", location)
        self.send_header("Content-Length", "0")
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()

    def _send_message_page(self, title: str, message: str, status: int) -> None:
        lang = "pt-BR" if i18n.current() == "pt" else "en"
        page = (
            f'<!doctype html><html lang="{lang}"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width, initial-scale=1">'
            f"<title>{html.escape(title)}</title><link rel=\"stylesheet\" href=\"/app.css\"></head>"
            f'<body><section class="gate"><h1 class="gate-title">{html.escape(title)}</h1>'
            f'<p class="gate-text">{html.escape(message)}</p>'
            f'<a class="play-button" href="/">{html.escape(t("page.back"))}</a></section></body></html>'
        )
        self._send(status, CONTENT_TYPES[".html"], page.encode())

    def _send_json(self, payload: Any, status: int = 200, headers: dict[str, str] | None = None) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode()
        self._send(status, "application/json; charset=utf-8", body, headers)

    def _send_text(self, text: str, status: int) -> None:
        self._send(status, "text/plain; charset=utf-8", text.encode())

    def _send(
        self, status: int, content_type: str, body: bytes, headers: dict[str, str] | None = None, cache: str = "no-store",
    ) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", cache)
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)


class DashboardServer(http.server.ThreadingHTTPServer):
    daemon_threads = True
    # On Windows, SO_REUSEADDR would let two panels listen on the same port.
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
        log.info("Port %s is already in use; the panel is probably open at %s", port, url)
        if open_browser:
            webbrowser.open(url)
        return
    threading.Thread(target=app.schedule, daemon=True).start()  # PowerShell takes ~1s; get it ready now
    log.info("Panel open at %s  (Ctrl+C or close this window to stop)", url)
    if settings.public_url:
        log.info("Address for friends: %s", settings.public_url)
    if open_browser:
        webbrowser.open(url)
    with server:
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            log.info("Panel stopped.")
