"""How plays become medals: the running numbers a person's medals need, and one check per rule.

Plain dicts in and out (saved in the person's achievements.json); no files, no network. Plays come in time order,
and "local" time is the room's clock (the server's time zone).
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from functools import lru_cache
from typing import Callable

from . import curation
from .lastfm import Listeners
from .medals import COLLECTIONS, GAMES_BY_SLUG, LOVE, MOON, SUN, WORDS, Game, Medal

HOUR_MS = 3_600_000
NONSTOP_GAP_S = 5 * 60  # between one song's end and the next one's start
SHORT_MS = 120_000
FIRST_RECORD_YEAR = 1860  # the oldest recording known; an earlier release year is a placeholder
HINTS = ("soundtrack", "ost", "original", "from", "game", "video game", "theme", "music from")


def _unknown(play: dict) -> None:
    return None


@dataclass(frozen=True)
class Context:
    """What a person's medals look at besides the play itself."""

    first_name: str = ""  # normalized
    finds: frozenset[str] = frozenset()  # songs the panel found for the person (their recent finds)
    playlists: frozenset[str] = frozenset()  # URIs of the playlists the panel made for the person
    listeners: Callable[[dict], Listeners | None] = _unknown  # the play's cached Last.fm count
    fans: Callable[[dict], int | None] = _unknown  # cached fans of the play's first artist


def new_stats() -> dict:
    return {
        "plays": 0, "ms": 0, "artists": {}, "songs": {}, "count": {}, "distinct": {}, "collections": {},
        "day": {}, "rich_day": {}, "streak": {}, "weekends": {}, "run": {}, "album": {}, "albums": {},
        "albums_long": 0, "last_at": None, "gap_days": 0.0, "hooked": {}, "made": {}, "events": {}, "kinds": {},
        "room": {}, "matched_with": {}, "titles": [],
    }


# ---------- reading a play


def local(at: float) -> datetime:
    return datetime.fromtimestamp(at)


@lru_cache(maxsize=8192)
def plain(text: str) -> str:
    """Normalized and padded with spaces for whole-word tests: ' kind of blue '."""
    return f" {curation.normalize(text)} "


def padded(title: str) -> str:
    """The title without its version ('So What - Live' -> ' so what ')."""
    return plain(curation.base_title(title))


def mentions(text: str, words) -> bool:
    return any(f" {word} " in text for word in words)


def first_artist(play: dict) -> dict:
    return (play.get("artists") or [{}])[0]


def artist_key(artist: dict) -> str:
    return artist.get("id") or curation.normalize(artist.get("name", ""))


def _names(play: dict) -> list[str]:
    return [curation.normalize(artist.get("name", "")) for artist in play.get("artists") or []]


def release(play: dict) -> tuple[int, date | None] | None:
    """(year, day) of the play's release; the day is None when Spotify only gives the year or the month. A year
    before recorded music or past next year ("0000" and the like) counts as no date."""
    text = (play.get("album") or {}).get("release") or ""
    if len(text) < 4 or not text[:4].isdigit() or not FIRST_RECORD_YEAR <= int(text[:4]) <= date.today().year + 1:
        return None
    try:
        day = date.fromisoformat(text) if len(text) == 10 else None
    except ValueError:
        day = None
    return int(text[:4]), day


def easter(year: int) -> date:
    """Western Easter Sunday (the anonymous Gregorian algorithm)."""
    golden, century, rest = year % 19, year // 100, year % 100
    leap_c, extra_c = divmod(century, 4)
    shift = (century + 8) // 25
    moon = (19 * golden + century - leap_c - (century - shift + 1) // 3 + 15) % 30
    leap_y, extra_y = divmod(rest, 4)
    weekday = (32 + 2 * extra_c + 2 * leap_y - moon - extra_y) % 7
    correction = (golden + 11 * moon + 22 * weekday) // 451
    month, day = divmod(moon + weekday - 7 * correction + 114, 31)
    return date(year, month, day + 1)


def matches_game(game: Game, play: dict) -> bool:
    """Music from the game: its name in the title or the album (plus a soundtrack hint when the name is a common
    word), or one of the game's own artists."""
    if any(name in game.artists for name in _names(play)):
        return True
    for text in (play.get("title", ""), (play.get("album") or {}).get("name") or ""):
        words = plain(text)  # the whole text: '(From "Apex Legends")' sits in the version part
        hinted = words.replace(" original mix ", " ")  # a dance track's "Original Mix" isn't a soundtrack
        if mentions(words, game.names) and (not game.context or mentions(hinted, HINTS)):
            return True
    return False


# ---------- running numbers


def _member(stats: dict, group: str, name: str, key: str) -> None:
    stats[group].setdefault(name, {})[key] = 1


def update(stats: dict, play: dict, ctx: Context) -> None:
    """Adds one play (in time order) to the numbers the "play" phase checks."""
    when = local(play["at"])
    title = padded(play["title"])
    found = release(play)
    stats["plays"] += 1
    stats["ms"] += play.get("duration_ms") or 0
    stats["songs"][play["uri"]] = 1
    for artist in play.get("artists") or []:
        key = artist_key(artist)
        if key:
            stats["artists"].setdefault(key, play["at"])
        initial = curation.normalize(artist.get("name", ""))[:1]
        if initial.isalpha():
            _member(stats, "collections", "letters", initial)
    hits = {
        "lunch": 12 <= when.hour < 14,
        "night": when.hour < 5,
        "dawn": 5 <= when.hour < 8,
        "weekend": when.weekday() >= 5,
        "love": mentions(title, LOVE),
        "feats": len(play.get("artists") or []) >= 2,
        "old": found is not None and when.year - found[0] >= 25,
        "new": found is not None and found[1] is not None and 0 <= (when.date() - found[1]).days <= 30,
    }
    for name, hit in hits.items():
        if hit:
            stats["count"][name] = stats["count"].get(name, 0) + 1
    if found and 1950 <= found[0] < 2030:
        _member(stats, "collections", "decades", str(found[0] // 10 * 10))
    for name, groups in COLLECTIONS.items():
        for index, group in enumerate(groups):
            if mentions(title, group):
                _member(stats, "collections", name, str(index))
    if mentions(title, MOON):
        _member(stats, "distinct", "moon", play["uri"])
    if mentions(title, SUN):
        _member(stats, "distinct", "sun", play["uri"])
    if play["uri"] in ctx.finds:
        stats["hooked"][play["uri"]] = stats["hooked"].get(play["uri"], 0) + 1
    _day(stats, play, when, found)
    _streaks(stats, play, when)
    _runs(stats, play)
    _album(stats, play)


def _day(stats: dict, play: dict, when: datetime, found: tuple | None) -> None:
    day = stats["day"]
    today = when.date().isoformat()
    if day.get("date") != today:
        day.clear()
        day.update(date=today, plays=0, ms=0, artists={}, songs={}, parts={}, hours={}, decades={})
    day["plays"] += 1
    day["ms"] += play.get("duration_ms") or 0
    for artist in play.get("artists") or []:
        if artist_key(artist):
            day["artists"][artist_key(artist)] = 1
    day["songs"][play["uri"]] = day["songs"].get(play["uri"], 0) + 1
    day["parts"][str(when.hour // 6)] = 1
    day["hours"][str(when.hour)] = 1
    if found:
        day["decades"][str(found[0] // 10)] = 1


def _streaks(stats: dict, play: dict, when: datetime) -> None:
    last_at = stats["last_at"]
    stats["gap_days"] = (play["at"] - last_at) / 86400 if last_at is not None else 0.0
    stats["last_at"] = play["at"]
    today = when.date()
    streak = stats["streak"]
    if streak.get("last") != today.isoformat():
        yesterday = (today - timedelta(days=1)).isoformat()
        streak["length"] = streak.get("length", 0) + 1 if streak.get("last") == yesterday else 1
        streak["last"] = today.isoformat()
    if when.weekday() >= 5:  # Saturday and Sunday of the same weekend, weekend after weekend
        saturday = today - timedelta(days=when.weekday() - 5)
        weekends = stats["weekends"]
        if weekends.get("current") != saturday.isoformat():
            weekends["current"], weekends["days"] = saturday.isoformat(), {}
        weekends["days"][str(when.weekday())] = 1
        if len(weekends["days"]) == 2 and weekends.get("last_full") != saturday.isoformat():
            before = (saturday - timedelta(days=7)).isoformat()
            weekends["run"] = weekends.get("run", 0) + 1 if weekends.get("last_full") == before else 1
            weekends["last_full"] = saturday.isoformat()


def _runs(stats: dict, play: dict) -> None:
    run = stats["run"]
    artist = artist_key(first_artist(play))
    run["artist_n"] = run.get("artist_n", 0) + 1 if artist and run.get("artist") == artist else 1
    run["artist"] = artist
    window = run.get("diverse", [])
    if artist in window:  # the run of different artists starts again after this artist's last play
        window = window[window.index(artist) + 1:]
    run["diverse"] = (window + [artist])[-50:]
    run["song_n"] = run.get("song_n", 0) + 1 if run.get("song") == play["uri"] else 1
    run["song"] = play["uri"]
    ms = play.get("duration_ms") or 0
    previous = run.get("at")
    # played_at may mark a song's start or end: the gap allows the longer of the two songs plus 5 minutes.
    if previous is not None and play["at"] - previous <= max(run.get("ms", 0), ms) / 1000 + NONSTOP_GAP_S:
        run["nonstop_ms"] = run.get("nonstop_ms", 0) + ms
    else:
        run["nonstop_ms"] = ms
    run["at"], run["ms"] = play["at"], ms
    run["short_n"] = run.get("short_n", 0) + 1 if 0 < ms < SHORT_MS else 0


def _album(stats: dict, play: dict) -> None:
    """Tracks of one album in order, disc after disc (track numbers restart on each disc), N being the album's
    total: a whole album is N plays in a row, disc 1 track 1 first."""
    album = play.get("album") or {}
    number, total = play.get("track_number"), album.get("tracks")
    disc = play.get("disc_number") or 1
    state = stats["album"]
    if not album.get("id") or not number or not total:
        state.clear()
        return
    same_album = state.get("id") == album["id"]
    if number == 1 and disc == 1:
        state.clear()
        state.update(id=album["id"], disc=1, number=1, count=1)
    elif same_album and ((disc == state["disc"] and number == state["number"] + 1)
                         or (disc == state["disc"] + 1 and number == 1)):
        state.update(disc=disc, number=number, count=state["count"] + 1)
    else:
        state.clear()
        return
    if state["count"] == total:
        if total >= 6:
            stats["albums"][album["id"]] = 1
            if total >= 15:
                stats["albums_long"] = 1
        state.clear()


def rich_update(stats: dict, play: dict, ctx: Context) -> None:
    """Adds one play to the numbers that need its Last.fm listeners and its artist's fans."""
    heard = ctx.listeners(play)
    if heard is not None and heard.count is not None:
        if heard.count < 100:
            _member(stats, "distinct", "rare100", play["uri"])
        if heard.count < 1000:
            _member(stats, "distinct", "rare1000", play["uri"])
    day = stats["rich_day"]
    today = local(play["at"]).date().isoformat()
    if day.get("date") != today:
        day.clear()
        day.update(date=today, small=0, giant=0)
    fans = ctx.fans(play)
    if fans is not None:
        if fans < 1000:
            _member(stats, "distinct", "small_artists", artist_key(first_artist(play)))
            day["small"] = 1
        if fans > 10_000_000:
            day["giant"] = 1


def stat_value(stats: dict, name: str) -> float:
    """One running number by name ("plays", "count:night", "day:repeat"...). Unknown names raise KeyError."""
    family, _, key = name.partition(":")
    if not key:
        return _SIMPLE[family](stats)
    if family in ("count", "events", "room"):
        return stats[family].get(key, 0)
    if family == "distinct":
        return len(stats["distinct"].get(key, {}))
    if family == "collection":
        return len(stats["collections"].get(key, {}))
    if family == "day":
        return _DAY[key](stats["day"])
    if family == "run":
        return _RUN[key](stats["run"])
    if family == "titles":
        return _WON[key](stats["titles"])
    if family == "rich_day" and key == "extremes":
        return int(bool(stats["rich_day"].get("small") and stats["rich_day"].get("giant")))
    raise KeyError(name)


def _month_index(month: str) -> int:
    year, number = month.split("-")
    return int(year) * 12 + int(number)


def _title_streak(titles: list[dict]) -> int:
    best = 0
    for title in {won["title"] for won in titles}:
        run, previous = 0, None
        for month in sorted({_month_index(won["month"]) for won in titles if won["title"] == title}):
            run = run + 1 if previous is not None and month == previous + 1 else 1
            previous, best = month, max(best, run)
    return best


_SIMPLE = {
    "plays": lambda stats: stats["plays"],
    "hours": lambda stats: stats["ms"] / HOUR_MS,
    "artists": lambda stats: len(stats["artists"]),
    "songs": lambda stats: len(stats["songs"]),
    "streak": lambda stats: stats["streak"].get("length", 0),
    "weekends": lambda stats: stats["weekends"].get("run", 0),
    "albums": lambda stats: len(stats["albums"]),
    "albums_long": lambda stats: stats["albums_long"],
    "hooked": lambda stats: max(stats["hooked"].values(), default=0),
    "kinds": lambda stats: len(stats["kinds"]),
}
_DAY = {
    "plays": lambda day: day.get("plays", 0),
    "hours": lambda day: day.get("ms", 0) / HOUR_MS,
    "artists": lambda day: len(day.get("artists", {})),
    "repeat": lambda day: max(day.get("songs", {}).values(), default=0),
    "parts": lambda day: len(day.get("parts", {})),
    "clock": lambda day: len(day.get("hours", {})),
    "decades": lambda day: len(day.get("decades", {})),
}
_RUN = {
    "artist": lambda run: run.get("artist_n", 0),
    "diverse": lambda run: len(run.get("diverse", [])),
    "song": lambda run: run.get("song_n", 0),
    "nonstop_hours": lambda run: run.get("nonstop_ms", 0) / HOUR_MS,
    "short": lambda run: run.get("short_n", 0),
}
_WON = {
    "count": len,
    "kinds": lambda titles: len({won["title"] for won in titles}),
    "double": lambda titles: max(Counter(won["month"] for won in titles).values(), default=0),
    "streak": _title_streak,
}


# ---------- one check per rule: rule(params, stats, play, ctx) -> bool


def _total(params, stats, play, ctx):
    return stat_value(stats, params["stat"]) >= params["at_least"]


def _clock(params, stats, play, ctx):
    return params["from"] <= local(play["at"]).strftime("%H:%M") <= params["to"]


def _date(params, stats, play, ctx):
    when = local(play["at"])
    return (when.month, when.day) == (params["month"], params["day"])


def _new_year(params, stats, play, ctx):
    when = local(play["at"])
    clock = when.strftime("%H:%M")
    return ((when.month, when.day) == (12, 31) and clock >= "23:50") or ((when.month, when.day) == (1, 1) and clock <= "00:10")


def _friday_13(params, stats, play, ctx):
    when = local(play["at"])
    return when.weekday() == 4 and when.day == 13


def _carnival(params, stats, play, ctx):
    day = local(play["at"]).date()
    sunday = easter(day.year)
    return day in (sunday - timedelta(days=48), sunday - timedelta(days=47))


def _date_words(params, stats, play, ctx):
    return _date(params, stats, play, ctx) and mentions(padded(play["title"]), WORDS[params["words"]])


def _weekday_words(params, stats, play, ctx):
    return local(play["at"]).weekday() == params["weekday"] and mentions(padded(play["title"]), WORDS[params["words"]])


def _released_before(params, stats, play, ctx):
    found = release(play)
    return found is not None and found[0] < params["year"]


def _same_day(params, stats, play, ctx):
    found = release(play)
    return bool(found and found[1] == local(play["at"]).date())


def _anniversary(params, stats, play, ctx):
    found, today = release(play), local(play["at"]).date()
    return bool(found and found[1] and (found[1].month, found[1].day) == (today.month, today.day)
                and today.year > found[1].year)


def _years_ago(params, stats, play, ctx):
    found = release(play)
    return bool(found and found[0] == local(play["at"]).year - params["years"])


def _min_ms(params, stats, play, ctx):
    return (play.get("duration_ms") or 0) >= params["ms"]


def _max_ms(params, stats, play, ctx):
    return 0 < (play.get("duration_ms") or 0) < params["ms"]


def _min_artists(params, stats, play, ctx):
    return len(play.get("artists") or []) >= params["n"]


def _title_words(params, stats, play, ctx):
    return len(padded(play["title"]).split()) >= params["n"]


def _title_has(params, stats, play, ctx):
    return mentions(padded(play["title"]), params["words"])


def _self_titled(params, stats, play, ctx):
    title = padded(play["title"]).strip()
    return bool(title) and title == curation.normalize(first_artist(play).get("name", ""))


def _title_track(params, stats, play, ctx):
    album = play.get("album") or {}
    title = padded(play["title"]).strip()
    return album.get("type") == "album" and bool(title) and title == padded(album.get("name") or "").strip()


def _namesake(params, stats, play, ctx):
    return len(ctx.first_name) >= 3 and any(f" {ctx.first_name} " in f" {name} " for name in _names(play))


def _digit_artist(params, stats, play, ctx):
    return any(name[:1].isdigit() for name in _names(play))


def _artist(params, stats, play, ctx):
    return any(name in params["names"] for name in _names(play))


def _song(params, stats, play, ctx):
    if padded(play["title"]).strip() not in params["titles"]:
        return False
    return not params.get("artist") or params["artist"] in _names(play)


def _panel_playlist(params, stats, play, ctx):
    uri = (play.get("context") or {}).get("uri")
    return bool(uri) and (uri in ctx.playlists or uri in stats["made"])


def _comeback(params, stats, play, ctx):
    return stats["gap_days"] >= params["days"]


def _game(params, stats, play, ctx):
    return matches_game(GAMES_BY_SLUG[params["game"]], play)


def _listeners_below(params, stats, play, ctx):
    heard = ctx.listeners(play)
    return heard is not None and heard.count is not None and heard.count < params["n"]


def _listeners_above(params, stats, play, ctx):
    heard = ctx.listeners(play)
    return heard is not None and heard.count is not None and heard.count > params["n"]


def _fans_below(params, stats, play, ctx):
    fans = ctx.fans(play)
    return fans is not None and fans < params["n"]


def _fans_above(params, stats, play, ctx):
    fans = ctx.fans(play)
    return fans is not None and fans > params["n"]


RULES: dict[str, Callable[[dict, dict, dict | None, Context], bool]] = {
    "total": _total, "clock": _clock, "date": _date, "new_year": _new_year, "friday_13": _friday_13,
    "carnival": _carnival, "date_words": _date_words, "weekday_words": _weekday_words,
    "released_before": _released_before, "same_day": _same_day, "anniversary": _anniversary, "years_ago": _years_ago,
    "min_ms": _min_ms, "max_ms": _max_ms, "min_artists": _min_artists, "title_words": _title_words,
    "title_has": _title_has, "self_titled": _self_titled, "title_track": _title_track, "namesake": _namesake,
    "digit_artist": _digit_artist, "artist": _artist, "song": _song, "panel_playlist": _panel_playlist,
    "comeback": _comeback, "game": _game, "listeners_below": _listeners_below, "listeners_above": _listeners_above,
    "fans_below": _fans_below, "fans_above": _fans_above,
}


def check(medal: Medal, stats: dict, play: dict | None, ctx: Context) -> bool:
    return RULES[medal.rule](medal.params, stats, play, ctx)
