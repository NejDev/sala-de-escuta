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
import threading
import time
import urllib.parse
import webbrowser
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable

from . import accounts, artists, config, curation, discovery, favorites, i18n, reviews, social, tempo
from .api import Spotify, SpotifyError, gate
from .auth import (
    LIBRARY_SCOPES, PLAYER_SCOPES, SOCIAL_SCOPES, TASTE_SCOPES, AuthRequest, TokenManager, exchange_code, missing_scopes,
    start_authorization,
)
from .config import (
    Settings, load_blocked, load_playlists, load_sensations, load_state, save_blocked, save_playlists, save_state,
)
from .deezer import Deezer, DeezerError
from .discovery import Hunt
from .i18n import t
from .musicbrainz import MusicBrainz
from .playlists import owned_playlists, run
from .views import album_view, item_row, pick_image

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
FAVORITE_PATH = re.compile(r"/api/favorites/(?P<id>[a-f0-9]{1,32})(?:/(?P<action>refresh|remove|show))?")
SCHEDULER_FIRST_S = 120  # let the panel settle after startup
SCHEDULER_TICK_S = 600  # at most one favorite rebuilt per tick, to spread Spotify requests out
MAX_BODY_BYTES = 64_000
COOKIE_NAME = "sala"
LIBRARY_KEY = re.compile(r"id:(?P<id>[A-Za-z0-9]{1,64})")
TRACK_URI = re.compile(r"spotify:track:[A-Za-z0-9]{1,64}")
PLAYLIST_ID_LIKE = re.compile(r"[A-Za-z0-9]{1,64}")  # Spotify ids are base62
LIKEABLE = re.compile(r"spotify:(?P<kind>track|episode):[A-Za-z0-9]{1,64}")
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
    liked: dict[str, bool] = field(default_factory=dict)  # heart state per song, so polling doesn't ask again
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


NEWS_PERIODS = (0, 3, 7, 14, 30, 90)  # 0 = released today
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
        self.musicbrainz = MusicBrainz()
        self._profiles: dict[str, Profile] = {}
        self._profiles_lock = threading.Lock()
        self._pending: dict[str, AuthRequest] = {}
        self._refreshing: dict[str, Hunt] = {}  # favorite id -> rebuild in progress
        self._refreshing_lock = threading.Lock()
        self._refresh_slot = threading.Lock()  # one rebuild at a time, manual or scheduled
        self._collector_wake = threading.Event()  # someone just joined Friends: build their taste now

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
        library = list(self.spotify(user).my_playlists())
        return {
            "me": {"id": user.id, "name": accounts.display_name(user.id), "is_owner": user.is_owner},
            "playlists": self._shelf(user, library),
            "hidden": [{"id": fav["id"], "name": fav["name"]} for fav in self._favorites(user) if fav.get("hidden")],
            "max_favorites": favorites.MAX_FAVORITES,
            "friends": social.allowed(user.id),
            "player_ready": not missing_scopes(user.paths.token, PLAYER_SCOPES),
            "search_paused_s": gate.remaining("search"),
        }

    def _shelf(self, user: Profile, library: list[dict]) -> list[dict]:
        """The bar: only favorites, the playlists the Sala rebuilds by itself."""
        owned = {playlist["id"]: playlist for playlist in library}
        ids = load_state(user.paths.state).get("playlists", {})
        specs = {spec["name"]: spec for spec in load_playlists()["playlists"]} if user.is_owner else {}
        shelf, gone = [], set()
        for fav in self._favorites(user):
            if fav["kind"] != "curated" and fav.get("playlist_id") not in owned:
                gone.add(fav["id"])  # deleted in the Spotify app: it leaves the Sala too
                continue
            if fav.get("hidden"):
                continue
            if fav["kind"] == "curated":
                spec = specs[fav["name"]]
                remote = owned.get(ids.get(spec["name"]))
                item = {
                    "key": spec["name"],
                    "name": spec["name"],
                    "kind": playlist_kind(spec),
                    "description": spec.get("description", ""),
                    "color": spec.get("color"),
                }
                if "mix" in spec:
                    item["sources"] = spec["mix"]["from"]
            else:
                remote = owned[fav["playlist_id"]]
                item = {
                    "key": f"fav:{fav['id']}",
                    "name": remote["name"],
                    "kind": "pinned" if fav["kind"] == "pinned" else "favorite",
                    "description": html.unescape(remote.get("description") or ""),
                    "color": fav.get("color"),
                }
            item.update(uri=None, image=None, total=0, favorite=self._favorite_view(user, fav))
            if remote:
                item.update(
                    uri=remote["uri"],
                    image=pick_image(remote.get("images"), 300),
                    total=(remote.get("items") or remote.get("tracks") or {}).get("total", 0),
                )
            shelf.append(item)
        if gone:
            favorites.change(user.id, lambda items: items.__setitem__(slice(None), [f for f in items if f["id"] not in gone]))
        return shelf

    @staticmethod
    def _require_owner(user: Profile) -> None:
        """The curated shelf and its base selection belong to the owner: friends don't even see them."""
        if not user.is_owner:
            raise UserError(t("err.playlist_not_found"), 404)

    def playlist(self, user: Profile, name: str) -> dict:
        if match := LIBRARY_KEY.fullmatch(name):
            playlist_id = match["id"]
        elif name.startswith("fav:"):
            playlist_id = self._favorite(user, name[4:])["playlist_id"]
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

    # Player

    def player(self, user: Profile) -> dict:
        if missing_scopes(user.paths.token, PLAYER_SCOPES):
            return {"needs_scope": True}
        sp = self.spotify(user)
        data = sp.playback()
        if not data or not data.get("item"):
            return {"item": None}
        device = data.get("device") or {}
        library_ready = not missing_scopes(user.paths.token, LIBRARY_SCOPES)
        return {
            "liked": self._liked(user, sp, data["item"].get("uri", "")) if library_ready else None,
            "library_ready": library_ready,
            "item": {**item_row(data["item"], image_size=120), "album_id": (data["item"].get("album") or {}).get("id")},
            "is_playing": data.get("is_playing", False),
            "progress_ms": data.get("progress_ms") or 0,
            "shuffle": data.get("shuffle_state", False),
            "repeat": data.get("repeat_state", "off"),
            "context_uri": (data.get("context") or {}).get("uri"),
            "device": {"name": device.get("name"), "volume": device.get("volume_percent")},
        }

    @staticmethod
    def _liked(user: Profile, sp: Spotify, uri: str) -> bool | None:
        """Whether the song (or episode) playing is in the person's library; asked once per song."""
        if not LIKEABLE.fullmatch(uri):
            return None
        if uri not in user.liked:
            try:
                user.liked[uri] = bool(sp.library_contains([uri])[0])
            except (SpotifyError, IndexError, TypeError):
                return None  # the heart is an extra: the player keeps working
        return user.liked[uri]

    def like(self, user: Profile, body: dict) -> dict:
        match = LIKEABLE.fullmatch(str(body.get("uri") or ""))
        if not match:
            raise UserError(t("err.like_what"))
        if missing_scopes(user.paths.token, LIBRARY_SCOPES):
            raise UserError(t("liked.need_auth"), 403, scope=True)
        uri, liked = match[0], bool(body.get("value"))
        sp = self.spotify(user)
        (sp.save_to_library if liked else sp.remove_from_library)([uri])
        user.liked[uri] = liked
        return {"ok": True, "liked": liked, "message": t(f"liked.{match['kind']}_{'on' if liked else 'off'}")}

    def player_action(self, user: Profile, body: dict) -> dict:
        action, value = body.get("action"), body.get("value")
        if action == "like":
            return self.like(user, body)
        if missing_scopes(user.paths.token, PLAYER_SCOPES):
            raise UserError(t("err.player_scope"), 403)
        sp = self.spotify(user)
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

    @staticmethod
    def _check_search() -> None:
        """Every discovery ends up finding songs through Spotify search: if it's paused, say so now."""
        paused = gate.remaining("search")
        if paused:
            raise UserError(pause_message(SpotifyError(429, "paused", retry_after=paused, family="search")), 429)

    def start_hunt(self, user: Profile, body: dict) -> dict:
        if body.get("kind") != "artist":  # the Artists search mostly finds people through MusicBrainz
            self._check_search()
        hunt, task = self._hunt_task(user, self.spotify(user), body, random.Random())
        with user.lock:
            if user.hunt:
                user.hunt.cancelled = True  # the previous discovery stops at its next step
            user.hunt = hunt
        threading.Thread(target=self._run_hunt, args=(hunt, task, i18n.current()), daemon=True).start()
        return hunt.snapshot()

    def _hunt_task(self, user: Profile, sp: Spotify, body: dict, rng: random.Random) -> tuple[Hunt, Callable[[], None]]:
        """Checks what the panel (or a favorite's recipe) asked for and prepares the discovery."""
        kind = body.get("kind")
        size = fan_range(body)
        recipe = {"kind": kind, "min_fans": size.min or None, "max_fans": size.max}
        if kind == "sense":
            text = " ".join((body.get("text") or "").split())
            if len(text) > FEELING_MAX_CHARS:
                raise UserError(t("err.feeling_too_long", max=FEELING_MAX_CHARS))
            spec = discovery.spec_from_text(text) if text else self._preset(body)
            if not tempo.available():
                raise UserError(t("err.tempo_missing"), 409)
            recipe.update({"text": text} if text else {"id": spec.get("id")})
            hunt = Hunt("sense", spec["name"], color=spec.get("color"), spec=spec)
            cache = discovery.TempoCache()

            def task() -> None:
                try:
                    discovery.sense(hunt, spec, sp, self.deezer, rng, cache, blocked=user.blocked, size=size)
                finally:
                    cache.save()
        elif kind == "roulette":
            genre = genre_from(body)
            recipe["genre"] = genre
            hunt = Hunt("roulette", t("label.roulette_genre", genre=genre) if genre else t("label.roulette"))

            def task() -> None:
                discovery.roulette(hunt, sp, self.deezer, rng, blocked=user.blocked, genre=genre, size=size)
        elif kind == "rabbit":
            seed = (body.get("seed") or "").strip()
            recipe["seed"] = seed
            hunt = Hunt("rabbit", t("label.rabbit"))

            def task() -> None:
                seeds = [seed] if seed else self._seed_artists(user, sp)
                discovery.rabbit_hole(hunt, sp, self.deezer, rng, seeds, blocked=user.blocked, size=size)
        elif kind == "news":
            genre = genre_from(body, required=True)
            try:
                days = 30 if body.get("days") in (None, "") else int(body["days"])
            except (TypeError, ValueError):
                days = 0
            if days not in NEWS_PERIODS:
                raise UserError(t("err.period"))
            recipe.update(genre=genre, days=days)
            hunt = Hunt("news", t("label.news", genre=genre))

            def task() -> None:
                discovery.news(hunt, sp, self.deezer, genre, size, days, blocked=user.blocked)
        elif kind == "artist":
            name = " ".join(str(body.get("name") or "").split())
            if not name:
                raise UserError(t("err.artist_name"))
            if len(name) > FEELING_MAX_CHARS:
                raise UserError(t("err.feeling_too_long", max=FEELING_MAX_CHARS))
            spotify_id = str(body.get("spotify") or "") or None
            if spotify_id and not PLAYLIST_ID_LIKE.fullmatch(spotify_id):
                raise UserError(t("err.artist_name"))
            recipe.update(name=name, spotify=spotify_id)
            hunt = Hunt("artist", name)

            def task() -> None:
                artists.discography(hunt, sp, self.musicbrainz, name, spotify_id)
        else:
            raise UserError(t("err.hunt_kind"))
        hunt.recipe = recipe
        return hunt, task

    def feature_track(self, user: Profile, body: dict) -> dict:
        """The track on someone else's album where the artist (or a member) appears, to play from it."""
        album = str(body.get("album") or "")
        if not PLAYLIST_ID_LIKE.fullmatch(album):
            raise UserError(t("err.pick_result"))
        wanted = {str(artist_id) for artist_id in body.get("artists") or []}
        tracks = self.spotify(user).album_tracks(album)
        track = next((tr for tr in tracks if wanted & {a.get("id") for a in tr.get("artists", [])}), None)
        if track is None:
            raise UserError(t("artists.no_track"), 404)
        return {"uri": track["uri"]}

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
        every = body.get("every") or None
        hunt = user.hunt
        if every:
            if every not in favorites.EVERY:
                raise UserError(t("fav.bad_every"))
            if not hunt or not hunt.recipe or not set(uris) <= {find.uri for find in hunt.finds}:
                raise UserError(t("fav.needs_discovery"))
        sp = self.spotify(user)
        same = next((playlist for playlist in self._owned(user, sp) if playlist["name"] == name), None)
        if every and not (same and self._favorite_for(user, same["id"])):
            if self._updating_count(user) >= favorites.MAX_FAVORITES:
                raise UserError(t("fav.too_many", max=favorites.MAX_FAVORITES), 409)
        if same:
            # Same name: the songs are only swapped if the person confirms (the old list is gone).
            if not body.get("replace"):
                raise UserError(t("save.exists", name=name), 409, exists=True)
            sp.replace_items(same["id"], uris)
            playlist, message = same, t("save.replaced", name=name, count=len(uris))
        else:
            playlist = sp.create_playlist(name, self._description(user, uris), False)
            sp.replace_items(playlist["id"], uris)
            message = t("save.created", name=name, count=len(uris))
        if every:
            self._make_favorite(user, playlist["id"], name, every, hunt)
            message += " " + t("fav.added", every=t(f"every.{every}"))
        self._remember(user, uris, name)
        return {"message": message, "uri": playlist["uri"], "id": playlist["id"], "favorite": bool(every)}

    def _make_favorite(self, user: Profile, playlist_id: str, name: str, every: str, hunt: Hunt) -> None:
        color = hunt.color or favorites.KIND_COLORS.get(hunt.kind)
        fav = favorites.new("discovery", name, every, playlist_id=playlist_id, recipe=hunt.recipe, color=color,
                            lang=i18n.current())

        def add(items: list[dict]) -> None:
            # The same playlist again (replaced by name): it keeps one entry with the new recipe.
            items[:] = [item for item in items if item.get("playlist_id") != playlist_id or item["kind"] == "curated"]
            items.append(fav)

        favorites.change(user.id, add)

    @staticmethod
    def _remember(user: Profile, uris: list[str], playlist: str) -> None:
        """Recent finds on the home screen: only songs that came from a discovery (we know their details)."""
        finds = {find.uri: find for find in (user.hunt.finds if user.hunt else [])}
        favorites.remember(user.id, [asdict(finds[uri]) for uri in uris if uri in finds], playlist)

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
        self._remember(user, uris, name)
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

    # Favorites: the bar's playlists, rebuilt by themselves

    def _favorites(self, user: Profile) -> list[dict]:
        if user.is_owner:
            return favorites.sync_curated(user.id, load_playlists()["playlists"])
        return favorites.load(user.id)

    def _favorite(self, user: Profile, fav_id: str) -> dict:
        fav = next((fav for fav in self._favorites(user) if fav["id"] == fav_id), None)
        if fav is None:
            raise UserError(t("fav.not_found"), 404)
        return fav

    @staticmethod
    def _favorite_for(user: Profile, playlist_id: str) -> dict | None:
        return next((fav for fav in favorites.load(user.id) if fav.get("playlist_id") == playlist_id), None)

    def _favorite_view(self, user: Profile, fav: dict) -> dict:
        running = self._refreshing.get(fav["id"])
        job = user.job
        if fav["kind"] == "curated" and job and job.status == "running" and job.name == fav["name"]:
            running = Hunt("refresh", fav["name"], message=(job.lines or [job.label])[-1])
        recipe = fav.get("recipe") or {}
        due = favorites.next_run(fav)
        return {
            "id": fav["id"],
            "kind": fav["kind"],
            "curated": fav["kind"] == "curated",
            "every": fav.get("every"),
            "last_run": int(fav["updated"] * 1000) if fav.get("updated") else None,
            "next_run": int(due * 1000) if due else None,
            "status": fav.get("status", "ok"),
            "message": fav.get("message", ""),
            "recipe": {"kind": recipe.get("kind"), "id": recipe.get("id")} if recipe else None,
            "running": {"message": running.message, "progress": running.progress, "total": running.total}
            if running else None,
        }

    def favorite_status(self, user: Profile, fav_id: str) -> dict:
        return self._favorite_view(user, self._favorite(user, fav_id))

    def set_every(self, user: Profile, fav_id: str, body: dict) -> dict:
        every = body.get("every")
        if every not in favorites.EVERY:
            raise UserError(t("fav.bad_every"))
        if self._favorite(user, fav_id)["kind"] == "pinned":
            raise UserError(t("fav.pinned_no_update"), 409)

        def edit(items: list[dict]) -> None:
            for fav in items:
                if fav["id"] == fav_id:
                    fav["every"] = every

        favorites.change(user.id, edit)
        return {**self.favorite_status(user, fav_id), "notice": t("fav.every_set", every=t(f"every.{every}"))}

    def _updating_count(self, user: Profile) -> int:
        return sum(1 for fav in self._favorites(user) if fav["kind"] == "discovery" and not fav.get("hidden"))

    def remove_favorite(self, user: Profile, fav_id: str) -> dict:
        """Off the bar, never lost: playlists that update are kept hidden (with their recipe) and can come
        back; a pinned shortcut is simply removed. The playlist always stays on Spotify."""
        fav = self._favorite(user, fav_id)
        if fav["kind"] == "pinned":
            favorites.change(user.id, lambda items: items.__setitem__(slice(None), [f for f in items if f["id"] != fav_id]))
            return {"message": t("fav.unpinned", name=fav["name"])}
        self._edit_favorite(user, fav_id, hidden=True)
        return {"message": t("fav.hidden", name=fav["name"])}

    def show_favorite(self, user: Profile, fav_id: str) -> dict:
        """Back on the bar; its schedule starts over from now."""
        fav = self._favorite(user, fav_id)
        if fav["kind"] == "discovery" and fav.get("hidden") and self._updating_count(user) >= favorites.MAX_FAVORITES:
            raise UserError(t("fav.too_many", max=favorites.MAX_FAVORITES), 409)
        self._edit_favorite(user, fav_id, hidden=False, last_run=time.time())
        return {"message": t("fav.shown", name=fav["name"])}

    @staticmethod
    def _edit_favorite(user: Profile, fav_id: str, **changes) -> None:
        def edit(items: list[dict]) -> None:
            for item in items:
                if item["id"] == fav_id:
                    item.update(changes)

        favorites.change(user.id, edit)

    def shelf_extras(self, user: Profile) -> dict:
        """What can go on the bar: curated playlists taken off it and the person's own playlists."""
        items = self._favorites(user)
        on_bar = {fav.get("playlist_id") for fav in items if fav["kind"] != "curated"}
        curated_ids = set(load_state(user.paths.state).get("playlists", {}).values()) if user.is_owner else set()
        owned = self._owned(user, self.spotify(user))
        by_id = {playlist["id"]: playlist for playlist in owned}
        ids = load_state(user.paths.state).get("playlists", {})

        def row(playlist: dict) -> dict:
            return {
                "id": playlist["id"],
                "name": playlist["name"],
                "image": pick_image(playlist.get("images"), 64),
                "total": (playlist.get("items") or playlist.get("tracks") or {}).get("total", 0),
            }

        def playlist_of(fav: dict) -> str | None:
            return ids.get(fav["name"]) if fav["kind"] == "curated" else fav.get("playlist_id")

        hidden = [
            {**(row(by_id[playlist_of(fav)]) if playlist_of(fav) in by_id else {"image": None, "total": 0}),
             "fav": fav["id"], "name": fav["name"], "kind": fav["kind"]}
            for fav in items if fav.get("hidden")
        ]
        return {
            "hidden": hidden,
            "playlists": [row(p) for p in owned if p["id"] not in on_bar and p["id"] not in curated_ids],
        }

    def pin(self, user: Profile, body: dict) -> dict:
        playlist_id = str(body.get("playlist") or "")
        playlist = next((p for p in self._owned(user, self.spotify(user)) if p["id"] == playlist_id), None)
        if playlist is None:
            raise UserError(t("save.not_yours"), 403)
        items = self._favorites(user)
        curated_ids = set(load_state(user.paths.state).get("playlists", {}).values()) if user.is_owner else set()
        if playlist_id in curated_ids or any(fav.get("playlist_id") == playlist_id for fav in items):
            raise UserError(t("fav.already"), 409)
        if sum(1 for fav in items if fav["kind"] == "pinned") >= favorites.MAX_PINNED:
            raise UserError(t("fav.too_many_pinned", max=favorites.MAX_PINNED), 409)
        fav = favorites.new("pinned", playlist["name"], None, playlist_id=playlist_id, lang=i18n.current())
        favorites.change(user.id, lambda items: items.append(fav))
        return {"message": t("fav.pinned", name=playlist["name"]), "key": f"fav:{fav['id']}"}

    def refresh_favorite(self, user: Profile, fav_id: str) -> dict:
        """'Update now': curated ones go through the update console; the others rebuild in the background."""
        fav = self._favorite(user, fav_id)
        if fav["kind"] == "curated":
            return {"job": self.start_job(user, {"playlist": fav["name"]})}
        if fav["kind"] == "pinned":
            raise UserError(t("fav.pinned_no_update"), 409)
        self._check_search()
        with self._refreshing_lock:
            if fav_id in self._refreshing:
                raise UserError(t("fav.already_running"), 409)
            self._refreshing[fav_id] = Hunt("refresh", fav["name"], message=t("fav.queued"))
        threading.Thread(target=self._refresh_in_background, args=(user, fav_id, i18n.current()), daemon=True).start()
        return self.favorite_status(user, fav_id)

    def _refresh_in_background(self, user: Profile, fav_id: str, lang: str) -> None:
        i18n.use(lang)
        try:
            self._refresh(user, fav_id)
        except Exception:
            log.exception("Favorite update failed")
        finally:
            with self._refreshing_lock:
                self._refreshing.pop(fav_id, None)

    def _refresh(self, user: Profile, fav_id: str) -> None:
        """Rebuilds one favorite: a fresh selection replaces the songs. One at a time, to spare Spotify."""
        with self._refresh_slot:
            fav = self._favorite(user, fav_id)
            sp = self.spotify(user)
            status, message = "ok", ""
            try:
                if fav["kind"] == "curated":
                    run(sp, load_playlists(), load_state(user.paths.state), only=[fav["name"]])
                    message = t("fav.updated_curated")
                else:
                    hunt, task = self._hunt_task(user, sp, fav["recipe"], random.Random())
                    with self._refreshing_lock:
                        self._refreshing[fav_id] = hunt  # the bar shows this discovery's progress
                    try:
                        task()
                    finally:
                        discovery.matches.save()
                    if hunt.finds:
                        sp.replace_items(fav["playlist_id"], [find.uri for find in hunt.finds])
                        message = t("fav.updated", count=len(hunt.finds))
                    else:
                        status, message = "empty", hunt.message  # keeps the current songs
            except SpotifyError as err:
                status = {429: "paused", 404: "missing"}.get(err.status, "error")
                message = t("fav.missing") if status == "missing" else spotify_message(err)
            except (DeezerError, UserError) as err:
                status, message = "error", t("err.discovery_failed", error=err)
            except SystemExit as exc:
                status, message = "error", str(exc.code)
            self._mark_run(user.id, lambda item: item["id"] == fav_id, status, message)

    @staticmethod
    def _mark_run(user_id: str, which: Callable[[dict], bool], status: str, message: str) -> None:
        def edit(items: list[dict]) -> None:
            for fav in items:
                if which(fav):
                    fav["status"], fav["message"] = status, message
                    if status != "paused":  # a Spotify pause: try again on the next round
                        fav["last_run"] = time.time()
                    if status == "ok":
                        fav["updated"] = fav["last_run"]

        favorites.change(user_id, edit)

    def run_due(self, now: float | None = None) -> str | None:
        """Rebuilds the most overdue favorite of anyone in the room (one per call). Returns its id."""
        if gate.remaining("search"):
            return None  # every rebuild searches Spotify; wait for the pause to end
        now = time.time() if now is None else now
        due = []
        for user_id in config.list_users():
            try:
                user = self.profile(user_id)
                items = self._favorites(user)
            except UserError:
                continue  # signed out: nothing to rebuild with
            ids = load_state(user.paths.state).get("playlists", {})
            for fav in items:
                exists = fav.get("playlist_id") or (fav["kind"] == "curated" and ids.get(fav["name"]))
                if exists and fav["id"] not in self._refreshing and favorites.is_due(fav, now):
                    due.append((favorites.next_run(fav), user, fav))
        if not due:
            return None
        _, user, fav = min(due, key=lambda item: item[0])
        i18n.use(fav.get("lang"))
        self._refresh(user, fav["id"])
        return fav["id"]

    def scheduler(self) -> None:
        """Runs inside the panel: as long as it's open, favorites rebuild themselves on time."""
        time.sleep(SCHEDULER_FIRST_S)
        while True:
            try:
                self.run_due()
            except Exception:
                log.exception("Scheduled update failed")
            time.sleep(SCHEDULER_TICK_S)

    # Friends: affinity and matches, only among people who turned it on

    def friends(self, user: Profile) -> dict:
        if not social.allowed(user.id):
            raise UserError(t("friends.off"), 403)
        ready = not missing_scopes(user.paths.token, SOCIAL_SCOPES)
        owner = {"access": self._friends_access()} if user.is_owner else {}
        if not social.sharing(user.id):
            return {"sharing": False, "ready": ready, **owner}  # nothing about anyone else
        if ready:
            self._collect(user, fresh_s=120)
        everyone = {uid: social.plays(uid) for uid in config.list_users()
                    if social.sharing(uid) and social.allowed(uid)}
        names = {uid: accounts.display_name(uid) for uid in everyone}
        tastes = {uid: social.taste(uid) for uid in everyone}
        profiles = {uid: social.profile(everyone[uid], tastes[uid]) for uid in everyone}
        artist_names: dict[str, str] = {}
        for uid in everyone:  # only names of artists both people like are ever shown
            artist_names.update(social.artist_names(everyone[uid], tastes[uid]))
        mine = everyone.get(user.id, [])
        friends = []
        for uid, items in everyone.items():
            if uid != user.id:
                numbers = social.stats(items)
                friends.append({"id": uid, "name": names[uid],
                                "affinity": social.affinity(profiles.get(user.id, {}), profiles[uid], artist_names),
                                "plays_7d": numbers["plays_7d"]})  # not what they played: only matches show songs
        friends.sort(key=lambda friend: -(friend["affinity"] or {}).get("percent", -1))
        me = {**social.stats(mine), "top": not missing_scopes(user.paths.token, TASTE_SCOPES),
              "taste": bool(tastes.get(user.id))}
        return {"sharing": True, "ready": ready, "me": me, "friends": friends,
                "feed": social.feed(everyone, names, user.id), **owner}

    @staticmethod
    def _friends_access() -> dict:
        owner = config.owner_id()
        return {
            "new": social.access()["new"],
            "people": [{"id": uid, "name": accounts.display_name(uid), "allowed": social.allowed(uid)}
                       for uid in config.list_users() if uid != owner],
        }

    def set_friends_access(self, user: Profile, body: dict) -> dict:
        """Owner only: who may use Friends."""
        self._require_owner(user)
        if "new" in body:
            social.set_new(bool(body["new"]), config.list_users())
            message = t("friends.access_new_on" if body["new"] else "friends.access_new_off")
        else:
            target = str(body.get("user") or "")
            if target not in config.list_users() or target == user.id:
                raise UserError(t("err.which_person"))
            allow = bool(body.get("allowed"))
            social.set_allowed(target, allow)
            message = t("friends.access_on" if allow else "friends.access_off", name=accounts.display_name(target))
        return {**self.friends(user), "message": message}

    def set_sharing(self, user: Profile, body: dict) -> dict:
        share, forget = bool(body.get("share")), bool(body.get("forget"))
        if not social.allowed(user.id):
            raise UserError(t("friends.off"), 403)
        if share and missing_scopes(user.paths.token, SOCIAL_SCOPES):
            raise UserError(t("friends.need_auth"), 403, scope=True)
        social.set_share(user.id, share, forget=forget)
        if share:
            self._collect(user)
            self._collector_wake.set()  # their taste profile gets built in the background right away
        message = t("friends.joined") if share else t("friends.forgot" if forget else "friends.left")
        return {**self.friends(user), "message": message}

    def _collect(self, user: Profile, fresh_s: float = 0) -> None:
        if fresh_s and time.time() - social.settings(user.id).get("collected", 0) < fresh_s:
            return
        try:
            social.collect(self.spotify(user), user.id)
        except SpotifyError as err:
            log.warning("Couldn't read %s's recent plays: %s", user.id, err)

    def collector(self) -> None:
        """While the panel is open, reads what the people who joined Friends listened to, and every
        few days what they like (most played, playlists, liked songs) for the affinity."""
        self._collector_wake.wait(SCHEDULER_FIRST_S)
        while True:
            self._collector_wake.clear()
            for user_id in config.list_users():
                if not social.sharing(user_id) or not social.allowed(user_id):
                    continue
                try:
                    user = self.profile(user_id)
                    if not missing_scopes(user.paths.token, SOCIAL_SCOPES):
                        self._collect(user)
                    with_top = not missing_scopes(user.paths.token, TASTE_SCOPES)
                    if social.taste_due(user_id, with_top):
                        social.build_taste(self.spotify(user), user_id, with_top)
                except UserError:
                    continue  # signed out
                except Exception:
                    log.exception("Reading what %s listens to failed", user_id)
            self._collector_wake.wait(social.COLLECT_EVERY_S)

    # Reviews: albums rated and written about, private or open to the room

    @staticmethod
    def _room() -> tuple[list[str], dict[str, str]]:
        users = config.list_users()
        return users, {uid: accounts.display_name(uid) for uid in users}

    def reviews(self, user: Profile) -> dict:
        users, names = self._room()
        return {"room": reviews.room(user.id, users, names), "mine": reviews.own(user.id, names)}

    def _album(self, user: Profile, album_id: str, users: list[str]) -> dict:
        known = reviews.known_album(album_id, users)
        if known:
            return known
        try:
            return album_view(self.spotify(user).album(album_id))
        except SpotifyError as err:
            if err.status in (400, 404):
                raise UserError(t("reviews.invalid_album"), 404) from None
            raise

    def album_reviews(self, user: Profile, raw_id: str) -> dict:
        album_id = reviews.album_id(raw_id)
        if not album_id:
            raise UserError(t("reviews.invalid_album"))
        users, names = self._room()
        return {"album": self._album(user, album_id, users), **reviews.of_album(album_id, user.id, users, names)}

    def save_review(self, user: Profile, body: dict) -> dict:
        album_id = reviews.album_id(str(body.get("album") or ""))
        if not album_id:
            raise UserError(t("reviews.invalid_album"))
        try:
            stars = reviews.rating(body.get("rating"))
        except (TypeError, ValueError):
            raise UserError(t("reviews.bad_rating")) from None
        text = str(body.get("text") or "").strip()
        if len(text) > reviews.MAX_TEXT:
            raise UserError(t("reviews.too_long", max=reviews.MAX_TEXT))
        if stars is None and not text:
            raise UserError(t("reviews.empty"))
        public = bool(body.get("public"))
        users, _ = self._room()
        reviews.save(user.id, self._album(user, album_id, users), stars, text, public)
        return {**self.album_reviews(user, album_id), "message": t("reviews.saved_public" if public else "reviews.saved")}

    def delete_review(self, user: Profile, body: dict) -> dict:
        album_id = reviews.album_id(str(body.get("album") or ""))
        if not album_id or not reviews.delete(user.id, album_id):
            raise UserError(t("reviews.not_found"), 404)
        return {**self.album_reviews(user, album_id), "message": t("reviews.deleted")}

    @staticmethod
    def recent_finds(user: Profile) -> dict:
        return {"finds": favorites.recent(user.id)}

    # Editing

    def add_item(self, user: Profile, name: str, body: dict) -> dict:
        entry, uri = body.get("entry", "").strip(), body.get("uri", "")
        if not entry or not uri.startswith("spotify:"):
            raise UserError(t("err.pick_result"))
        own_id = None
        if match := LIBRARY_KEY.fullmatch(name):
            own_id = match["id"]
        elif name.startswith("fav:"):
            fav = self._favorite(user, name[4:])
            if fav["kind"] != "pinned":
                raise UserError(t("fav.pinned_only_add"), 409)
            own_id = fav["playlist_id"]
        if own_id:
            # A playlist from their own account: it only goes to Spotify (which refuses if it isn't theirs).
            try:
                self.spotify(user).add_items(own_id, [uri])
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
            if not job.dry_run:
                App._mark_run(user.id, lambda fav: fav["kind"] == "curated" and fav["name"] == name, "ok", "")
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
        except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError):
            return  # the browser closed the connection before the answer arrived
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
        if method == "POST" and path == "/api/artists/track":
            return app.feature_track(user, body)
        if method == "GET" and path == "/api/reviews":
            return app.reviews(user)
        if method == "GET" and path == "/api/reviews/album":
            return app.album_reviews(user, query.get("id", ""))
        if method == "POST" and path == "/api/reviews":
            return app.save_review(user, body)
        if method == "POST" and path == "/api/reviews/delete":
            return app.delete_review(user, body)
        if method == "GET" and path == "/api/friends":
            return app.friends(user)
        if method == "POST" and path == "/api/friends":
            return app.set_sharing(user, body)
        if method == "POST" and path == "/api/friends/access":
            return app.set_friends_access(user, body)
        if method == "GET" and path == "/api/recent":
            return app.recent_finds(user)
        if method == "GET" and path == "/api/favorites/extras":
            return app.shelf_extras(user)
        if method == "POST" and path == "/api/favorites/pin":
            return app.pin(user, body)
        if match := FAVORITE_PATH.fullmatch(path):
            fav_id, action = match["id"], match["action"]
            if method == "GET" and not action:
                return app.favorite_status(user, fav_id)
            if method == "POST" and not action:
                return app.set_every(user, fav_id, body)
            if method == "POST" and action == "refresh":
                return app.refresh_favorite(user, fav_id)
            if method == "POST" and action == "remove":
                return app.remove_favorite(user, fav_id)
            if method == "POST" and action == "show":
                return app.show_favorite(user, fav_id)
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
    threading.Thread(target=app.scheduler, daemon=True).start()
    threading.Thread(target=app.collector, daemon=True).start()
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
