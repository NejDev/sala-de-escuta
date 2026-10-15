"""Achievements: monthly titles and hidden medals among the people who take part (opt-in inside Friends).

data/users/<id>/achievements.json keeps a person's medals, what they've seen and highlighted, and the running numbers
behind the medals; data/achievements.json keeps the closed months. Everything is worked out in the loop that collects
plays (dashboard.collector), from plays.json plus Last.fm listeners and artist fans looked up and cached in the
background; panel actions arrive through note(). Opening the tab never asks anyone outside.

Privacy: only participants see anything. A medal nobody earned never leaves this module, and its "how" line only
reaches whoever earned it. Erasing removes the person's file and their name from closed months.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from collections import Counter
from pathlib import Path

from . import accounts, config, curation, favorites, medal_rules, reviews, social
from .i18n import t
from .lastfm import ListenerCounts
from .medal_rules import Context, first_artist
from .medals import BY_ID, GAMES_BY_SLUG, MEDALS, Medal

MAX_HIGHLIGHTS = 10

log = logging.getLogger(__name__)
_lock = threading.RLock()


class Unreadable(Exception):
    """An achievements file exists but can't be read: it's left as it is."""


# ---------- files


def _file(user_id: str) -> Path:
    return config.user_paths(user_id).dir / "achievements.json"


def _room_file() -> Path:
    return config.DATA_DIR / "achievements.json"


def _empty() -> dict:
    return {"on": False, "joined": None, "earned": {}, "seen": {}, "highlights": [], "stats": medal_rules.new_stats(),
            "through": 0, "rich_through": 0}


def load(user_id: str) -> dict:
    try:
        data = json.loads(_file(user_id).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return _empty()
    except ValueError as err:
        raise Unreadable(f"{user_id}: {err}") from err
    if not isinstance(data, dict):
        raise Unreadable(f"{user_id}: not an object")
    full = {**_empty(), **data}
    full["stats"] = {**medal_rules.new_stats(), **full["stats"]}  # numbers added in later versions start empty
    return full


def _write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix(".tmp")
    partial.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    partial.replace(path)  # a crash midway never leaves half a file


def _read_room() -> dict:
    try:
        room = json.loads(_room_file().read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"months": {}}
    except ValueError as err:
        raise Unreadable(f"room: {err}") from err
    if not isinstance(room, dict):
        raise Unreadable("room: not an object")
    room.setdefault("months", {})
    return room


# ---------- who takes part


def taking_part(user_id: str) -> bool:
    try:
        on = bool(load(user_id)["on"])
    except Unreadable:
        return False
    return on and social.sharing(user_id) and social.allowed(user_id)


def participants() -> list[str]:
    return [user_id for user_id in config.list_users() if taking_part(user_id)]


def set_on(user_id: str, on: bool, now: float | None = None) -> None:
    """Turning on the first time counts the history Friends already has; coming back skips the time away."""
    now = time.time() if now is None else now
    with _lock:
        data = load(user_id)
        if on and not data["on"]:
            if data["joined"] is not None:
                data["through"] = data["rich_through"] = now
            data["joined"] = data["joined"] or now
        data["on"] = on
        _write(_file(user_id), data)


def forget(user_id: str) -> None:
    """Erases the person's achievements and their name from closed months."""
    with _lock:
        _file(user_id).unlink(missing_ok=True)
        try:
            room = _read_room()
        except Unreadable as err:
            log.warning("Achievements: couldn't remove %s from past months: %s", user_id, err)
            return
        changed = False
        for titles in room["months"].values():
            for title in list(titles):
                users = [uid for uid in titles[title]["users"] if uid != user_id]
                if users != titles[title]["users"]:
                    changed = True
                    if users:
                        titles[title]["users"] = users
                    else:
                        del titles[title]
        if changed:
            _write(_room_file(), room)


# ---------- the catalog as this room sees it


def available(lastfm: bool) -> list[Medal]:
    """The medals this room can earn (Last.fm ones only with a key)."""
    return [medal for medal in MEDALS if lastfm or medal.requires != "lastfm"]


def medal_texts(medal_id: str) -> tuple[str, str]:
    """(name, how) in the current language; a game medal is named after its game."""
    medal = BY_ID[medal_id]
    if medal.rule == "game":
        name = GAMES_BY_SLUG[medal.params["game"]].name
        return name, t("medal.game.how", game=name)
    return t(f"medal.{medal_id}"), t(f"medal.{medal_id}.how")


def _artist_name(play: dict) -> str:
    """The first credited artist, or "" when the credit has no letters or digits (nothing to look up)."""
    name = first_artist(play).get("name", "")
    return name if any(char.isalnum() for char in name) else ""


def context(user_id: str, counts: ListenerCounts | None, fans) -> Context:
    """What the person's medals look at besides plays. `fans` answers cached(name) (ArtistFans)."""
    first = curation.normalize(accounts.display_name(user_id)).split()
    made = {f"spotify:playlist:{fav['playlist_id']}" for fav in favorites.load(user_id) if fav.get("playlist_id")}

    def listeners(play: dict):
        name = _artist_name(play)
        return counts.cached(name, play["title"]) if counts is not None and name else None

    def artist_fans(play: dict):
        name = _artist_name(play)
        return fans.cached(name) if fans is not None and name else None

    return Context(first_name=first[0] if first else "",
                   finds=frozenset(find["uri"] for find in favorites.recent(user_id) if find.get("uri")),
                   playlists=frozenset(made), listeners=listeners, fans=artist_fans)


# ---------- earning


def _song(play: dict) -> dict:
    artists = play.get("artists") or []
    return {"uri": play["uri"], "title": play["title"], "artist": artists[0]["name"] if artists else "",
            "image": play.get("image")}


def _pending(data: dict, phase: str, lastfm: bool) -> list[Medal]:
    return [medal for medal in available(lastfm) if medal.phase == phase and medal.id not in data["earned"]]


def _award_due(data: dict, pending: list[Medal], play: dict | None, ctx: Context, at: float) -> list[str]:
    new = []
    for medal in list(pending):
        if not medal_rules.check(medal, data["stats"], play, ctx):
            continue
        got = {"at": at, "song": _song(play) if medal.song and play else None}
        if medal.requires == "lastfm" and play:
            heard = ctx.listeners(play)
            if heard is not None and heard.count is not None:
                got["lastfm"] = {"listeners": heard.count, "url": heard.url}
        data["earned"][medal.id] = got
        pending.remove(medal)
        new.append(medal.id)
    return new


def process(user_id: str, plays: list[dict], ctx: Context, lastfm: bool) -> list[str]:
    """New plays (after the last one processed) into the person's numbers and "play" medals. Returns what was earned."""
    with _lock:
        data = load(user_id)
        if not data["on"]:
            return []
        fresh = sorted((item for item in plays if item["at"] > data["through"]), key=lambda item: item["at"])
        if not fresh:
            return []
        pending = _pending(data, "play", lastfm)
        new = []
        for item in fresh:
            medal_rules.update(data["stats"], item, ctx)
            new += _award_due(data, pending, item, ctx, item["at"])
        data["through"] = fresh[-1]["at"]
        _write(_file(user_id), data)
        return new


def note(user_id: str, event: str, lastfm: bool = False, **detail) -> list[str]:
    """Something done in the panel: counted only for participants, and medals are awarded right away."""
    if not taking_part(user_id):
        return []
    with _lock:
        try:
            data = load(user_id)
        except Unreadable:
            return []
        stats = data["stats"]
        events = stats["events"]

        def bump(name: str) -> None:
            events[name] = events.get(name, 0) + 1

        if event == "hunt":
            kind = detail.get("kind")
            if kind:
                bump(kind)
            if kind in ("roulette", "sense", "rabbit", "news"):
                stats["kinds"][kind] = 1
            if detail.get("rare"):
                bump("roulette_rare")
            if detail.get("text"):
                bump("sense_text")
            if detail.get("listeners") is not None and detail["listeners"] <= 50:
                bump("listeners_tight")
        elif event == "playlist":
            bump("playlist")
            if detail.get("uri"):
                stats["made"][detail["uri"]] = 1
        elif event in ("favorite", "block"):
            bump(event)
        elif event == "review":
            mine = list(reviews.mine(user_id).values())
            events["reviews"] = len(mine)
            events["review_five"] = int(any(review.get("rating") == 5 for review in mine))
            events["review_long"] = int(any(review.get("public") and len(review.get("text") or "") >= 500
                                             for review in mine))
        new = _award_due(data, _pending(data, "event", lastfm), None, Context(), time.time())
        _write(_file(user_id), data)
        return new


# ---------- what people see


def mark_seen(user_id: str, ids: list[str]) -> None:
    with _lock:
        data = load(user_id)
        data["seen"].update({medal_id: 1 for medal_id in ids if medal_id in data["earned"]})
        _write(_file(user_id), data)


def set_highlights(user_id: str, ids: list[str]) -> None:
    """Up to 10 earned medals, in the order given; anything else is dropped."""
    with _lock:
        data = load(user_id)
        data["highlights"] = [medal_id for medal_id in dict.fromkeys(ids) if medal_id in data["earned"]][:MAX_HIGHLIGHTS]
        _write(_file(user_id), data)


def summary(user_id: str, lastfm: bool) -> dict:
    """For the tab's dot: whether the person takes part and how many medals they haven't opened yet."""
    if not taking_part(user_id):
        return {"on": False, "new": 0}
    data = load(user_id)
    ids = {medal.id for medal in available(lastfm)}
    return {"on": True, "new": len([medal_id for medal_id in data["earned"] if medal_id in ids and medal_id not in data["seen"]])}


def highlights_of(user_id: str, lastfm: bool) -> list[dict]:
    """A participant's highlighted medals (names only), for their card in Friends."""
    if not taking_part(user_id):
        return []
    data = load(user_id)
    ids = {medal.id for medal in available(lastfm)}
    return [{"id": medal_id, "name": medal_texts(medal_id)[0]}
            for medal_id in data["highlights"] if medal_id in data["earned"] and medal_id in ids]


def _medal_view(medal_id: str, got: dict, holders: int, own: bool) -> dict:
    name, how = medal_texts(medal_id)
    shown = {"id": medal_id, "name": name, "at": got["at"], "song": got.get("song"), "lastfm": got.get("lastfm"),
             "holders": holders}
    if own:
        shown["how"] = how  # only whoever earned it learns how
    return shown


def view(viewer: str, lastfm: bool, fans, now: float | None = None) -> dict:
    """What the tab shows `viewer`. Only participants (on, sharing and allowed in Friends) get more than the switch.
    `fans(name)` gives cached artist fans (the month's race needs them)."""
    now = time.time() if now is None else now
    mine = load(viewer)
    sharing = social.sharing(viewer)
    if not (mine["on"] and sharing and social.allowed(viewer)):
        return {"sharing": sharing, "on": False}
    datas = {}
    for user_id in participants():
        try:
            datas[user_id] = load(user_id)
        except Unreadable:
            continue
    ids = {medal.id for medal in available(lastfm)}
    holders = Counter(medal_id for data in datas.values() for medal_id in data["earned"] if medal_id in ids)

    def person(user_id: str, own: bool) -> dict:
        earned = sorted(((medal_id, got) for medal_id, got in datas[user_id]["earned"].items() if medal_id in ids),
                        key=lambda pair: pair[1]["at"], reverse=True)
        medals = [_medal_view(medal_id, got, holders[medal_id], own) for medal_id, got in earned]
        by_id = {medal["id"]: medal for medal in medals}
        return {"id": user_id, "name": accounts.display_name(user_id), "count": len(medals),
                "highlights": [by_id[medal_id] for medal_id in datas[user_id]["highlights"] if medal_id in by_id],
                "medals": medals}

    fresh = sorted((got["at"], medal_id) for medal_id, got in mine["earned"].items()
                   if medal_id in ids and medal_id not in mine["seen"])
    return {
        "sharing": True, "on": True, "total": len(ids), "participants": len(datas), "lastfm": lastfm,
        "me": person(viewer, True),
        "new": [medal_id for _, medal_id in fresh],
        "people": [person(user_id, False) for user_id in datas if user_id != viewer],
        "race": [],
        "months": [],
    }
