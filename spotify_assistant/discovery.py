"""Sensações e Descobrir.

- Sensações: parte de playlists que pessoas montaram para um momento (treino,
  foco...), ouve a prévia de cada faixa, mede BPM e energia e fica só com o que
  cabe na faixa daquela sensação.
- Roleta: sorteia álbuns pouco ouvidos de um ano qualquer (tag:hipster do
  Spotify) e faixas menos populares de gêneros do mundo todo (Deezer).
- Toca do coelho: parte de um artista que você já ouve e pula de relacionado
  em relacionado, sempre para os menos conhecidos.

Tudo termina no Spotify: faixas do Deezer são localizadas pelo ISRC.
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
from datetime import date
from typing import Callable, Collection, Iterator

from . import config, curation, tempo
from .api import Spotify, SpotifyError
from .deezer import Deezer, DeezerError
from .views import pick_image

SENSE_TARGET = 20
SENSE_MAX_LISTEN = 72
PLAYLISTS_PER_SOURCE = 2
ROULETTE_COUNT = 12
RABBIT_WALKS = 4
RABBIT_HOPS = 4
RABBIT_TRACKS = 2  # do último artista; dos do meio sai uma de cada
MIN_FANS = 100
LISTEN_THREADS = 6

# Buscas que trazem faixas típicas de cada gênero no Deezer. Edite à vontade.
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

# Faixas "de algoritmo" que lotam playlists de foco/relaxamento e não são música para descobrir.
JUNK_WORDS = (
    "binaural", "white noise", "brown noise", "pink noise", "rain sounds", "ruido branco",
    "asmr", "hz", "solfeggio", "sleep music", "study music", "relaxing music", "musica relaxante",
    "bpm", "workout remix", "workout music", "fitness music",
)

# Dicionário local de sentimentos para o campo livre das Sensações (sem IA paga).
# Cada entrada: radicais em português/inglês -> faixa de BPM, energia, cor e buscas extras.
# Radicais com 4+ letras casam por prefixo ("raiv" pega "raiva" e "raivoso").
FEELINGS: tuple[tuple[tuple[str, ...], dict], ...] = (
    (("odio", "odiar", "odiand", "odei", "raiv", "furi", "puto", "puta da vida", "brav", "irritad", "revolt",
      "vinganc", "rage", "angry", "hate"),
     {"bpm": [125, 185], "energy": [0.72, 1.0], "color": "#D8453B",
      "sources": ["raiva", "rage music", "metal pesado", "hardcore punk", "nu metal"]}),
    (("coracao partido", "termino", "fossa", "sofrenci", "corno", "breakup", "heartbreak"),
     {"bpm": [60, 115], "energy": [0.2, 0.8], "color": "#9C7AA8",
      "sources": ["sofrência", "fossa", "breakup songs", "músicas de término"]}),
    (("trist", "chor", "depre", "melancol", "deprimid", "sad", "luto"),
     {"bpm": [55, 100], "energy": [0.0, 0.62], "color": "#8E9AAF",
      "sources": ["músicas tristes", "sad songs", "sad piano", "sad indie"]}),
    (("saudad", "nostalg", "lembranc", "infancia", "memoria"),
     {"bpm": [60, 115], "energy": [0.0, 0.72], "color": "#C9A27E",
      "sources": ["saudade", "nostalgia", "mpb saudade", "anos 80 nostalgia"]}),
    (("solid", "sozinh", "lonely", "isolad"),
     {"bpm": [55, 100], "energy": [0.0, 0.6], "color": "#7C8BA6",
      "sources": ["solidão", "lonely songs", "sad indie"]}),
    (("amor", "apaixon", "paixao", "romant", "love", "namor", "crush"),
     {"bpm": [60, 115], "energy": [0.2, 0.78], "color": "#E3909E",
      "sources": ["músicas românticas", "love songs", "r&b romântico", "mpb romântica"]}),
    (("sexy", "sensual", "desejo", "tesao", "safad"),
     {"bpm": [65, 110], "energy": [0.3, 0.78], "color": "#C0587E",
      "sources": ["sensual", "slow jams", "r&b sensual"]}),
    (("feliz", "felicid", "alegri", "alegre", "happy", "bom humor", "good vibes", "contente"),
     {"bpm": [100, 135], "energy": [0.55, 1.0], "color": "#F2C14E",
      "sources": ["músicas felizes", "happy hits", "good vibes"]}),
    (("eufori", "hype", "empolgad", "energia", "pilhad", "animad"),
     {"bpm": [120, 150], "energy": [0.7, 1.0], "color": "#F06A4F",
      "sources": ["hype", "euforia", "edm festival", "músicas animadas"]}),
    (("confian", "poderos", "chefe", "boss", "foda", "imbativel", "marra"),
     {"bpm": [85, 145], "energy": [0.65, 1.0], "color": "#D4A84B",
      "sources": ["confiança", "boss music", "rap motivação", "músicas de vilão"]}),
    (("esperanc", "recomec", "superac", "hope"),
     {"bpm": [70, 125], "energy": [0.35, 0.88], "color": "#9FD3A8",
      "sources": ["esperança", "superação", "uplifting", "hopeful indie"]}),
    (("ansied", "ansios", "nervos", "estress", "stress", "panico", "preocupad"),
     {"bpm": [55, 90], "energy": [0.0, 0.5], "color": "#7FB7BE",
      "sources": ["calma ansiedade", "calm anxiety", "ambient calm", "piano calmo"]}),
    (("calm", "paz", "tranquil", "zen", "medit", "relax", "sereno"),
     {"bpm": [50, 88], "energy": [0.0, 0.48], "color": "#B8C4A0",
      "sources": ["paz", "meditação", "ambient peaceful", "música calma"]}),
    (("medo", "terror", "sombri", "dark", "tens", "assombr", "creepy"),
     {"bpm": [60, 130], "energy": [0.15, 0.8], "color": "#6F5E8C",
      "sources": ["dark ambient", "trilha de terror", "darkwave", "músicas sombrias"]}),
    (("sono", "dormir", "cansad", "exaust", "sleep"),
     {"bpm": [45, 78], "energy": [0.0, 0.38], "color": "#5B6C8F",
      "sources": ["dormir", "sleep piano", "ambient sleep"]}),
    (("foco", "concentr", "estud", "focus", "produtiv"),
     {"bpm": [55, 100], "energy": [0.0, 0.7], "color": "#7FB7BE",
      "sources": ["foco", "deep focus", "lofi estudar"]}),
    (("festa", "balada", "danc", "rolê", "role", "party"),
     {"bpm": [112, 132], "energy": [0.65, 1.0], "color": "#E3909E",
      "sources": ["festa", "dance hits", "balada"]}),
)
CONSENSUS_LISTEN = 48
CONSENSUS_MIN_MEASURED = 6
CONSENSUS_BPM_OCTAVES = 0.2  # ±15% em torno do pulso típico
CONSENSUS_ENERGY = 0.22

# Nada religioso, de nenhuma denominação. Palavras fortes descartam a faixa sozinhas;
# as "pistas" só contam para descartar uma playlist inteira quando aparecem em várias faixas
# (playlists chamadas "paz" ou "esperança" costumam ser gospel sem dizer no título da música).
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
    tag: str = ""  # rótulo curto (gênero ou ano) que aparece na pilha da roleta
    artists: list[str] = field(default_factory=list)  # para "não mostrar mais este artista"


@dataclass
class Hunt:
    kind: str  # sense | roulette | rabbit
    label: str
    color: str | None = None
    status: str = "running"  # running | done | error | cancelled
    message: str = ""
    progress: int = 0
    total: int = 0
    finds: list[Find] = field(default_factory=list)
    chains: list[dict] = field(default_factory=list)
    cancelled: bool = False
    spec: dict | None = None  # parâmetros da sensação (usados ao salvar como playlist)

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
        }


class TempoCache:
    """BPM/energia já medidos, por id do Deezer, para não ouvir a mesma prévia duas vezes."""

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
    """A análise é CPU pura; em processos separados ela não disputa o GIL com o servidor."""
    global _pool
    with _pool_lock:
        if _pool is None:
            _pool = ProcessPoolExecutor(max_workers=max(1, min(4, (os.cpu_count() or 2) - 1)))
    return _pool.submit(tempo.measure, mp3).result()


# ---------- Regras puras


def fit_bpm(bpm: float, low: float, high: float) -> int | None:
    """BPM dentro da faixa, aceitando metade/dobro (o erro mais comum de quem mede tempo)."""
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
) -> dict | None:
    """Entre os relacionados, sorteia no terço menos conhecido (com um mínimo de fãs)."""
    fresh = [
        artist for artist in options
        if artist["id"] not in visited and artist.get("nb_fan", 0) >= MIN_FANS
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
    """Título, artista e álbum de uma faixa do Deezer ou do Spotify."""
    artists = [track.get("artist", {}).get("name", "")] + [a.get("name", "") for a in track.get("artists", [])]
    album = track.get("album") or {}
    return (track.get("title") or track.get("name") or "", *artists, album.get("title") or album.get("name") or "")


def religious_track(track: dict) -> bool:
    return is_religious(*_track_texts(track))


def religious_collection(name: str, tracks: list[dict], owner: str = "") -> bool:
    """Playlist/álbum religioso: nome explícito, ou várias faixas com palavras e pistas religiosas."""
    if is_religious(name, owner):
        return True
    hits = sum(1 for track in tracks if _says(_track_texts(track), RELIGIOUS_WORDS + RELIGIOUS_HINTS))
    return hits >= max(2, len(tracks) // 10)


def blocked_set(names: list[str]) -> set[str]:
    """Nomes de artistas bloqueados, normalizados para comparar sem acento/maiúscula."""
    return {curation.normalize(name) for name in names if name.strip()}


def blocked_track(track: dict, blocked: Collection[str]) -> bool:
    """Faixa (do Deezer ou do Spotify) com algum artista que a pessoa pediu para não ver mais."""
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
    """Transforma o que a pessoa escreveu ("ódio", "saudade de casa") numa sensação.

    A própria frase é a primeira busca: há muita playlist batizada com sentimentos.
    Se o dicionário reconhece o sentimento, ele dá o ritmo e amplia as buscas;
    senão "bpm" fica None e o ritmo é aprendido com as músicas (ver consensus).
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
                "description": f"Músicas para {clean.lower()}.",
                "color": params["color"],
                "bpm": params["bpm"],
                "energy": params["energy"],
                "sources": [clean, *extra],
            }
    return {
        "name": label,
        "description": f"Músicas para {clean.lower()}, no ritmo que as playlists sobre isso têm em comum.",
        "color": None,
        "bpm": None,
        "energy": None,
        "sources": [clean, f"músicas {clean}", f"{clean} playlist"],
    }


def fold_bpm(bpm: float) -> float:
    """Leva o BPM para a oitava 70–140, onde metade/dobro viram o mesmo pulso."""
    while bpm < 70:
        bpm *= 2
    while bpm >= 140:
        bpm /= 2
    return bpm


def consensus(analyses: list[tempo.Analysis]) -> tuple[float, float] | None:
    """Pulso e energia típicos (medianas) de um conjunto de prévias."""
    if len(analyses) < CONSENSUS_MIN_MEASURED:
        return None
    bpms = sorted(fold_bpm(a.bpm) for a in analyses)
    energies = sorted(a.energy for a in analyses)
    middle = len(analyses) // 2
    return bpms[middle], energies[middle]


def consensus_distance(analysis: tempo.Analysis, center: tuple[float, float]) -> float | None:
    """Distância até o centro (0 = igual); None se ficou fora do padrão."""
    center_bpm, center_energy = center
    bpm_gap = abs(math.log2(fold_bpm(analysis.bpm) / center_bpm)) / CONSENSUS_BPM_OCTAVES
    energy_gap = abs(analysis.energy - center_energy) / CONSENSUS_ENERGY
    if bpm_gap > 1 or energy_gap > 1:
        return None
    return bpm_gap + energy_gap


def lesser_known(tracks: list[dict]) -> list[dict]:
    """Metade menos popular de uma busca (o Deezer ordena da mais para a menos ouvida)."""
    ranked = sorted(tracks, key=lambda track: track.get("rank", 0))
    return ranked[: max(1, len(ranked) // 2)]


# ---------- Ponte Deezer -> Spotify


class MatchCache:
    """Faixas já localizadas no Spotify (por ISRC ou título+artista): cada uma é buscada uma vez só."""

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
        if track:  # só o que o painel usa, para o arquivo não crescer à toa
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
              image: str | None = None, tag: str = "") -> Find:
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
    )


# ---------- Sensações


def gather_candidates(
    dz: Deezer, queries: list[str], rng: random.Random, blocked: Collection[str] = frozenset(),
) -> list[dict]:
    """Faixas com prévia de playlists montadas para o momento, alternando entre as fontes."""
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


def listen(
    dz: Deezer,
    tracks: list[dict],
    cache: TempoCache,
    measure: Callable[[bytes], tempo.Analysis | None],
) -> Iterator[tuple[dict, tempo.Analysis | None]]:
    """Mede as faixas em paralelo e entrega na ordem em que ficam prontas."""

    def work(track: dict) -> tempo.Analysis | None:
        key = str(track["id"])
        known, analysis = cache.get(key)
        if known:
            return analysis
        try:
            analysis = measure(dz.preview(track["preview"]))
        except Exception as err:  # prévia expirada, MP3 estranho...
            log.debug("Não deu para medir %s: %s", track.get("title"), err)
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
) -> None:
    hunt.message = "Procurando playlists feitas para esse momento…"
    candidates = gather_candidates(dz, spec["sources"], rng, blocked)
    if not candidates:
        hunt.message = f"Não achei playlists sobre “{spec['name']}”. Tente outra palavra."
        return
    if spec.get("bpm") is None:
        _sense_by_consensus(hunt, spec, sp, dz, candidates[:CONSENSUS_LISTEN], cache, measure, blocked)
        return
    candidates = candidates[:SENSE_MAX_LISTEN]
    hunt.total = len(candidates)
    seen: set[str] = set()
    for track, analysis in listen(dz, candidates, cache, measure):
        if hunt.cancelled:
            return
        hunt.progress += 1
        bpm = fits(analysis, spec)
        if bpm is not None:
            _add_find(hunt, sp, track, analysis, bpm, seen, blocked)
        hunt.message = f"Ouvindo prévias: {hunt.progress} de {hunt.total}. {len(hunt.finds)} no ritmo certo."
        if len(hunt.finds) >= SENSE_TARGET:
            break
    if hunt.finds:
        hunt.message = f"{len(hunt.finds)} músicas no ritmo de “{spec['name']}”, de {hunt.progress} prévias ouvidas."
    else:
        hunt.message = "Nenhuma prévia ficou no ritmo desta vez. Gere de novo para ouvir outras."


def _add_find(
    hunt: Hunt, sp: Spotify, track: dict, analysis: tempo.Analysis, bpm: float, seen: set[str],
    blocked: Collection[str] = frozenset(),
) -> None:
    if blocked_track(track, blocked):  # bloqueado no meio da busca
        return
    match = to_spotify(sp, track)
    if not match or blocked_track(match, blocked):
        return
    key = curation.normalize(f"{match['name']} {match['artists'][0]['name']}")
    if key not in seen:
        seen.add(key)
        hunt.finds.append(find_from(match, bpm=bpm, energy=analysis.energy))


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
    """Palavra fora do dicionário: ouve tudo primeiro, descobre o ritmo em comum e fica com quem segue ele."""
    hunt.total = len(candidates)
    measured: list[tuple[dict, tempo.Analysis]] = []
    for track, analysis in listen(dz, candidates, cache, measure):
        if hunt.cancelled:
            return
        hunt.progress += 1
        if analysis is not None:
            measured.append((track, analysis))
        hunt.message = f"Ouvindo para entender o ritmo de “{spec['name']}”: {hunt.progress} de {hunt.total}."
    center = consensus([analysis for _, analysis in measured])
    if center is None:
        hunt.message = f"Poucas músicas para entender “{spec['name']}”. Tente outra palavra."
        return
    hunt.message = f"O ritmo de “{spec['name']}” fica perto de {round(center[0])} BPM. Separando as músicas…"
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
        f"{len(hunt.finds)} músicas no ritmo de “{spec['name']}”, perto de {round(center[0])} BPM."
        if hunt.finds else f"As músicas sobre “{spec['name']}” não têm um ritmo em comum. Tente outra palavra."
    )


# ---------- Roleta


def obscure_album_pick(sp: Spotify, rng: random.Random, blocked: Collection[str] = frozenset()) -> Find | None:
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
    return find_from(
        rng.choice(secular),
        reason=f"Sorteada de um álbum de {year} que quase ninguém ouve.",
        image=pick_image(album.get("images"), 64),
        tag=str(year),
    )


def world_genre_pick(
    sp: Spotify, dz: Deezer, rng: random.Random, blocked: Collection[str] = frozenset(),
) -> Find | None:
    """Faixa pouco popular de uma playlist com o nome do gênero (buscar faixas casaria só o título)."""
    genre = rng.choice(WORLD_GENRES)
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
    match = to_spotify(sp, rng.choice(lesser_known(tracks)))
    if not match or blocked_track(match, blocked):
        return None
    return find_from(match, reason=f"Sorteada de uma playlist de {genre}.", tag=genre.capitalize())


def roulette(
    hunt: Hunt, sp: Spotify, dz: Deezer, rng: random.Random, count: int = ROULETTE_COUNT,
    blocked: Collection[str] = frozenset(),
) -> None:
    hunt.total = count
    hunt.message = "Girando a roleta…"
    attempts = 0
    while len(hunt.finds) < count and attempts < count * 4 and not hunt.cancelled:
        attempts += 1
        try:
            find = obscure_album_pick(sp, rng, blocked) if attempts % 2 else world_genre_pick(sp, dz, rng, blocked)
        except (SpotifyError, DeezerError) as err:
            if isinstance(err, SpotifyError) and err.status == 429:
                raise  # pausa da Spotify: insistir só aumenta o castigo
            log.warning("Roleta: %s", err)
            continue
        blocked_now = find is not None and any(curation.normalize(name) in blocked for name in find.artists)
        if find and not blocked_now and all(find.uri != known.uri for known in hunt.finds):
            hunt.finds.append(find)
            hunt.progress = len(hunt.finds)
            hunt.message = f"Sorteadas {hunt.progress} de {count}."
    hunt.message = f"{len(hunt.finds)} músicas sorteadas." if hunt.finds else "A roleta não achou nada desta vez. Gire de novo."


# ---------- Toca do coelho


def walk(
    dz: Deezer, seed: str, hops: int, rng: random.Random, blocked: Collection[str] = frozenset(),
) -> list[dict]:
    start = dz.search_artist(seed)
    if not start:
        return []
    path, visited = [start], {start["id"]}
    for _ in range(hops):
        step = next_hop(dz.related(path[-1]["id"]), visited, rng, blocked)
        if step is None:
            break
        path.append(step)
        visited.add(step["id"])
    return path if len(path) > 1 else []


def artist_picks(
    sp: Spotify, dz: Deezer, artist: dict, wanted: int, reason: str, taken: set[str],
    blocked: Collection[str] = frozenset(),
) -> list[Find]:
    """As faixas mais ouvidas do artista que existem no Spotify (sem repetir a mesma música)."""
    picks: list[Find] = []
    for top in dz.top_tracks(artist["id"]):
        title = curation.normalize(curation.base_title(top.get("title", "")))
        if title and title in taken:  # a mesma música em outra gravação
            continue
        if religious_track(top):
            continue
        match = to_spotify(sp, dz.track(top["id"]))  # o "top" não traz ISRC
        if match and match["uri"] not in taken and not religious_track(match) and not blocked_track(match, blocked):
            taken.update({title, match["uri"]})
            picks.append(find_from(match, reason=reason))
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
) -> None:
    """Cada caminho vira uma viagem: uma faixa de cada artista no meio e duas do último."""
    hunt.total = walks
    for index in range(walks):
        if hunt.cancelled or not seeds:
            return
        seed = rng.choice(seeds)
        hunt.message = f"Descendo a toca a partir de {seed}…"
        try:
            path = walk(dz, seed, RABBIT_HOPS, rng, blocked)
            finds: list[Find] = []
            taken: set[str] = set()
            steps = path[1:]
            for number, artist in enumerate(steps, start=1):
                last = number == len(steps)
                reason = (
                    f"Fim da toca: {number} pulos a partir de {seed}." if last
                    else f"Pulo {number} de {len(steps)} a partir de {seed}."
                )
                finds.extend(artist_picks(sp, dz, artist, RABBIT_TRACKS if last else 1, reason, taken, blocked))
        except (SpotifyError, DeezerError) as err:
            if isinstance(err, SpotifyError) and err.status == 429:
                raise  # pausa da Spotify: insistir só aumenta o castigo
            log.warning("Toca do coelho: %s", err)
            continue
        if finds:
            hunt.chains.append({
                "path": [{"name": artist["name"], "fans": artist.get("nb_fan")} for artist in path],
                "finds": finds,
            })
            hunt.finds.extend(finds)
        hunt.progress = index + 1
    hunt.message = (
        f"{len(hunt.chains)} caminhos, {len(hunt.finds)} músicas do conhecido ao desconhecido." if hunt.chains
        else "A toca não levou a lugar nenhum desta vez. Tente de novo ou escolha outro artista."
    )
