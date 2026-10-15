"""Sensations, Discover and New releases.

- Sensations: starts from playlists people made for a moment (workout, focus...),
  listens to each track's preview, measures BPM and energy and keeps only what
  fits that sensation's range.
- Roulette: draws barely-played albums from any year (Spotify's tag:hipster) and
  lesser-known tracks from genres all over the world (Deezer).
- Rabbit hole: starts from an artist you already listen to and hops from related
  artist to related artist, always toward the lesser-known ones.
- New releases: the latest releases from a genre's artists, within the chosen size.

Everything ends up on Spotify: Deezer tracks are located by ISRC.
Progress messages and reasons are written with i18n.t() in the language of
whoever started the discovery (the discovery thread sets it).
"""
from __future__ import annotations

import json
import logging
import math
import os
import random
import threading
from concurrent.futures import Future, ProcessPoolExecutor, ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from typing import Callable, Collection, Iterator

from . import config, curation, i18n, tempo
from .api import Spotify, SpotifyError
from .deezer import Deezer, DeezerError
from .i18n import t
from .views import pick_image

SENSE_TARGET = 20
SENSE_MAX_LISTEN = 72
PLAYLISTS_PER_SOURCE = 2
ROULETTE_COUNT = 12
RABBIT_WALKS = 4
RABBIT_HOPS = 4
RABBIT_TRACKS = 2  # from the last artist; one from each artist in between
MIN_FANS = 100
LISTEN_THREADS = 6
SIZE_BATCH = 24  # tracks whose artist's fans are checked at once (Sensations)
NEWS_RESULTS = 24
NEWS_MAX_ARTISTS = 45  # right-sized artists whose releases we look at
NEWS_ARTIST_POOL = 120  # genre artists gathered from playlists, before the fans filter

# Searches that bring up typical tracks of each genre on Deezer. Edit freely.
WORLD_GENRES = (
    "zamrock", "ethio jazz", "afrobeat", "highlife", "city pop", "enka", "rebetiko", "fado",
    "chamamé", "cumbia psicodélica", "chicha peruana", "tropicália", "baião", "frevo", "carimbó",
    "lambada", "kizomba", "semba", "mbalax", "soukous", "raï", "dangdut",
    "kroncong", "j-jazz", "shibuya-kei", "anatolian rock", "arabesk", "klezmer", "balkan brass",
    "tango nuevo", "chacarera", "son cubano", "bolero", "mambo", "salsa dura", "calypso", "soca",
    "rocksteady", "dub", "lovers rock", "zydeco", "bluegrass", "delta blues", "doo-wop",
    "northern soul", "yacht rock", "krautrock", "italo disco", "chanson", "yé-yé", "schlager",
    "joik", "sea shanty", "irish trad", "flamenco", "rumba catalana", "huayno", "forró pé de serra",
    "samba rock", "choro", "maracatu", "brega", "tecnobrega", "manguebeat", "sertanejo raiz",
    "jovem guarda", "exotica", "space age pop", "library music", "vaporwave", "shoegaze",
    "dream pop", "math rock", "post-rock", "midwest emo", "trip hop", "jungle", "uk garage",
    "footwork", "amapiano", "gqom", "kuduro", "grime", "zouk", "gamelan", "throat singing",
    "hawaiian slack key", "bossa nova japonesa", "turkish psych", "persian pop",
)

# "Algorithm" tracks that crowd focus/relaxation playlists and aren't music worth discovering.
JUNK_WORDS = (
    "binaural", "white noise", "brown noise", "pink noise", "rain sounds", "ruido branco",
    "asmr", "hz", "solfeggio", "sleep music", "study music", "relaxing music", "musica relaxante",
    "bpm", "workout remix", "workout music", "fitness music",
)

# Local dictionary of feelings for the Sensations free-text field (no paid AI).
# Each entry: Portuguese/English stems -> BPM range, energy, color and extra searches.
# Stems with 4+ letters match as a prefix ("raiv" catches "raiva" and "raivoso");
# shorter ones only match a whole word.
FEELINGS: tuple[tuple[tuple[str, ...], dict], ...] = (
    (("odio", "odiar", "odiand", "odei", "raiv", "furi", "puto", "puta da vida", "brav", "irritad", "revolt",
      "vinganc", "rage", "angry", "anger", "hate", "fury", "mad", "pissed", "annoy", "revenge"),
     {"bpm": [125, 185], "energy": [0.72, 1.0], "color": "#D8453B",
      "sources": ["raiva", "rage music", "metal pesado", "hardcore punk", "nu metal"]}),
    (("coracao partido", "termino", "fossa", "sofrenci", "corno", "breakup", "break up", "heartbr", "dumped"),
     {"bpm": [60, 115], "energy": [0.2, 0.8], "color": "#9C7AA8",
      "sources": ["sofrência", "fossa", "breakup songs", "músicas de término"]}),
    (("trist", "chor", "depre", "melancol", "melanchol", "deprimid", "sad", "sadn", "luto", "cry", "cryi",
      "grief", "griev", "mourn", "gloom"),
     {"bpm": [55, 100], "energy": [0.0, 0.62], "color": "#8E9AAF",
      "sources": ["músicas tristes", "sad songs", "sad piano", "sad indie"]}),
    (("saudad", "nostalg", "lembranc", "infancia", "memor", "miss you", "missing", "childhood", "throwback"),
     {"bpm": [60, 115], "energy": [0.0, 0.72], "color": "#C9A27E",
      "sources": ["saudade", "nostalgia", "mpb saudade", "anos 80 nostalgia"]}),
    (("solid", "sozinh", "lonely", "lonel", "alone", "isolad", "isolat"),
     {"bpm": [55, 100], "energy": [0.0, 0.6], "color": "#7C8BA6",
      "sources": ["solidão", "lonely songs", "sad indie"]}),
    (("amor", "apaixon", "paixao", "romant", "romanc", "love", "namor", "crush"),
     {"bpm": [60, 115], "energy": [0.2, 0.78], "color": "#E3909E",
      "sources": ["músicas românticas", "love songs", "r&b romântico", "mpb romântica"]}),
    (("sexy", "sensual", "desejo", "desir", "tesao", "safad", "seduct"),
     {"bpm": [65, 110], "energy": [0.3, 0.78], "color": "#C0587E",
      "sources": ["sensual", "slow jams", "r&b sensual"]}),
    (("feliz", "felicid", "alegri", "alegre", "happy", "happi", "joy", "joyf", "cheer", "glad", "bom humor",
      "good mood", "good vibes", "contente"),
     {"bpm": [100, 135], "energy": [0.55, 1.0], "color": "#F2C14E",
      "sources": ["músicas felizes", "happy hits", "good vibes"]}),
    (("eufori", "euphori", "hype", "empolgad", "excit", "pumped", "energ", "pilhad", "animad"),
     {"bpm": [120, 150], "energy": [0.7, 1.0], "color": "#F06A4F",
      "sources": ["hype", "euforia", "edm festival", "músicas animadas"]}),
    (("confian", "confiden", "poderos", "power", "chefe", "boss", "foda", "badass", "imbativel", "unstopp",
      "marra", "villain"),
     {"bpm": [85, 145], "energy": [0.65, 1.0], "color": "#D4A84B",
      "sources": ["confiança", "boss music", "rap motivação", "músicas de vilão"]}),
    (("esperanc", "recomec", "superac", "hope", "uplift", "fresh start", "overcom"),
     {"bpm": [70, 125], "energy": [0.35, 0.88], "color": "#9FD3A8",
      "sources": ["esperança", "superação", "uplifting", "hopeful indie"]}),
    (("ansied", "ansios", "anxi", "nervos", "nervou", "estress", "stress", "panico", "panic", "preocupad",
      "worr", "overwhelm"),
     {"bpm": [55, 90], "energy": [0.0, 0.5], "color": "#7FB7BE",
      "sources": ["calma ansiedade", "calm anxiety", "ambient calm", "piano calmo"]}),
    (("calm", "paz", "peace", "tranquil", "zen", "medit", "relax", "chill", "sereno", "serene", "unwind"),
     {"bpm": [50, 88], "energy": [0.0, 0.48], "color": "#B8C4A0",
      "sources": ["paz", "meditação", "ambient peaceful", "música calma"]}),
    (("medo", "fear", "terror", "horror", "sombri", "dark", "tens", "assombr", "haunt", "creep", "spook", "scar"),
     {"bpm": [60, 130], "energy": [0.15, 0.8], "color": "#6F5E8C",
      "sources": ["dark ambient", "trilha de terror", "darkwave", "músicas sombrias"]}),
    (("sono", "dormir", "cansad", "exaust", "exhaust", "tired", "sleep", "insomn"),
     {"bpm": [45, 78], "energy": [0.0, 0.38], "color": "#5B6C8F",
      "sources": ["dormir", "sleep piano", "ambient sleep"]}),
    (("foco", "concentr", "estud", "focus", "study", "studi", "produtiv", "productiv"),
     {"bpm": [55, 100], "energy": [0.0, 0.7], "color": "#7FB7BE",
      "sources": ["foco", "deep focus", "lofi estudar"]}),
    (("festa", "balada", "danc", "rolê", "role", "party", "club", "rave", "celebrat"),
     {"bpm": [112, 132], "energy": [0.65, 1.0], "color": "#E3909E",
      "sources": ["festa", "dance hits", "balada"]}),
)
CONSENSUS_LISTEN = 48
CONSENSUS_MIN_MEASURED = 6
CONSENSUS_BPM_OCTAVES = 0.2  # ±15% around the typical pulse
CONSENSUS_ENERGY = 0.22

# Nothing religious, of any denomination. Strong words discard a track on their own;
# "hints" only count toward discarding a whole playlist when they show up in several tracks
# (playlists called "peace" or "hope" are often gospel without saying so in the song title).
RELIGIOUS_WORDS = (
    "gospel", "worship", "louvor", "louvores", "adoracao", "christian", "cristao", "crista", "cristaos",
    "evangelico", "evangelica", "catolico", "catolica", "catholic", "igreja", "church", "hino", "hinos",
    "hymn", "hymns", "harpa crista", "cantor cristao", "aleluia", "hallelujah", "jesus", "cristo", "christ",
    "deus", "dios", "dieu", "gott", "god", "espirito santo", "holy spirit", "salmo", "salmos", "psalm",
    "psalms", "biblia", "bible", "evangelho", "pastor", "pastora", "padre", "ministerio", "missionario",
    "pregacao", "sermon", "culto", "terco", "rosario", "rosary", "ave maria", "gregorian", "gregoriano",
    "liturgia", "liturgical", "mantra", "mantras", "bhajan", "kirtan", "devotional", "devocional",
    "nasheed", "quran", "alcorao", "allah", "sufi", "qawwali", "umbanda", "candomble", "orixa", "orixas",
    "spiritual", "spirituals", "espiritual", "buddhist", "budista", "chant", "torah", "shabbat",
    "krishna", "yahweh", "adonai", "messias", "messiah", "amem", "amen", "oracao", "prayer",
    "rezar", "fe", "praise",
)
RELIGIOUS_HINTS = (
    "senhor", "ceu", "gloria", "graca", "santo", "santa", "anjo", "anjos", "milagre", "milagres",
    "promessa", "adorar", "sobrenatural", "uncao", "altar", "cruz", "pai", "eterno", "redencao",
    "salvacao", "ressuscita", "fiel", "heaven", "lord", "grace", "holy", "angel",
)

log = logging.getLogger(__name__)


@dataclass
class Find:
    uri: str
    title: str
    subtitle: str
    image: str | None
    duration_ms: int
    reason: str = ""
    bpm: float | None = None
    energy: float | None = None
    tag: str = ""  # short label (genre or year) shown on the roulette pile
    artists: list[str] = field(default_factory=list)  # for "don't show this artist again"
    released: str | None = None  # release date (New releases)
    fans: int | None = None  # the artist's fans, when we know them


@dataclass(frozen=True)
class FanRange:
    """Artist size the person chose: minimum and (optionally) maximum fans."""

    min: int = 0
    max: int | None = None

    @property
    def active(self) -> bool:
        return self.min > 0 or self.max is not None

    def ok(self, fans: int | None) -> bool:
        fans = fans or 0
        return fans >= self.min and (self.max is None or fans <= self.max)


ANY_SIZE = FanRange()


class FanCounts:
    """Fans per artist, kept while the panel is open (each lookup costs a request)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._by_id: dict[int, int] = {}
        self._by_name: dict[str, int | None] = {}

    def by_id(self, dz: Deezer, artist_id: int) -> int:
        with self._lock:
            if artist_id in self._by_id:
                return self._by_id[artist_id]
        fans = dz.artist(artist_id).get("nb_fan") or 0
        with self._lock:
            self._by_id[artist_id] = fans
        return fans

    def known(self, artist_id: int | None) -> int | None:
        """Fans already looked up, without asking again."""
        with self._lock:
            return self._by_id.get(artist_id)

    def by_name(self, dz: Deezer, name: str) -> int | None:
        key = curation.normalize(name)
        with self._lock:
            if key in self._by_name:
                return self._by_name[key]
        found = dz.search_artist(name)
        fans = found.get("nb_fan") if found else None
        with self._lock:
            self._by_name[key] = fans
        return fans


fan_counts = FanCounts()


@dataclass
class Hunt:
    kind: str  # sense | roulette | rabbit | news | artist
    label: str
    color: str | None = None
    status: str = "running"  # running | done | error | cancelled
    message: str = ""
    progress: int = 0
    total: int = 0
    finds: list[Find] = field(default_factory=list)
    chains: list[dict] = field(default_factory=list)
    cancelled: bool = False
    spec: dict | None = None  # the sensation's parameters (used for the playlist description)
    recipe: dict | None = None  # what rebuilds this discovery later (a favorite's automatic updates)
    artist: dict | None = None  # Artists search: who it is, with members and subunits
    releases: list[dict] = field(default_factory=list)  # Artists search: their releases, newest first

    def snapshot(self) -> dict:
        return {
            "kind": self.kind,
            "label": self.label,
            "color": self.color,
            "status": self.status,
            "message": self.message,
            "progress": self.progress,
            "total": self.total,
            "finds": [asdict(find) for find in list(self.finds)],
            "chains": [
                {"path": chain["path"], "finds": [asdict(find) for find in chain["finds"]]}
                for chain in list(self.chains)
            ],
            "artist": self.artist,
            "releases": list(self.releases),
        }


class TempoCache:
    """BPM/energy already measured, by Deezer id, so the same preview isn't heard twice."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        try:
            self._data: dict[str, list | None] = json.loads(config.TEMPO_CACHE_FILE.read_text(encoding="utf-8"))
        except (FileNotFoundError, ValueError):
            self._data = {}
        self._dirty = False

    def get(self, key: str) -> tuple[bool, tempo.Analysis | None]:
        with self._lock:
            if key not in self._data:
                return False, None
            value = self._data[key]
        return True, tempo.Analysis(*value) if value else None

    def put(self, key: str, analysis: tempo.Analysis | None) -> None:
        with self._lock:
            self._data[key] = [analysis.bpm, analysis.confidence, analysis.energy] if analysis else None
            self._dirty = True

    def save(self) -> None:
        with self._lock:
            if not self._dirty:
                return
            config.DATA_DIR.mkdir(exist_ok=True)
            config.TEMPO_CACHE_FILE.write_text(json.dumps(self._data), encoding="utf-8")
            self._dirty = False


_pool: ProcessPoolExecutor | None = None
_pool_lock = threading.Lock()


def measure_in_process(mp3: bytes) -> tempo.Analysis | None:
    """The analysis is pure CPU; in separate processes it doesn't fight the server for the GIL."""
    global _pool
    with _pool_lock:
        if _pool is None:
            _pool = ProcessPoolExecutor(max_workers=max(1, min(4, (os.cpu_count() or 2) - 1)))
    return _pool.submit(tempo.measure, mp3).result()


# ---------- Pure rules


def fit_bpm(bpm: float, low: float, high: float) -> int | None:
    """BPM inside the range, accepting half/double (the most common tempo-measuring mistake)."""
    for candidate in (bpm, bpm * 2, bpm / 2):
        if low <= candidate <= high:
            return round(candidate)
    return None


def fits(analysis: tempo.Analysis | None, spec: dict) -> int | None:
    if analysis is None:
        return None
    low_energy, high_energy = spec["energy"]
    if not low_energy <= analysis.energy <= high_energy:
        return None
    return fit_bpm(analysis.bpm, *spec["bpm"])


def next_hop(
    options: list[dict], visited: set, rng: random.Random, blocked: Collection[str] = frozenset(),
    size: FanRange = ANY_SIZE,
) -> dict | None:
    """Among the related artists of the requested size, picks from the least-known third."""
    floor = max(MIN_FANS, size.min)  # under 100 fans it's usually an empty or duplicate profile
    fresh = [
        artist for artist in options
        if artist["id"] not in visited and artist.get("nb_fan", 0) >= floor
        and (size.max is None or artist.get("nb_fan", 0) <= size.max)
        and not is_religious(artist.get("name", "")) and curation.normalize(artist.get("name", "")) not in blocked
    ]
    if not fresh:
        return None
    fresh.sort(key=lambda artist: artist.get("nb_fan", 0))
    return rng.choice(fresh[: max(1, len(fresh) // 3)])


def is_junk(track: dict) -> bool:
    text = f" {curation.normalize(track.get('title', '') + ' ' + track.get('artist', {}).get('name', ''))} "
    return any(f" {word} " in text for word in JUNK_WORDS)


def _says(texts: tuple[str, ...], words: tuple[str, ...]) -> bool:
    text = f" {curation.normalize(' '.join(t for t in texts if t))} "
    return any(f" {word} " in text for word in words)


def is_religious(*texts: str) -> bool:
    return _says(texts, RELIGIOUS_WORDS)


def _track_texts(track: dict) -> tuple[str, ...]:
    """Title, artist and album of a Deezer or Spotify track."""
    artists = [track.get("artist", {}).get("name", "")] + [a.get("name", "") for a in track.get("artists", [])]
    album = track.get("album") or {}
    return (track.get("title") or track.get("name") or "", *artists, album.get("title") or album.get("name") or "")


def religious_track(track: dict) -> bool:
    return is_religious(*_track_texts(track))


def religious_collection(name: str, tracks: list[dict], owner: str = "") -> bool:
    """Religious playlist/album: an explicit name, or several tracks with religious words and hints."""
    if is_religious(name, owner):
        return True
    hits = sum(1 for track in tracks if _says(_track_texts(track), RELIGIOUS_WORDS + RELIGIOUS_HINTS))
    return hits >= max(2, len(tracks) // 10)


def blocked_set(names: list[str]) -> set[str]:
    """Blocked artist names, normalized to compare without accents or case."""
    return {curation.normalize(name) for name in names if name.strip()}


def blocked_track(track: dict, blocked: Collection[str]) -> bool:
    """A track (Deezer or Spotify) with any artist the person asked not to see again."""
    if not blocked:
        return False
    names = [track.get("artist", {}).get("name", "")] + [a.get("name", "") for a in track.get("artists", [])]
    return any(curation.normalize(name) in blocked for name in names if name)


def usable(track: dict, blocked: Collection[str] = frozenset()) -> bool:
    return (
        bool(track.get("preview")) and track.get("readable", True)
        and not is_junk(track) and not religious_track(track) and not blocked_track(track, blocked)
    )


def _mentions(tokens: list[str], text: str, stem: str) -> bool:
    stem = curation.normalize(stem)
    if " " in stem:
        return f" {stem} " in text
    if len(stem) >= 4:
        return any(token.startswith(stem) for token in tokens)
    return stem in tokens


def spec_from_text(text: str) -> dict:
    """Turns what the person wrote ("anger", "saudade de casa") into a sensation.

    The phrase itself is the first search: plenty of playlists are named after feelings.
    If the dictionary recognizes the feeling, it sets the rhythm and widens the searches;
    otherwise "bpm" stays None and the rhythm is learned from the songs (see consensus).
    """
    clean = " ".join(text.split())
    normalized = curation.normalize(clean)
    tokens = normalized.split()
    label = clean[:1].upper() + clean[1:]
    for stems, params in FEELINGS:
        if any(_mentions(tokens, f" {normalized} ", stem) for stem in stems):
            extra = [s for s in params["sources"] if curation.normalize(s) != normalized]
            return {
                "name": label,
                "description": t("sense.free_description", feeling=clean.lower()),
                "color": params["color"],
                "bpm": params["bpm"],
                "energy": params["energy"],
                "sources": [clean, *extra],
            }
    return {
        "name": label,
        "description": t("sense.free_learned", feeling=clean.lower()),
        "color": None,
        "bpm": None,
        "energy": None,
        "sources": [clean, t("sense.query_songs", feeling=clean), f"{clean} playlist"],
    }


def fold_bpm(bpm: float) -> float:
    """Brings the BPM into the 70–140 octave, where half/double become the same pulse."""
    while bpm < 70:
        bpm *= 2
    while bpm >= 140:
        bpm /= 2
    return bpm


def consensus(analyses: list[tempo.Analysis]) -> tuple[float, float] | None:
    """Typical pulse and energy (medians) of a set of previews."""
    if len(analyses) < CONSENSUS_MIN_MEASURED:
        return None
    bpms = sorted(fold_bpm(a.bpm) for a in analyses)
    energies = sorted(a.energy for a in analyses)
    middle = len(analyses) // 2
    return bpms[middle], energies[middle]


def consensus_distance(analysis: tempo.Analysis, center: tuple[float, float]) -> float | None:
    """Distance to the center (0 = identical); None if it's outside the pattern."""
    center_bpm, center_energy = center
    bpm_gap = abs(math.log2(fold_bpm(analysis.bpm) / center_bpm)) / CONSENSUS_BPM_OCTAVES
    energy_gap = abs(analysis.energy - center_energy) / CONSENSUS_ENERGY
    if bpm_gap > 1 or energy_gap > 1:
        return None
    return bpm_gap + energy_gap


def lesser_known(tracks: list[dict]) -> list[dict]:
    """The less popular half of a search (Deezer sorts from most to least played)."""
    ranked = sorted(tracks, key=lambda track: track.get("rank", 0))
    return ranked[: max(1, len(ranked) // 2)]


# ---------- Deezer -> Spotify bridge


class MatchCache:
    """Tracks already located on Spotify (by ISRC or title+artist): each one is searched only once."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._data: dict[str, dict | None] | None = None
        self._dirty = False

    def _load(self) -> dict[str, dict | None]:
        if self._data is None:
            try:
                self._data = json.loads(config.MATCH_CACHE_FILE.read_text(encoding="utf-8"))
            except (FileNotFoundError, ValueError):
                self._data = {}
        return self._data

    def get(self, key: str) -> tuple[bool, dict | None]:
        with self._lock:
            data = self._load()
            return key in data, data.get(key)

    def put(self, key: str, track: dict | None) -> None:
        slim = None
        if track:  # only what the panel uses, so the file doesn't grow for nothing
            slim = {
                "uri": track["uri"],
                "name": track["name"],
                "duration_ms": track.get("duration_ms") or 0,
                "artists": [{"name": artist["name"]} for artist in track.get("artists", [])],
                "album": {"images": (track.get("album") or {}).get("images") or []},
            }
        with self._lock:
            self._load()[key] = slim
            self._dirty = True

    def save(self) -> None:
        with self._lock:
            if not self._dirty or self._data is None:
                return
            config.DATA_DIR.mkdir(exist_ok=True)
            config.MATCH_CACHE_FILE.write_text(json.dumps(self._data), encoding="utf-8")
            self._dirty = False


matches = MatchCache()


def to_spotify(sp: Spotify, track: dict) -> dict | None:
    artist = track["artist"]["name"]
    title = track.get("title_short") or track["title"]
    key = track.get("isrc") or curation.normalize(f"{artist} {title}")
    known, cached = matches.get(key)
    if known:
        return cached
    found = None
    if track.get("isrc"):
        results = sp.search(f"isrc:{track['isrc']}", "track")
        found = results[0] if results else None
    if found is None:
        found = curation.pick_track(sp.search(f"{title} {artist}", "track"), artist, title)
    matches.put(key, found)
    return found


def find_from(track: dict, reason: str = "", bpm: float | None = None, energy: float | None = None,
              image: str | None = None, tag: str = "", released: str | None = None, fans: int | None = None) -> Find:
    return Find(
        uri=track["uri"],
        title=track["name"],
        subtitle=", ".join(artist["name"] for artist in track.get("artists", [])),
        image=image or pick_image((track.get("album") or {}).get("images"), 64),
        duration_ms=track.get("duration_ms") or 0,
        reason=reason,
        bpm=bpm,
        energy=energy,
        tag=tag,
        artists=[artist["name"] for artist in track.get("artists", [])],
        released=released,
        fans=fans,
    )


# ---------- Sensations


def gather_candidates(
    dz: Deezer, queries: list[str], rng: random.Random, blocked: Collection[str] = frozenset(),
) -> list[dict]:
    """Tracks with previews from playlists made for the moment, alternating between the sources."""
    groups, seen = [], set()
    for query in queries:
        playlists = [p for p in dz.search_playlists(query) if p.get("nb_tracks", 0) >= 10][:6]
        for playlist in rng.sample(playlists, min(PLAYLISTS_PER_SOURCE, len(playlists))):
            listed = dz.playlist_tracks(playlist["id"])
            if religious_collection(playlist.get("title", ""), listed, playlist.get("user", {}).get("name", "")):
                continue
            tracks = []
            for track in listed:
                if usable(track, blocked) and track["id"] not in seen:
                    seen.add(track["id"])
                    tracks.append(track)
            rng.shuffle(tracks)
            groups.append(tracks)
    rng.shuffle(groups)
    return curation.interleave(groups)


def within_size(
    dz: Deezer, tracks: list[dict], size: FanRange, want: int, hunt: Hunt | None = None,
) -> list[dict]:
    """The first `want` tracks by artists of the chosen size, checking fans in batches."""
    if not size.active:
        return tracks[:want]
    kept: list[dict] = []
    with ThreadPoolExecutor(max_workers=LISTEN_THREADS) as executor:
        for start in range(0, len(tracks), SIZE_BATCH):
            if hunt and hunt.cancelled:
                break
            batch = tracks[start : start + SIZE_BATCH]
            ids = list(dict.fromkeys(artist_id for track in batch if (artist_id := (track.get("artist") or {}).get("id"))))
            fans = dict(zip(ids, executor.map(lambda artist_id: fan_counts.by_id(dz, artist_id), ids)))
            kept.extend(track for track in batch if (track.get("artist") or {}).get("id") in fans
                        and size.ok(fans[track["artist"]["id"]]))
            if hunt:
                hunt.message = t("sense.checking_size", count=len(kept))
            if len(kept) >= want:
                break
    return kept[:want]


def listen(
    dz: Deezer,
    tracks: list[dict],
    cache: TempoCache,
    measure: Callable[[bytes], tempo.Analysis | None],
) -> Iterator[tuple[dict, tempo.Analysis | None]]:
    """Measures the tracks in parallel and yields them in the order they're ready."""

    def work(track: dict) -> tempo.Analysis | None:
        key = str(track["id"])
        known, analysis = cache.get(key)
        if known:
            return analysis
        try:
            analysis = measure(dz.preview(track["preview"]))
        except Exception as err:  # expired preview, odd MP3...
            log.debug("Couldn't measure %s: %s", track.get("title"), err)
            analysis = None
        cache.put(key, analysis)
        return analysis

    executor = ThreadPoolExecutor(max_workers=LISTEN_THREADS)
    futures: dict[Future, dict] = {executor.submit(work, track): track for track in tracks}
    try:
        for future in as_completed(futures):
            yield futures[future], future.result()
    finally:
        executor.shutdown(wait=False, cancel_futures=True)


def sense(
    hunt: Hunt,
    spec: dict,
    sp: Spotify,
    dz: Deezer,
    rng: random.Random,
    cache: TempoCache,
    measure: Callable[[bytes], tempo.Analysis | None] = measure_in_process,
    blocked: Collection[str] = frozenset(),
    size: FanRange = ANY_SIZE,
) -> None:
    hunt.message = t("sense.looking")
    candidates = gather_candidates(dz, spec["sources"], rng, blocked)
    if not candidates:
        hunt.message = t("sense.no_playlists", name=spec["name"])
        return
    by_consensus = spec.get("bpm") is None
    candidates = within_size(dz, candidates, size, CONSENSUS_LISTEN if by_consensus else SENSE_MAX_LISTEN, hunt)
    if hunt.cancelled:
        return
    if not candidates:
        hunt.message = t("sense.no_size", name=spec["name"])
        return
    if by_consensus:
        _sense_by_consensus(hunt, spec, sp, dz, candidates, cache, measure, blocked)
        return
    hunt.total = len(candidates)
    seen: set[str] = set()
    for track, analysis in listen(dz, candidates, cache, measure):
        if hunt.cancelled:
            return
        hunt.progress += 1
        bpm = fits(analysis, spec)
        if bpm is not None:
            _add_find(hunt, sp, track, analysis, bpm, seen, blocked)
        hunt.message = t("sense.listening", progress=hunt.progress, total=hunt.total, found=len(hunt.finds))
        if len(hunt.finds) >= SENSE_TARGET:
            break
    if hunt.finds:
        hunt.message = t("sense.done", count=len(hunt.finds), name=spec["name"], heard=hunt.progress)
    else:
        hunt.message = t("sense.none")


def _add_find(
    hunt: Hunt, sp: Spotify, track: dict, analysis: tempo.Analysis, bpm: float, seen: set[str],
    blocked: Collection[str] = frozenset(),
) -> None:
    if blocked_track(track, blocked):  # blocked while the discovery was running
        return
    match = to_spotify(sp, track)
    if not match or blocked_track(match, blocked):
        return
    key = curation.normalize(f"{match['name']} {match['artists'][0]['name']}")
    if key not in seen:
        seen.add(key)
        fans = fan_counts.known((track.get("artist") or {}).get("id"))
        hunt.finds.append(find_from(match, bpm=bpm, energy=analysis.energy, fans=fans))


def _sense_by_consensus(
    hunt: Hunt,
    spec: dict,
    sp: Spotify,
    dz: Deezer,
    candidates: list[dict],
    cache: TempoCache,
    measure: Callable[[bytes], tempo.Analysis | None],
    blocked: Collection[str] = frozenset(),
) -> None:
    """A word outside the dictionary: listen to everything first, find the shared rhythm, keep what follows it."""
    hunt.total = len(candidates)
    measured: list[tuple[dict, tempo.Analysis]] = []
    for track, analysis in listen(dz, candidates, cache, measure):
        if hunt.cancelled:
            return
        hunt.progress += 1
        if analysis is not None:
            measured.append((track, analysis))
        hunt.message = t("consensus.listening", name=spec["name"], progress=hunt.progress, total=hunt.total)
    center = consensus([analysis for _, analysis in measured])
    if center is None:
        hunt.message = t("consensus.few", name=spec["name"])
        return
    hunt.message = t("consensus.center", name=spec["name"], bpm=round(center[0]))
    ranked = sorted(
        ((distance, track, analysis) for track, analysis in measured
         if (distance := consensus_distance(analysis, center)) is not None),
        key=lambda item: item[0],
    )
    seen: set[str] = set()
    for _, track, analysis in ranked:
        if hunt.cancelled:
            return
        _add_find(hunt, sp, track, analysis, round(analysis.bpm), seen, blocked)
        if len(hunt.finds) >= SENSE_TARGET:
            break
    hunt.message = (
        t("consensus.done", count=len(hunt.finds), name=spec["name"], bpm=round(center[0]))
        if hunt.finds else t("consensus.none", name=spec["name"])
    )


# ---------- Roulette


def obscure_album_pick(
    sp: Spotify, rng: random.Random, blocked: Collection[str] = frozenset(),
    dz: Deezer | None = None, size: FanRange = ANY_SIZE,
) -> Find | None:
    year = rng.randint(1955, date.today().year)
    albums = [
        album for album in sp.search(f"tag:hipster year:{year}", "album", offset=rng.randrange(0, 90))
        if album.get("album_type") != "compilation"
    ]
    if not albums:
        return None
    album = rng.choice(albums)
    tracks = sp.album_tracks(album["id"])
    album_artists = " ".join(artist["name"] for artist in album.get("artists", []))
    if not tracks or religious_collection(album.get("name", ""), tracks, album_artists):
        return None
    secular = [track for track in tracks if not religious_track(track) and not blocked_track(track, blocked)]
    if not secular:
        return None
    fans = None
    if size.active and dz is not None:
        first_artist = (album.get("artists") or [{}])[0].get("name", "")
        fans = fan_counts.by_name(dz, first_artist) if first_artist else None
        if fans is None or not size.ok(fans):
            return None
    return find_from(
        rng.choice(secular),
        reason=t("reason.obscure_album", year=year),
        image=pick_image(album.get("images"), 64),
        tag=str(year),
        fans=fans,
    )


def world_genre_pick(
    sp: Spotify, dz: Deezer, rng: random.Random, blocked: Collection[str] = frozenset(),
    genre: str | None = None, size: FanRange = ANY_SIZE,
) -> Find | None:
    """A track from a playlist named after the genre (searching tracks would only match titles)."""
    genre = genre or rng.choice(WORLD_GENRES)
    playlists = [p for p in dz.search_playlists(genre, limit=6) if p.get("nb_tracks", 0) >= 10]
    if not playlists:
        return None
    playlist = rng.choice(playlists)
    listed = dz.playlist_tracks(playlist["id"])
    if religious_collection(playlist.get("title", ""), listed, playlist.get("user", {}).get("name", "")):
        return None
    tracks = [track for track in listed if usable(track, blocked)]
    if not tracks:
        return None
    # With no size chosen, lean toward the less popular side; with a size, the filter decides.
    pool = lesser_known(tracks) if not size.active else tracks
    rng.shuffle(pool)
    for track in pool[:6]:
        fans = fan_counts.by_id(dz, track["artist"]["id"]) if size.active else None
        if size.active and not size.ok(fans):
            continue
        match = to_spotify(sp, track)
        if match and not blocked_track(match, blocked):
            return find_from(match, reason=t("reason.genre_playlist", genre=genre), tag=genre.capitalize(), fans=fans)
    return None


def roulette(
    hunt: Hunt, sp: Spotify, dz: Deezer, rng: random.Random, count: int = ROULETTE_COUNT,
    blocked: Collection[str] = frozenset(), genre: str | None = None, size: FanRange = ANY_SIZE,
) -> None:
    hunt.total = count
    hunt.message = t("roulette.spinning")
    attempts = 0
    budget = count * (6 if genre or size.active else 4)  # filters throw away more attempts
    while len(hunt.finds) < count and attempts < budget and not hunt.cancelled:
        attempts += 1
        try:
            # With a genre, only that genre's playlists; without one, alternate with lost albums from any year.
            if genre or attempts % 2 == 0:
                find = world_genre_pick(sp, dz, rng, blocked, genre=genre, size=size)
            else:
                find = obscure_album_pick(sp, rng, blocked, dz=dz, size=size)
        except (SpotifyError, DeezerError) as err:
            if isinstance(err, SpotifyError) and err.status == 429:
                raise  # Spotify pause: insisting only makes it longer
            log.warning("Roulette: %s", err)
            continue
        blocked_now = find is not None and any(curation.normalize(name) in blocked for name in find.artists)
        if find and not blocked_now and all(find.uri != known.uri for known in hunt.finds):
            hunt.finds.append(find)
            hunt.progress = len(hunt.finds)
            hunt.message = t("roulette.progress", progress=hunt.progress, total=count)
    hunt.message = t("roulette.done", count=len(hunt.finds)) if hunt.finds else t("roulette.none")


# ---------- New releases


def genre_artists(dz: Deezer, genre: str, blocked: Collection[str] = frozenset()) -> list[dict]:
    """Artists that show up in the genre's playlists, including new-release ones."""
    artists: dict[int, dict] = {}
    for query in (f"{genre} new releases", f"{genre} lançamentos", f"new {genre}", genre):
        playlists = [p for p in dz.search_playlists(query, limit=5) if p.get("nb_tracks", 0) >= 10][:2]
        for playlist in playlists:
            listed = dz.playlist_tracks(playlist["id"])
            if religious_collection(playlist.get("title", ""), listed, playlist.get("user", {}).get("name", "")):
                continue
            for track in listed:
                artist = track.get("artist") or {}
                name = artist.get("name", "")
                if artist.get("id") and artist["id"] not in artists and name and not is_religious(name) \
                        and curation.normalize(name) not in blocked:
                    artists[artist["id"]] = artist
        if len(artists) >= NEWS_ARTIST_POOL:
            break
    return list(artists.values())[:NEWS_ARTIST_POOL]


def recent_albums(albums: list[dict], since: date) -> list[dict]:
    """Records released from 'since' onward, newest first."""
    fresh = []
    for album in albums:
        try:
            released = date.fromisoformat(album.get("release_date", ""))
        except ValueError:
            continue
        if since <= released <= date.today() and not is_religious(album.get("title", "")):
            fresh.append(album)
    return sorted(fresh, key=lambda album: album["release_date"], reverse=True)


def focus_track(album: dict, tracks: list[dict], artist_id: int | None = None) -> dict | None:
    """The track the release is named after; otherwise the artist's own first one (soundtracks have many)."""
    playable = [track for track in tracks if track.get("readable", True)]
    if artist_id is not None:
        own = [track for track in playable if (track.get("artist") or {}).get("id") == artist_id]
        playable = own or playable
    title = curation.normalize(curation.base_title(album.get("title", "")))
    named = next((t for t in playable if curation.normalize(curation.base_title(t.get("title", ""))) == title), None)
    return named or (playable[0] if playable else None)


RECORD_TYPES = ("single", "ep", "album", "compile")


def _is_edit(title: str) -> bool:
    return any(word in curation.normalize(title).split() for word in ("clean", "edit", "radio"))


def news(
    hunt: Hunt, sp: Spotify, dz: Deezer, genre: str, size: FanRange = ANY_SIZE, days: int = 30,
    blocked: Collection[str] = frozenset(),
) -> None:
    """Recent releases from the genre's artists, within the chosen size."""
    since = date.today() - timedelta(days=days)
    hunt.message = t("news.looking", genre=genre)
    artists = genre_artists(dz, genre, blocked)
    if not artists:
        hunt.message = t("news.no_artists", genre=genre)
        return
    hunt.total = len(artists)
    releases: list[tuple[dict, dict, int | None]] = []

    def inspect(artist: dict) -> tuple[dict, int | None, list[dict] | None]:
        fans = fan_counts.by_id(dz, artist["id"]) if size.active else None
        if size.active and not size.ok(fans):
            return artist, fans, None
        return artist, fans, recent_albums(dz.artist_albums(artist["id"]), since)

    # Several artists at once; the Deezer client's brake keeps the request pace.
    executor = ThreadPoolExecutor(max_workers=LISTEN_THREADS)
    futures = [executor.submit(inspect, artist) for artist in artists]
    checked = 0
    try:
        for future in as_completed(futures):
            if hunt.cancelled:
                return
            hunt.progress += 1
            artist, fans, albums = future.result()
            if albums is None:
                continue
            checked += 1
            releases.extend((album, artist, fans) for album in albums)
            hunt.message = t("news.progress", progress=hunt.progress, total=hunt.total, releases=len(releases))
            if checked >= NEWS_MAX_ARTISTS:
                break
    finally:
        executor.shutdown(wait=False, cancel_futures=True)
    if not releases:
        hunt.message = t("news.none_today" if days == 0 else "news.none", genre=genre, days=days)
        return

    hunt.message = t("news.picking")
    seen: set[tuple[int, str]] = set()
    # Newest first; on the same day, the original version before the "clean"/"edit" one.
    releases.sort(key=lambda item: (item[0]["release_date"], not _is_edit(item[0].get("title", ""))), reverse=True)
    for album, artist, fans in releases:
        if hunt.cancelled:
            return
        key = (artist["id"], curation.normalize(curation.base_title(album.get("title", ""))))
        if key in seen:  # same release in another version (clean, explicit, same-day deluxe)
            continue
        seen.add(key)
        track = focus_track(album, dz.album_tracks(album["id"]), artist["id"])
        if track is None or religious_track(track) or blocked_track(track, blocked):
            continue
        match = to_spotify(sp, track)
        if not match or blocked_track(match, blocked) or any(found.uri == match["uri"] for found in hunt.finds):
            continue
        released = date.fromisoformat(album["release_date"])
        record = album.get("record_type", "")
        kind = t(f"record.{record}" if record in RECORD_TYPES else "record.other")
        who = t("reason.who_fans", name=artist["name"], fans=i18n.number(fans)) if fans is not None else artist["name"]
        hunt.finds.append(find_from(
            match,
            reason=t("reason.release", kind=kind, who=who, date=i18n.long_date(released)),
            released=album["release_date"],
            fans=fans,
            tag=i18n.short_date(released),
        ))
        if len(hunt.finds) >= NEWS_RESULTS:
            break
    hunt.message = (
        t("news.done_today" if days == 0 else "news.done", count=len(hunt.finds), genre=genre, days=days)
        if hunt.finds else t("news.not_on_spotify")
    )


# ---------- Rabbit hole


def walk(
    dz: Deezer, seed: str, hops: int, rng: random.Random, blocked: Collection[str] = frozenset(),
    size: FanRange = ANY_SIZE,
) -> list[dict]:
    start = dz.search_artist(seed)
    if not start:
        return []
    path, visited = [start], {start["id"]}
    for _ in range(hops):
        step = next_hop(dz.related(path[-1]["id"]), visited, rng, blocked, size)
        if step is None:
            break
        path.append(step)
        visited.add(step["id"])
    return path if len(path) > 1 else []


def artist_picks(
    sp: Spotify, dz: Deezer, artist: dict, wanted: int, reason: str, taken: set[str],
    blocked: Collection[str] = frozenset(),
) -> list[Find]:
    """The artist's most-played tracks that exist on Spotify (without repeating the same song)."""
    picks: list[Find] = []
    for top in dz.top_tracks(artist["id"]):
        title = curation.normalize(curation.base_title(top.get("title", "")))
        if title and title in taken:  # the same song in another recording
            continue
        if religious_track(top):
            continue
        match = to_spotify(sp, dz.track(top["id"]))  # the "top" entry has no ISRC
        if match and match["uri"] not in taken and not religious_track(match) and not blocked_track(match, blocked):
            taken.update({title, match["uri"]})
            picks.append(find_from(match, reason=reason, fans=artist.get("nb_fan")))
        if len(picks) == wanted:
            break
    return picks


def rabbit_hole(
    hunt: Hunt,
    sp: Spotify,
    dz: Deezer,
    rng: random.Random,
    seeds: list[str],
    walks: int = RABBIT_WALKS,
    blocked: Collection[str] = frozenset(),
    size: FanRange = ANY_SIZE,
) -> None:
    """Each path becomes a trip: one track from each artist along the way and two from the last."""
    hunt.total = walks
    for index in range(walks):
        if hunt.cancelled or not seeds:
            return
        seed = rng.choice(seeds)
        hunt.message = t("rabbit.going", seed=seed)
        try:
            path = walk(dz, seed, RABBIT_HOPS, rng, blocked, size)
            finds: list[Find] = []
            taken: set[str] = set()
            steps = path[1:]
            for number, artist in enumerate(steps, start=1):
                last = number == len(steps)
                reason = (
                    t("reason.rabbit_end", hops=number, seed=seed) if last
                    else t("reason.rabbit_hop", hop=number, hops=len(steps), seed=seed)
                )
                finds.extend(artist_picks(sp, dz, artist, RABBIT_TRACKS if last else 1, reason, taken, blocked))
        except (SpotifyError, DeezerError) as err:
            if isinstance(err, SpotifyError) and err.status == 429:
                raise  # Spotify pause: insisting only makes it longer
            log.warning("Rabbit hole: %s", err)
            continue
        if finds:
            hunt.chains.append({
                "path": [{"name": artist["name"], "fans": artist.get("nb_fan")} for artist in path],
                "finds": finds,
            })
            hunt.finds.extend(finds)
        hunt.progress = index + 1
    hunt.message = (
        t("rabbit.done", chains=len(hunt.chains), count=len(hunt.finds)) if hunt.chains else t("rabbit.none")
    )
