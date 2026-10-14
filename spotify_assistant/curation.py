"""Regras puras de escolha: casa o que está no playlists.json com resultados do catálogo."""
from __future__ import annotations

import re
import unicodedata
from datetime import date, timedelta
from typing import TypeVar

T = TypeVar("T")

STOPWORDS = {"the", "an", "of", "in", "on", "and", "to", "de", "la", "le", "du", "des"}
# Versões que nunca queremos numa playlist "refinada" (a não ser que o título peça).
UNWANTED = (
    "karaoke", "lullaby", "8 bit", "music box", "tribute", "cover", "remix",
    "sped up", "slowed", "lofi", "lo fi", "ninar",
)
MIN_TITLE_OVERLAP = 0.6
UNWANTED_PENALTY = 10


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def tokens(text: str) -> list[str]:
    return [t for t in normalize(text).split() if t not in STOPWORDS]


def base_title(name: str) -> str:
    """'So What - Remastered 2005 (Live)' -> 'So What'."""
    return re.sub(r"\s*[\(\[].*?[\)\]]", "", name).split(" - ")[0]


def title_overlap(wanted: str, candidate: str) -> float:
    """Fração das palavras pedidas presentes no título encontrado.

    Palavras com 3+ letras casam por prefixo ('prelude' ~ 'preludes');
    números e palavras curtas precisam ser iguais ('1' não casa com '18').
    """
    want, have = tokens(wanted), tokens(candidate)
    if not want:
        return 0.0
    hits = sum(1 for w in want if any(h == w or (len(w) > 2 and h.startswith(w)) for h in have))
    return hits / len(want)


def artist_matches(wanted: str, artists: list[dict]) -> bool:
    want = f" {normalize(wanted)} "
    return any(want in f" {normalize(artist['name'])} " for artist in artists)


def parse_track_spec(spec: str) -> tuple[str, str]:
    artist, sep, title = spec.partition(" - ")
    if not sep:
        raise SystemExit(f'Faixa fora do formato "Artista - Título" no playlists.json: {spec!r}')
    return artist.strip(), title.strip()


def unwanted_hits(track: dict, wanted_title: str) -> int:
    haystack = f" {normalize(track['name'] + ' ' + track.get('album', {}).get('name', ''))} "
    wanted = normalize(wanted_title)
    return sum(1 for word in UNWANTED if f" {word} " in haystack and word not in wanted)


def pick_track(candidates: list[dict], artist: str, title: str) -> dict | None:
    best, best_score = None, 0.0
    for track in candidates:
        if not artist_matches(artist, track["artists"]):
            continue
        overlap = title_overlap(title, track["name"])
        if overlap < MIN_TITLE_OVERLAP:
            continue
        score = overlap * 10 - UNWANTED_PENALTY * unwanted_hits(track, title)
        if normalize(base_title(track["name"])) == normalize(title):
            score += 3
        if score > best_score:  # empate: fica o primeiro (mais relevante na busca)
            best, best_score = track, score
    return best


def pick_artist_tracks(candidates: list[dict], artist: str, limit: int) -> list[dict]:
    picked, seen = [], set()
    for track in candidates:
        if not artist_matches(artist, track["artists"]):
            continue
        key = normalize(base_title(track["name"]))
        if key in seen:
            continue
        seen.add(key)
        picked.append(track)
        if len(picked) == limit:
            break
    return picked


def pick_show(candidates: list[dict], wanted: str) -> dict | None:
    for show in candidates:
        languages = show.get("languages") or []
        in_portuguese = not languages or any(lang.lower().startswith("pt") for lang in languages)
        if in_portuguese and title_overlap(wanted, show["name"]) == 1.0:
            return show
    return None


def recent_episodes(episodes: list[dict], today: date, max_age_days: int, max_per_show: int) -> list[dict]:
    cutoff = today - timedelta(days=max_age_days)
    fresh = [
        episode for episode in episodes
        if episode.get("is_playable", True)
        and episode.get("release_date_precision") == "day"
        and date.fromisoformat(episode["release_date"]) >= cutoff
    ]
    fresh.sort(key=lambda episode: episode["release_date"], reverse=True)
    return fresh[:max_per_show]


def interleave(groups: list[list[T]]) -> list[T]:
    """[[a1, a2], [b1], [c1, c2]] -> [a1, b1, c1, a2, c2]"""
    longest = max((len(group) for group in groups), default=0)
    return [group[i] for i in range(longest) for group in groups if i < len(group)]


def track_label(track: dict) -> str:
    artists = ", ".join(artist["name"] for artist in track["artists"][:2])
    return f"{artists} — {track['name']}"
