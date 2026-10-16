"""Achievements: monthly titles and hidden medals among the people who take part (opt-in inside Friends).

data/users/<id>/achievements.json keeps a person's medals, what they've seen and highlighted, and the running numbers
behind the medals; data/achievements.json keeps the closed months. Everything is worked out in the loop that collects
plays (dashboard.collector), from plays.json plus Last.fm listeners and artist fans looked up and cached in the
background; panel actions arrive through note(). Opening the tab never asks anyone outside.

Privacy: only participants see anything. A medal nobody earned never leaves this module, and its "how" line only
reaches whoever earned it; the browser knows medals by opaque public ids (files keep the real ones). Erasing removes
the person's file and their name from closed months.
"""
from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
import unicodedata
from collections import Counter
from pathlib import Path
from typing import Callable

from . import accounts, config, curation, favorites, i18n, medal_rules, monthly, reviews, social
from .deezer import Deezer, DeezerError
from .i18n import t
from .lastfm import LastFmError, ListenerCounts
from .medal_rules import Context, first_artist
from .medals import BY_ID, GAMES_BY_SLUG, MEDALS, TITLES, Medal

MAX_HIGHLIGHTS = 10
LOOKUPS_PER_LOOP = 300  # Last.fm and fans lookups of each kind per person per loop; the rest wait for the next one
FANS_FILE = "fans-cache.json"
FANS_FRESH_S = 30 * 86400
FANS_MAX_ENTRIES = 100_000
RICH_WAIT_S = 3 * 86400  # how long the cursor may wait at one play whose lookups keep failing
SYNC_S = 5 * 60  # two plays of a song this close together count as "in sync"
MONTHS_SHOWN = 12

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
            "through": 0, "rich_through": 0, "stall": None}


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
    if not _well_formed(full):
        raise Unreadable(f"{user_id}: a field has the wrong type")
    full["stats"] = {**medal_rules.new_stats(), **full["stats"]}  # numbers added in later versions start empty
    return full


def _number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _well_formed(data: dict) -> bool:
    return (isinstance(data["on"], bool) and (data["joined"] is None or _number(data["joined"]))
            and all(isinstance(data[key], dict) for key in ("earned", "seen", "stats"))
            and isinstance(data["highlights"], list) and _number(data["through"]) and _number(data["rich_through"])
            and (data["stall"] is None or (isinstance(data["stall"], dict) and _number(data["stall"].get("at"))
                                           and _number(data["stall"].get("since")))))


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
    """Turning on the first time counts the history Friends already has; coming back skips the time away (which is
    no gap in listening: it neither makes a comeback nor ends a streak of its own)."""
    now = time.time() if now is None else now
    with _lock:
        data = load(user_id)
        if on and not data["on"]:
            if data["joined"] is not None:
                data["through"] = data["rich_through"] = now
                data["stats"]["last_at"] = None
                data["stats"]["streak"] = {}
            data["joined"] = data["joined"] or now
        data["on"] = on
        _write(_file(user_id), data)


def forget(user_id: str) -> None:
    """Erases the person's achievements, their id from other people's matches and their name from closed months
    (a duo they were part of goes with them)."""
    with _lock:
        _file(user_id).unlink(missing_ok=True)
        for other in config.list_users():
            if other == user_id:
                continue
            try:
                data = load(other)
            except Unreadable as err:
                log.warning("Achievements: couldn't remove %s from %s's matches: %s", user_id, other, err)
                continue
            if data["stats"]["matched_with"].pop(user_id, None) is not None:
                _write(_file(other), data)
        try:
            room = _read_room()
        except Unreadable as err:
            log.warning("Achievements: couldn't remove %s from past months: %s", user_id, err)
            return
        changed = False
        for titles in room["months"].values():
            for title in list(titles):
                if user_id not in titles[title]["users"]:
                    continue
                changed = True
                users = [uid for uid in titles[title]["users"] if uid != user_id]
                if users and title != "duo":
                    titles[title]["users"] = users
                else:
                    del titles[title]
        if changed:
            _write(_room_file(), room)


# ---------- the catalog as this room sees it


def public_id(medal_id: str) -> str:
    """The id the browser gets: a real id spells out the rule, and the network log would show it for medals other
    people earned."""
    return hashlib.sha256(f"medal:{medal_id}".encode()).hexdigest()[:12]


_REAL_IDS = {public_id(medal.id): medal.id for medal in MEDALS}


def _real_ids(ids: list[str]) -> list[str]:
    """Public ids back to the real ones; anything else is dropped."""
    return [_REAL_IDS[medal_id] for medal_id in ids if medal_id in _REAL_IDS]


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
    made = {f"spotify:playlist:{fav['playlist_id']}" for fav in favorites.load(user_id)
            if fav.get("playlist_id") and fav.get("kind") in ("discovery", "curated")}  # a pinned one is the person's own

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


class ArtistFans:
    """Fans per artist name, looked up in the background and kept 30 days in data/fans-cache.json."""

    def __init__(self, path: Path | None = None, now: Callable[[], float] = time.time) -> None:
        self._path, self._now = path, now
        self._lock = threading.Lock()
        self._data: dict[str, dict] | None = None
        self._dirty = False

    @staticmethod
    def key(name: str) -> str:
        return " ".join(unicodedata.normalize("NFKC", name).casefold().split())

    def _file(self) -> Path:
        return self._path or config.DATA_DIR / FANS_FILE

    def _entries(self) -> dict[str, dict]:
        """Called with the lock held."""
        if self._data is None:
            try:
                data = json.loads(self._file().read_text(encoding="utf-8"))
            except (FileNotFoundError, ValueError):
                data = {}
            self._data = data if isinstance(data, dict) else {}
        return self._data

    def known(self, name: str) -> bool:
        with self._lock:
            return self.key(name) in self._entries()

    def fresh(self, name: str) -> bool:
        """An entry exists and is younger than FANS_FRESH_S (a stale one is still usable, but is asked again)."""
        with self._lock:
            entry = self._entries().get(self.key(name))
        return bool(entry) and self._now() - entry["at"] < FANS_FRESH_S

    def cached(self, name: str) -> int | None:
        with self._lock:
            entry = self._entries().get(self.key(name))
        return entry["n"] if entry else None

    def get(self, dz: Deezer, name: str) -> int | None:
        with self._lock:
            entry = self._entries().get(self.key(name))
        if entry and self._now() - entry["at"] < FANS_FRESH_S:
            return entry["n"]
        found = dz.search_artist(name)  # errors propagate and nothing is cached
        fans = found.get("nb_fan") if found else None
        with self._lock:
            entries = self._entries()
            entries[self.key(name)] = {"n": fans, "at": self._now()}
            if len(entries) > FANS_MAX_ENTRIES:  # keep the newest 90%
                newest = sorted(entries, key=lambda key: entries[key]["at"], reverse=True)[: int(FANS_MAX_ENTRIES * 0.9)]
                self._data = {key: entries[key] for key in newest}
            self._dirty = True
        return fans

    def save(self) -> None:
        with self._lock:
            if not self._dirty or self._data is None:
                return
            path = self._file()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(self._data, ensure_ascii=False), encoding="utf-8")
            self._dirty = False


def enrich(plays: list[dict], after: float, counts: ListenerCounts | None, fans: ArtistFans, dz: Deezer,
           budget: int = LOOKUPS_PER_LOOP) -> None:
    """Looks up what the rich medals need for plays after `after`: at most `budget` Last.fm and `budget` fans
    lookups; a failure stops that kind until the next loop (and is logged)."""
    asked = {"lastfm": 0, "fans": 0}
    going = {"lastfm": counts is not None, "fans": True}
    for item in plays:
        if item["at"] <= after:
            continue
        name = _artist_name(item)
        if not name:
            continue
        if going["lastfm"] and counts.cached(name, item["title"]) is None:
            if asked["lastfm"] >= budget:
                going["lastfm"] = False
            else:
                asked["lastfm"] += 1
                try:
                    counts.get(name, item["title"])
                except LastFmError as err:
                    log.warning("Achievements: Last.fm lookups wait for the next loop (%s)", err.kind)
                    going["lastfm"] = False
        if going["fans"] and not fans.fresh(name):
            if asked["fans"] >= budget:
                going["fans"] = False
            else:
                asked["fans"] += 1
                try:
                    fans.get(dz, name)
                except DeezerError as err:
                    log.warning("Achievements: fans lookups wait for the next loop (%s)", err)
                    going["fans"] = False
        if not any(going.values()):
            break


def rich_pass(user_id: str, plays: list[dict], ctx: Context, lastfm: bool, counts: ListenerCounts | None,
              fans: ArtistFans, now: float | None = None) -> list[str]:
    """Plays whose numbers are known, in order, into the "rich" medals; stops at the first play still waiting.
    The cursor waits at one play at most 3 days, counted from when it first stopped there: then the play goes in
    with what is known (an unknown number earns nothing)."""
    now = time.time() if now is None else now
    with _lock:
        data = load(user_id)
        if not data["on"]:
            return []
        pending = _pending(data, "rich", lastfm)
        new, last, changed = [], None, False
        for item in sorted(plays, key=lambda item: item["at"]):
            if item["at"] <= data["rich_through"]:
                continue
            name = _artist_name(item)
            waiting = name and ((counts is not None and counts.cached(name, item["title"]) is None) or not fans.known(name))
            stall = data["stall"]
            here = stall is not None and stall["at"] == item["at"]
            if waiting:
                if not (here and now - stall["since"] >= RICH_WAIT_S):
                    if not here:
                        data["stall"] = {"at": item["at"], "since": now}
                        changed = True
                    break  # its numbers aren't known yet: the next loop picks up from here
            medal_rules.rich_update(data["stats"], item, ctx)
            new += _award_due(data, pending, item, ctx, item["at"])
            last = item["at"]
            if here:
                data["stall"] = None
                changed = True
        if last is not None or changed:
            if last is None:
                last = data["rich_through"]
            data["rich_through"] = last
            _write(_file(user_id), data)
        return new


def _plays_by_song(plays_by_user: dict[str, list[dict]], people: list[str], now: float) -> dict[str, list[tuple]]:
    """The last week's plays of each song: (at, person, play), oldest first."""
    heard: dict[str, list[tuple]] = {}
    for user_id in people:
        for item in plays_by_user.get(user_id, []):
            if item["at"] >= now - social.MATCH_DAYS * 86400:
                heard.setdefault(item["uri"], []).append((item["at"], user_id, item))
    for entries in heard.values():
        entries.sort(key=lambda entry: entry[0])
    return heard


def room_pass(plays_by_user: dict[str, list[dict]], lastfm: bool, now: float | None = None) -> dict[str, list[str]]:
    """Matches among participants (the same song within 6 hours, as in Friends) into each one's medals."""
    now = time.time() if now is None else now
    with _lock:
        datas = {}
        for user_id in plays_by_user:
            try:
                datas[user_id] = load(user_id)
            except Unreadable as err:
                log.warning("Achievements left alone: %s", err)
        people = [user_id for user_id, data in datas.items() if data["on"]]
        latest: dict[str, tuple[float, dict]] = {}
        trio: dict[str, dict] = {}
        for uri, entries in _plays_by_song(plays_by_user, people, now).items():
            for index, (start, first, first_play) in enumerate(entries):
                window = [(user_id, item) for at, user_id, item in entries[index:] if at - start <= social.MATCH_WINDOW_S]
                if len({user_id for user_id, _ in window}) >= 3:
                    for user_id, item in window:
                        datas[user_id]["stats"]["room"]["trio"] = 1
                        trio[user_id] = item
                for at, second, second_play in entries[index + 1:]:
                    if at - start > social.MATCH_WINDOW_S:
                        break
                    if second == first:
                        continue
                    for me, other, mine in ((first, second, first_play), (second, first, second_play)):
                        stats = datas[me]["stats"]
                        stats["distinct"].setdefault("matched", {})[uri] = 1
                        stats["matched_with"][other] = 1
                        if at - start <= SYNC_S:
                            stats["room"]["sync"] = 1
                        if at >= latest.get(me, (0, None))[0]:
                            latest[me] = (at, mine)
        firsts = {user_id: monthly.settled(datas[user_id]["stats"]["artists"]) for user_id in people}
        new = {}
        for me in people:
            stats = datas[me]["stats"]
            others = set(people) - {me}
            if len(others) >= 2 and others <= set(stats["matched_with"]):
                stats["room"]["everyone"] = 1
            stats["room"]["trend"] = len({artist for other in others for artist in monthly.picked_up(firsts[me], firsts[other])})
            stats["room"]["follow"] = len({artist for other in others for artist in monthly.picked_up(firsts[other], firsts[me])})
            new[me] = []
            for medal in _pending(datas[me], "room", lastfm):
                song = trio.get(me) if medal.params.get("song_from") == "trio" else latest.get(me, (0, None))[1]
                new[me] += _award_due(datas[me], [medal], song, Context(), now)
            _write(_file(me), datas[me])
        return new


def close_month(plays_by_user: dict[str, list[dict]], fans, lastfm: bool, now: float | None = None) -> str | None:
    """Closes last month once (only months from the first one achievements ran), saving its titles and awarding
    the medals that come from them. Returns the month closed."""
    now = time.time() if now is None else now
    month = monthly.previous_month(now)
    with _lock:
        try:
            room = _read_room()
        except Unreadable as err:
            log.warning("Achievements: months left alone: %s", err)
            return None
        if "since" not in room:
            room["since"] = monthly.month_of(now)
            _write(_room_file(), room)
        if month < room["since"] or month in room["months"] or not plays_by_user:
            return None
        datas = {}
        for user_id in plays_by_user:
            try:
                datas[user_id] = load(user_id)
            except Unreadable as err:
                log.warning("Achievements left alone: %s", err)
        datas = {user_id: data for user_id, data in datas.items() if data["on"]}  # only participants compete
        firsts = {user_id: data["stats"]["artists"] for user_id, data in datas.items()}
        titles = monthly.standings(month, {user_id: plays_by_user[user_id] for user_id in datas}, firsts, fans)
        room["months"][month] = titles
        _write(_room_file(), room)
        for title, held in titles.items():
            for user_id in held["users"]:
                datas[user_id]["stats"]["titles"].append({"month": month, "title": title})
        for user_id, data in datas.items():
            _award_due(data, _pending(data, "titles", lastfm), None, Context(), now)
            _write(_file(user_id), data)
        return month


def _titles_view(titles: dict[str, dict]) -> list[dict]:
    shown = []
    for title in TITLES:
        if title not in titles:
            continue
        value = round(titles[title]["value"])
        shown.append({"id": title, "name": t(f"title.{title}"),
                      "holders": [accounts.display_name(user_id) for user_id in titles[title]["users"]],
                      "value": t(f"title.{title}.value", count=value, value=i18n.number(value))})
    return shown


def _past_months(people: set[str]) -> list[dict]:
    """Closed months as the current participants see them: someone who left isn't listed (the file keeps them for a
    return) and a duo shows only while both are in."""
    try:
        months = _read_room()["months"]
    except Unreadable:
        return []
    shown = []
    for month, titles in sorted(months.items(), reverse=True):
        kept = {}
        for title, held in titles.items():
            users = [user_id for user_id in held["users"] if user_id in people]
            if users and (title != "duo" or len(users) == len(held["users"])):
                kept[title] = {**held, "users": users}
        if kept:
            shown.append({"month": month, "titles": _titles_view(kept)})
    return shown[:MONTHS_SHOWN]


def note(user_id: str, event: str, lastfm: bool = False, **detail) -> list[str]:
    """Something done in the panel: counted only for participants, and medals are awarded right away."""
    if not taking_part(user_id):
        return []
    with _lock:
        try:
            data = load(user_id)
        except Unreadable:
            return []
        if not data["on"]:
            return []  # left or erased since the check: nothing is kept
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
        elif event == "review":  # only reviews written since joining
            joined = data["joined"] or 0
            mine = [review for review in reviews.mine(user_id).values()
                    if isinstance(review, dict) and _number(review.get("at")) and review["at"] >= joined]
            events["reviews"] = len(mine)
            events["review_five"] = int(any(review.get("rating") == 5 for review in mine))
            events["review_long"] = int(any(review.get("public") and len(review.get("text") or "") >= 500
                                             for review in mine))
        new = _award_due(data, _pending(data, "event", lastfm), None, Context(), time.time())
        _write(_file(user_id), data)
        return new


# ---------- what people see


def mark_seen(user_id: str, ids: list[str]) -> None:
    """`ids` are public ids (as the browser has them); only earned medals count."""
    with _lock:
        data = load(user_id)
        if not data["on"]:
            return
        data["seen"].update({medal_id: 1 for medal_id in _real_ids(ids) if medal_id in data["earned"]})
        _write(_file(user_id), data)


def set_highlights(user_id: str, ids: list[str]) -> None:
    """Up to 10 earned medals (public ids), in the order given; anything else is dropped."""
    with _lock:
        data = load(user_id)
        if not data["on"]:
            return
        chosen = dict.fromkeys(_real_ids(ids))
        data["highlights"] = [medal_id for medal_id in chosen if medal_id in data["earned"]][:MAX_HIGHLIGHTS]
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
    return [{"id": public_id(medal_id), "name": medal_texts(medal_id)[0]}
            for medal_id in data["highlights"] if medal_id in data["earned"] and medal_id in ids]


def _medal_view(medal_id: str, got: dict, holders: int, own: bool) -> dict:
    name, how = medal_texts(medal_id)
    shown = {"id": public_id(medal_id), "name": name, "at": got["at"], "song": got.get("song"), "holders": holders}
    if own:  # only whoever earned it learns how (a Last.fm count would hint at it too)
        shown["how"] = how
        shown["lastfm"] = got.get("lastfm")
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
        if user_id == viewer:
            datas[user_id] = mine
            continue
        try:
            datas[user_id] = load(user_id)
        except Unreadable:
            continue
    ids = {medal.id for medal in available(lastfm)}
    holders = Counter(medal_id for data in datas.values() for medal_id in data["earned"] if medal_id in ids)

    def person(user_id: str, own: bool) -> dict:
        earned = sorted(((medal_id, got) for medal_id, got in datas[user_id]["earned"].items() if medal_id in ids),
                        key=lambda pair: pair[1]["at"], reverse=True)
        medals = {medal_id: _medal_view(medal_id, got, holders[medal_id], own) for medal_id, got in earned}
        return {"id": user_id, "name": accounts.display_name(user_id), "count": len(medals),
                "highlights": [medals[medal_id] for medal_id in datas[user_id]["highlights"] if medal_id in medals],
                "medals": list(medals.values())}

    fresh = sorted((got["at"], medal_id) for medal_id, got in mine["earned"].items()
                   if medal_id in ids and medal_id not in mine["seen"])
    return {
        "sharing": True, "on": True, "total": len(ids), "participants": len(datas), "lastfm": lastfm,
        "me": person(viewer, True),
        "new": [public_id(medal_id) for _, medal_id in fresh],
        "people": [person(user_id, False) for user_id in datas if user_id != viewer],
        "race": _titles_view(monthly.standings(monthly.month_of(now), {user_id: social.plays(user_id) for user_id in datas},
                                               {user_id: data["stats"]["artists"] for user_id, data in datas.items()}, fans)),
        "months": _past_months(set(datas)),
    }
