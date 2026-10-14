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
import os
import random
import threading
from concurrent.futures import Future, ProcessPoolExecutor, ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Callable, Iterator

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
RABBIT_TRACKS = 2
MIN_FANS = 100
LISTEN_THREADS = 6

# Buscas que trazem faixas típicas de cada gênero no Deezer. Edite à vontade.
WORLD_GENRES = (
    "zamrock", "ethio jazz", "afrobeat", "highlife", "city pop", "enka", "rebetiko", "fado",
    "chamamé", "cumbia psicodélica", "chicha peruana", "tropicália", "baião", "frevo", "carimbó",
    "lambada", "kizomba", "semba", "mbalax", "soukous", "gnawa", "raï", "qawwali", "dangdut",
    "kroncong", "j-jazz", "shibuya-kei", "anatolian rock", "arabesk", "klezmer", "balkan brass",
    "tango nuevo", "chacarera", "son cubano", "bolero", "mambo", "salsa dura", "calypso", "soca",
    "rocksteady", "dub", "lovers rock", "zydeco", "bluegrass", "delta blues", "doo-wop",
    "northern soul", "yacht rock", "krautrock", "italo disco", "chanson", "yé-yé", "schlager",
    "joik", "sea shanty", "irish trad", "flamenco", "rumba catalana", "huayno", "forró pé de serra",
    "samba rock", "choro", "maracatu", "brega", "tecnobrega", "manguebeat", "sertanejo raiz",
    "jovem guarda", "exotica", "space age pop", "library music", "vaporwave", "shoegaze",
    "dream pop", "math rock", "post-rock", "midwest emo", "trip hop", "jungle", "uk garage",
    "footwork", "amapiano", "gqom", "kuduro", "grime", "zouk", "gamelan", "throat singing",
    "carnatic", "hawaiian slack key", "bossa nova japonesa", "turkish psych", "persian pop",
)

# Faixas "de algoritmo" que lotam playlists de foco/relaxamento e não são música para descobrir.
JUNK_WORDS = (
    "binaural", "white noise", "brown noise", "pink noise", "rain sounds", "ruido branco",
    "asmr", "hz", "solfeggio", "sleep music", "study music", "relaxing music", "musica relaxante",
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


def next_hop(options: list[dict], visited: set, rng: random.Random) -> dict | None:
    """Entre os relacionados, sorteia no terço menos conhecido (com um mínimo de fãs)."""
    fresh = [artist for artist in options if artist["id"] not in visited and artist.get("nb_fan", 0) >= MIN_FANS]
    if not fresh:
        return None
    fresh.sort(key=lambda artist: artist.get("nb_fan", 0))
    return rng.choice(fresh[: max(1, len(fresh) // 3)])


def is_junk(track: dict) -> bool:
    text = f" {curation.normalize(track.get('title', '') + ' ' + track.get('artist', {}).get('name', ''))} "
    return any(f" {word} " in text for word in JUNK_WORDS)


def usable(track: dict) -> bool:
    return bool(track.get("preview")) and track.get("readable", True) and not is_junk(track)


def lesser_known(tracks: list[dict]) -> list[dict]:
    """Metade menos popular de uma busca (o Deezer ordena da mais para a menos ouvida)."""
    ranked = sorted(tracks, key=lambda track: track.get("rank", 0))
    return ranked[: max(1, len(ranked) // 2)]


# ---------- Ponte Deezer -> Spotify


def to_spotify(sp: Spotify, track: dict) -> dict | None:
    isrc = track.get("isrc")
    if isrc:
        found = sp.search(f"isrc:{isrc}", "track")
        if found:
            return found[0]
    artist = track["artist"]["name"]
    title = track.get("title_short") or track["title"]
    return curation.pick_track(sp.search(f"{title} {artist}", "track"), artist, title)


def find_from(track: dict, reason: str = "", bpm: float | None = None, energy: float | None = None,
              image: str | None = None) -> Find:
    return Find(
        uri=track["uri"],
        title=track["name"],
        subtitle=", ".join(artist["name"] for artist in track.get("artists", [])),
        image=image or pick_image((track.get("album") or {}).get("images"), 64),
        duration_ms=track.get("duration_ms") or 0,
        reason=reason,
        bpm=bpm,
        energy=energy,
    )


# ---------- Sensações


def gather_candidates(dz: Deezer, queries: list[str], rng: random.Random) -> list[dict]:
    """Faixas com prévia de playlists montadas para o momento, alternando entre as fontes."""
    groups, seen = [], set()
    for query in queries:
        playlists = [p for p in dz.search_playlists(query) if p.get("nb_tracks", 0) >= 10][:6]
        for playlist in rng.sample(playlists, min(PLAYLISTS_PER_SOURCE, len(playlists))):
            tracks = []
            for track in dz.playlist_tracks(playlist["id"]):
                if usable(track) and track["id"] not in seen:
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
) -> None:
    hunt.message = "Procurando playlists feitas para esse momento…"
    candidates = gather_candidates(dz, spec["sources"], rng)[:SENSE_MAX_LISTEN]
    hunt.total = len(candidates)
    seen = set()
    for track, analysis in listen(dz, candidates, cache, measure):
        if hunt.cancelled:
            return
        hunt.progress += 1
        bpm = fits(analysis, spec)
        if bpm is not None:
            match = to_spotify(sp, track)
            key = match and curation.normalize(f"{match['name']} {match['artists'][0]['name']}")
            if match and key not in seen:
                seen.add(key)
                hunt.finds.append(find_from(match, reason=spec["name"], bpm=bpm, energy=analysis.energy))
        hunt.message = f"Ouvindo prévias: {hunt.progress} de {hunt.total}. {len(hunt.finds)} no ritmo certo."
        if len(hunt.finds) >= SENSE_TARGET:
            break
    if hunt.finds:
        hunt.message = f"{len(hunt.finds)} músicas no ritmo de {spec['name'].lower()}, de {hunt.progress} prévias ouvidas."
    else:
        hunt.message = "Nenhuma prévia ficou no ritmo desta vez. Gere de novo para ouvir outras."


# ---------- Roleta


def obscure_album_pick(sp: Spotify, rng: random.Random) -> Find | None:
    year = rng.randint(1955, date.today().year)
    albums = [
        album for album in sp.search(f"tag:hipster year:{year}", "album", offset=rng.randrange(0, 90))
        if album.get("album_type") != "compilation"
    ]
    if not albums:
        return None
    album = rng.choice(albums)
    tracks = sp.album_tracks(album["id"])
    if not tracks:
        return None
    return find_from(
        rng.choice(tracks),
        reason=f"Álbum pouco ouvido de {year}",
        image=pick_image(album.get("images"), 64),
    )


def world_genre_pick(sp: Spotify, dz: Deezer, rng: random.Random) -> Find | None:
    """Faixa pouco popular de uma playlist com o nome do gênero (buscar faixas casaria só o título)."""
    genre = rng.choice(WORLD_GENRES)
    playlists = [p for p in dz.search_playlists(genre, limit=6) if p.get("nb_tracks", 0) >= 10]
    if not playlists:
        return None
    tracks = [track for track in dz.playlist_tracks(rng.choice(playlists)["id"]) if usable(track)]
    if not tracks:
        return None
    match = to_spotify(sp, rng.choice(lesser_known(tracks)))
    return find_from(match, reason=genre.capitalize()) if match else None


def roulette(hunt: Hunt, sp: Spotify, dz: Deezer, rng: random.Random, count: int = ROULETTE_COUNT) -> None:
    hunt.total = count
    hunt.message = "Girando a roleta…"
    attempts = 0
    while len(hunt.finds) < count and attempts < count * 4 and not hunt.cancelled:
        attempts += 1
        try:
            find = obscure_album_pick(sp, rng) if attempts % 2 else world_genre_pick(sp, dz, rng)
        except (SpotifyError, DeezerError) as err:
            log.warning("Roleta: %s", err)
            continue
        if find and all(find.uri != known.uri for known in hunt.finds):
            hunt.finds.append(find)
            hunt.progress = len(hunt.finds)
            hunt.message = f"Sorteadas {hunt.progress} de {count}."
    hunt.message = f"{len(hunt.finds)} músicas sorteadas." if hunt.finds else "A roleta não achou nada desta vez. Gire de novo."


# ---------- Toca do coelho


def walk(dz: Deezer, seed: str, hops: int, rng: random.Random) -> list[dict]:
    start = dz.search_artist(seed)
    if not start:
        return []
    path, visited = [start], {start["id"]}
    for _ in range(hops):
        step = next_hop(dz.related(path[-1]["id"]), visited, rng)
        if step is None:
            break
        path.append(step)
        visited.add(step["id"])
    return path if len(path) > 1 else []


def rabbit_hole(
    hunt: Hunt,
    sp: Spotify,
    dz: Deezer,
    rng: random.Random,
    seeds: list[str],
    walks: int = RABBIT_WALKS,
) -> None:
    hunt.total = walks
    for index in range(walks):
        if hunt.cancelled or not seeds:
            return
        seed = rng.choice(seeds)
        hunt.message = f"Descendo a toca a partir de {seed}…"
        try:
            path = walk(dz, seed, RABBIT_HOPS, rng)
            finds, titles = [], set()
            if path:
                for top in dz.top_tracks(path[-1]["id"]):
                    title = curation.normalize(curation.base_title(top.get("title", "")))
                    if title and title in titles:  # a mesma música em outra gravação
                        continue
                    match = to_spotify(sp, dz.track(top["id"]))  # o "top" não traz ISRC
                    if match:
                        titles.add(title)
                        finds.append(find_from(match, reason=f"A partir de {seed}"))
                    if len(finds) == RABBIT_TRACKS:
                        break
        except (SpotifyError, DeezerError) as err:
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
        f"{len(hunt.chains)} artistas encontrados longe do óbvio." if hunt.chains
        else "A toca não levou a lugar nenhum desta vez. Tente de novo ou escolha outro artista."
    )
