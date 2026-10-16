"""Monthly titles: one holder per month among the people taking part in achievements (ties share).

Not secret: the owner chose the eight titles, and the race for the month in progress shows openly. Worked out from
plays (Friends keeps 90 days) and each person's first-heard artists (their achievements numbers).
"""
from __future__ import annotations

import statistics
from datetime import timedelta
from typing import Callable

from .medal_rules import first_artist, local, release
from .medals import TITLES
from .social import MATCH_WINDOW_S

MIN_PLAYS = 50  # fewer plays in the month: out of the race
MIN_FANS_KNOWN = 20  # "most alternative" needs fans for this many of the month's artists
TREND_S = 30 * 86400


def month_of(at: float) -> str:
    return local(at).strftime("%Y-%m")


def previous_month(at: float) -> str:
    first = local(at).date().replace(day=1)
    return (first - timedelta(days=1)).strftime("%Y-%m")


def picked_up(mine: dict[str, float], theirs: dict[str, float]) -> list[str]:
    """Artists the other person heard for the first time within 30 days after I did."""
    return [artist for artist, first in mine.items() if artist in theirs and first < theirs[artist] <= first + TREND_S]


def _pair_matches(mine: list[dict], theirs: list[dict]) -> int:
    times: dict[str, list[float]] = {}
    for item in theirs:
        times.setdefault(item["uri"], []).append(item["at"])
    return len({item["uri"] for item in mine
                if any(abs(item["at"] - other) <= MATCH_WINDOW_S for other in times.get(item["uri"], ()))})


def standings(month: str, plays_by_user: dict[str, list[dict]], firsts_by_user: dict[str, dict[str, float]],
              fans: Callable[[str], int | None]) -> dict[str, dict]:
    """Each title's holders and their number in `month`; a title nobody can hold is left out."""
    month_plays = {uid: [item for item in plays if month_of(item["at"]) == month] for uid, plays in plays_by_user.items()}
    eligible = sorted(uid for uid, plays in month_plays.items() if len(plays) >= MIN_PLAYS)
    values: dict[str, dict[str, float]] = {title: {} for title in TITLES}
    for uid in eligible:
        plays = month_plays[uid]
        hours = [local(item["at"]).hour for item in plays]
        firsts = firsts_by_user.get(uid, {})
        values["marathoner"][uid] = len(plays)
        values["night-owl"][uid] = sum(hour < 5 for hour in hours)
        values["early-bird"][uid] = sum(5 <= hour < 8 for hour in hours)
        values["explorer"][uid] = sum(month_of(first) == month for first in firsts.values())
        values["time-traveler"][uid] = len({found[0] // 10 for item in plays if (found := release(item))})
        names = {first_artist(item).get("name", "") for item in plays}
        known = [count for count in (fans(name) for name in names if name) if count is not None]
        if len(known) >= MIN_FANS_KNOWN:
            values["alternative"][uid] = statistics.median(known)
        started = {artist: first for artist, first in firsts.items() if month_of(first) == month}
        others = [firsts_by_user.get(other, {}) for other in plays_by_user if other != uid]
        values["trendsetter"][uid] = len({artist for theirs in others for artist in picked_up(started, theirs)})
    for index, first in enumerate(eligible):
        for second in eligible[index + 1:]:
            values["duo"][f"{first}+{second}"] = _pair_matches(month_plays[first], month_plays[second])
    result = {}
    for title in TITLES:
        numbers = values[title]
        if not numbers:
            continue
        best = min(numbers.values()) if title == "alternative" else max(numbers.values())
        if title != "alternative" and best <= 0:
            continue
        users = sorted({uid for key, value in numbers.items() if value == best for uid in key.split("+")})
        result[title] = {"users": users, "value": best}
    return result
