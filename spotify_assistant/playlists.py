"""Monta o conteúdo de cada playlist do playlists.json e grava no Spotify."""
from __future__ import annotations

import logging
import random
from dataclasses import dataclass, field
from datetime import date

from . import curation
from .api import Spotify, SpotifyError
from .config import save_state

log = logging.getLogger(__name__)


@dataclass
class Built:
    spec: dict
    uris: list[str] = field(default_factory=list)
    labels: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)

    def add(self, uri: str, label: str) -> None:
        if uri not in self.uris:
            self.uris.append(uri)
            self.labels.append(label)

    def items(self) -> list[tuple[str, str]]:
        return list(zip(self.uris, self.labels))

    def shuffle(self, rng: random.Random) -> None:
        pairs = self.items()
        rng.shuffle(pairs)
        self.uris = [uri for uri, _ in pairs]
        self.labels = [label for _, label in pairs]


def build_music(sp: Spotify, spec: dict, rng: random.Random) -> Built:
    built = Built(spec)
    for entry in spec.get("tracks", []):
        artist, title = curation.parse_track_spec(entry)
        track = curation.pick_track(sp.search(f"{title} {artist}", "track"), artist, title)
        if track is None:
            track = curation.pick_track(sp.search(f"track:{title} artist:{artist}", "track"), artist, title)
        if track is None:
            built.missing.append(entry)
        else:
            built.add(track["uri"], curation.track_label(track))

    pool = spec.get("artists", {})
    for artist in pool.get("names", []):
        tracks = curation.pick_artist_tracks(sp.search(f"artist:{artist}", "track"), artist, pool.get("per_artist", 3))
        if not tracks:
            built.missing.append(f"{artist} (artista)")
        for track in tracks:
            built.add(track["uri"], curation.track_label(track))

    if spec.get("shuffle"):
        built.shuffle(rng)
    return built


def build_podcasts(sp: Spotify, spec: dict, state: dict, today: date) -> Built:
    built = Built(spec)
    cfg = spec["podcasts"]
    show_ids = state.setdefault("shows", {})
    picked: list[tuple[dict, str]] = []
    for name in cfg["shows"]:
        if name not in show_ids:
            show = curation.pick_show(sp.search(name, "show"), name)
            if show is None:
                built.missing.append(name)
                continue
            show_ids[name] = show["id"]
        try:
            episodes = sp.show_episodes(show_ids[name])
        except SpotifyError as err:
            if err.status != 404:
                raise
            del show_ids[name]  # programa saiu do catálogo; busca de novo na próxima vez
            built.missing.append(name)
            continue
        fresh = curation.recent_episodes(episodes, today, cfg.get("max_age_days", 10), cfg.get("max_per_show", 2))
        picked.extend((episode, name) for episode in fresh)

    picked.sort(key=lambda pair: pair[0]["release_date"], reverse=True)
    for episode, show_name in picked[: cfg.get("max_total", 30)]:
        built.add(episode["uri"], f"{show_name} — {episode['name']} ({episode['release_date']})")
    return built


def build_mix(spec: dict, built: dict[str, Built], rng: random.Random) -> Built:
    mix = spec["mix"]
    per_source = mix.get("per_source", 10)
    groups = []
    for source in mix["from"]:
        pairs = built[source].items()
        groups.append(rng.sample(pairs, min(per_source, len(pairs))))
    result = Built(spec)
    for uri, label in curation.interleave(groups):
        result.add(uri, label)
    return result


def run(
    sp: Spotify,
    config: dict,
    state: dict,
    *,
    weekly: bool = False,
    only: list[str] | None = None,
    dry_run: bool = False,
    today: date | None = None,
) -> None:
    today = today or date.today()
    specs = {spec["name"]: spec for spec in config["playlists"]}
    if weekly:
        targets = [spec for spec in config["playlists"] if spec.get("refresh") == "weekly"]
    elif only:
        unknown = sorted(set(only) - specs.keys())
        if unknown:
            raise SystemExit(f"Não existe no playlists.json: {', '.join(unknown)}")
        targets = [specs[name] for name in only]
    else:
        targets = config["playlists"]

    needed = {spec["name"] for spec in targets}
    for spec in targets:
        for source in spec.get("mix", {}).get("from", []):
            if source not in specs or "mix" in specs[source]:
                raise SystemExit(f'"{spec["name"]}" mistura "{source}", que não existe (ou também é uma mistura).')
            needed.add(source)

    rng = random.Random()
    built: dict[str, Built] = {}
    for spec in config["playlists"]:
        if spec["name"] in needed and "mix" not in spec:
            log.info("Montando %s...", spec["name"])
            if "podcasts" in spec:
                built[spec["name"]] = build_podcasts(sp, spec, state, today)
            else:
                built[spec["name"]] = build_music(sp, spec, rng)
    for spec in config["playlists"]:
        if spec["name"] in needed and "mix" in spec:
            built[spec["name"]] = build_mix(spec, built, rng)

    for spec in targets:
        result = built[spec["name"]]
        log.info("\n%s: %d itens", spec["name"], len(result.uris))
        if dry_run:
            for label in result.labels:
                log.info("   %s", label)
        for missing in result.missing:
            log.warning("   não encontrado: %s", missing)

    if dry_run:
        save_state(state)  # só guarda o cache de IDs dos podcasts
        log.info("\nSimulação: nada foi alterado no Spotify.")
        return

    owned = _owned_playlists(sp)
    for spec in targets:
        result = built[spec["name"]]
        if not result.uris:
            log.warning("%s ficou vazia nesta rodada; o conteúdo atual foi mantido.", spec["name"])
            continue
        playlist_id = _ensure_playlist(sp, spec, state, owned)
        sp.replace_items(playlist_id, result.uris)
        if "podcasts" in spec:
            sp.update_details(playlist_id, description=f"{spec.get('description', '')} Atualizada em {today:%d/%m/%Y}.")
        log.info("%s gravada no Spotify (%d itens).", spec["name"], len(result.uris))
    save_state(state)


def _owned_playlists(sp: Spotify) -> dict[str, str]:
    """id -> nome das playlists que pertencem ao usuário logado."""
    me = sp.me()["id"]
    return {playlist["id"]: playlist["name"] for playlist in sp.my_playlists() if playlist["owner"]["id"] == me}


def _ensure_playlist(sp: Spotify, spec: dict, state: dict, owned: dict[str, str]) -> str:
    ids = state.setdefault("playlists", {})
    name = spec["name"]
    playlist_id = ids.get(name)
    if playlist_id not in owned:  # apagada no app, ou primeira execução
        playlist_id = next((pid for pid, pname in owned.items() if pname == name), None)
    if playlist_id is None:
        playlist_id = sp.create_playlist(name, spec.get("description", ""), spec.get("public", False))["id"]
        log.info("Playlist criada: %s", name)
    ids[name] = playlist_id
    save_state(state)
    return playlist_id
