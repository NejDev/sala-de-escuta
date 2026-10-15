# Achievements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Monthly titles and 138+ hidden medals (plus one per game) for the people who take part, worked out in the
background from the plays Friends already collects, with a new "Conquistas" tab.

**Architecture:** `medals.py` is the catalog (data, spoilers); `medal_rules.py` turns plays into running numbers and
checks one rule per medal (pure); `achievements.py` keeps each person's file, runs the passes (plays, Last.fm/fans
lookups, matches, closed months) and builds what the API returns; `monthly.py` works out the titles. The dashboard's
collector loop drives it every 15 minutes; panel actions call `achievements.note()`.

**Tech Stack:** Python 3.12 standard library, unittest with fakes, vanilla JS (`static/app.js`), CSS.

**Spec:** `docs/superpowers/specs/2026-10-15-achievements-design.md` and its companion catalog
`docs/superpowers/specs/2026-10-15-achievements-catalog.md` (SPOILERS: the owner doesn't read it; this plan never
names a medal outside code identifiers that tests need).

## Global Constraints

- Python 3.12 standard library only. No new packages.
- Every text a person sees goes through `t()`, in pt and en (`i18n.py` / `static/i18n.js`, valid JSON after `const STRINGS = `).
- Never mention Deezer in the UI. Last.fm is credited (text and a link, no logo) wherever its numbers show.
- No Spotify request is ever made for achievements.
- Secrecy: the browser never receives a medal nobody in the room earned, nor the "how" of a medal the viewer didn't
  earn. Commit messages name no medal.
- Privacy: only participants (achievements on + sharing in Friends + allowed in Friends) see anything; leaving Friends
  or the owner turning Friends off for someone erases their achievements.
- Tests use fakes only (no Spotify, Last.fm or Deezer for real). Run with `python -m unittest discover -s tests`.
- Windows: write patch scripts to the scratchpad and run them with `python -I`; heredocs break.

## Review Focus

1. **Day boundaries in local time:** plays at 23:59 and 00:01 belong to different days, streaks and month closing use
   the room's clock. (Task 3 `test_a_day_starts_at_midnight`, Task 6 `test_closes_last_month_once_from_the_first_month_on`.)
2. **A 90-day history on joining:** thousands of plays processed at once must award each medal once, with the play
   that crossed the line, and never twice on the next loop. (Task 4 `test_joining_counts_the_history_already_collected`.)
3. **Leaks:** a non-participant, someone who left, the "how" of others' medals, unearned ids sent in highlights or
   seen lists. (Task 4 `ViewTest`, Task 7 `test_highlights_and_seen_take_only_earned_medals`.)
4. **Lookups that fail midway:** a Last.fm or Deezer failure must not skip plays for the rich medals (the cursor stops
   at the first play whose numbers aren't known). (Task 5 `test_rich_medals_wait_for_their_numbers`.)
5. **Unreadable files:** a corrupt `achievements.json` is never overwritten, and the person is skipped, not crashed
   on. (Task 4 `test_an_unreadable_file_is_left_alone`.)

---

### Task 1: Plays keep album, track number and context; cached Last.fm reads

**Files:**
- Modify: `spotify_assistant/social.py` (`_play`)
- Modify: `spotify_assistant/lastfm.py` (`ListenerCounts.cached`)
- Test: `tests/test_social.py`, `tests/test_lastfm.py`

**Interfaces:**
- Produces: plays with `album: {"id", "name", "type", "release", "tracks"}`, `track_number`, `context: {"type", "uri"} | None`;
  `ListenerCounts.cached(artist: str, title: str) -> Listeners | None` (any age; None when never asked).

- [ ] **Step 1: Write the failing tests**

In `tests/test_social.py`, add a class at the end (before `if __name__`, if present):

```python
class PlayTest(unittest.TestCase):
    def test_keeps_what_achievements_need(self):
        item = {"played_at": "2026-10-15T12:00:00Z", "context": {"type": "album", "uri": "spotify:album:al"},
                "track": {"uri": "spotify:track:t", "name": "So What", "duration_ms": 562000, "track_number": 1,
                          "artists": [{"id": "md", "name": "Miles Davis"}],
                          "album": {"id": "al", "name": "Kind of Blue", "album_type": "album",
                                    "release_date": "1959-08-17", "total_tracks": 5, "images": []}}}
        played = social._play(item)
        self.assertEqual(played["album"], {"id": "al", "name": "Kind of Blue", "type": "album",
                                           "release": "1959-08-17", "tracks": 5})
        self.assertEqual((played["track_number"], played["context"]), (1, {"type": "album", "uri": "spotify:album:al"}))
        self.assertIsNone(social._play({**item, "context": None})["context"])
```

In `tests/test_lastfm.py`, `CacheTest`, add:

```python
    def test_cached_reads_without_asking(self):
        counts = self.counts()
        self.assertIsNone(counts.cached("Miles Davis", "So What"))
        counts.get("Miles Davis", "So What")
        self.now[0] += lastfm.FRESH_S * 2  # however old
        self.assertEqual(counts.cached("MILES DAVIS", "So What (Live)"), lastfm.Listeners(1234, PAGE))
        self.assertEqual(len(self.server.urls), 1)
```

- [ ] **Step 2: Run them to see them fail**

Run: `python -m unittest tests.test_social.PlayTest tests.test_lastfm.CacheTest.test_cached_reads_without_asking`
Expected: FAIL (`KeyError: 'album'`) and ERROR (`AttributeError: 'ListenerCounts' object has no attribute 'cached'`).

- [ ] **Step 3: Implement**

`spotify_assistant/social.py`, replace the `return {...}` of `_play` with:

```python
    album = track.get("album") or {}
    context = item.get("context") or {}
    return {
        "uri": track["uri"],
        "title": track.get("name", ""),
        "artists": [{"id": a.get("id"), "name": a.get("name", "")} for a in track.get("artists", [])],
        "image": pick_image(album.get("images"), 64),
        "duration_ms": track.get("duration_ms") or 0,
        "at": when,
        # For achievements (already in the answer; older plays don't have them).
        "album": {"id": album.get("id"), "name": album.get("name", ""), "type": album.get("album_type"),
                  "release": album.get("release_date"), "tracks": album.get("total_tracks")},
        "track_number": track.get("track_number"),
        "context": {"type": context["type"], "uri": context.get("uri")} if context.get("type") else None,
    }
```

`spotify_assistant/lastfm.py`, in `ListenerCounts`, after `get`:

```python
    def cached(self, artist: str, title: str) -> Listeners | None:
        """What the cache holds, however old; None when the track was never asked about. Never asks Last.fm."""
        with self._lock:
            entry = self._entries().get(cache_key(artist, title))
        return Listeners(entry["n"], entry["url"]) if entry else None
```

- [ ] **Step 4: Run the tests**

Run: `python -m unittest tests.test_social tests.test_lastfm`
Expected: OK.

- [ ] **Step 5: Commit**

```bash
git add spotify_assistant/social.py spotify_assistant/lastfm.py tests/test_social.py tests/test_lastfm.py
git commit -m "Plays keep album, track number and context; cached Last.fm reads"
```

---

### Task 2: The catalog and its names

**Files:**
- Create: `spotify_assistant/medals.py` (copied from the catalog file's "Code" section, with `GAMES` from its games section)
- Create: `spotify_assistant/medal_names.py` (generated)
- Create (scratchpad, not in the repo): `make_medal_names.py`
- Modify: `spotify_assistant/i18n.py` (title texts, game "how", merge of medal names)
- Test: `tests/test_medals.py`

**Interfaces:**
- Produces: `medals.Medal(id, family, rule, params, phase, requires, song)`, `medals.Game(slug, name, names, context, artists)`,
  `medals.MEDALS`, `medals.BY_ID`, `medals.GAMES`, `medals.GAMES_BY_SLUG`, `medals.TITLES`, word lists `LOVE`, `MOON`,
  `SUN`, `WORDS`, `COLLECTIONS`; i18n keys `medal.<id>`, `medal.<id>.how`, `medal.game.how` (`{game}`),
  `title.<id>`, `title.<id>.value` (plural tuple with `{value}`).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_medals.py`:

```python
import re
import unittest

from spotify_assistant import curation, i18n, medals

OWN = [medal for medal in medals.MEDALS if medal.family != "games"]


class CatalogTest(unittest.TestCase):
    def test_at_least_a_hundred_medals_besides_games(self):
        self.assertGreaterEqual(len(OWN), 100)
        self.assertGreaterEqual(len([medal for medal in OWN if medal.requires != "lastfm"]), 100)  # even without a key

    def test_ids_are_unique_and_plain(self):
        ids = [medal.id for medal in medals.MEDALS]
        self.assertEqual(len(ids), len(set(ids)))
        for medal_id in ids:
            self.assertRegex(medal_id, r"^[a-z0-9-]+$")

    def test_every_medal_has_a_name_and_a_how_in_both_languages(self):
        for medal in OWN:
            for lang in i18n.LANGUAGES:
                with self.subTest(medal=medal.id, lang=lang):
                    self.assertTrue(i18n.MESSAGES[lang].get(f"medal.{medal.id}"))
                    self.assertTrue(i18n.MESSAGES[lang].get(f"medal.{medal.id}.how"))
        self.assertEqual(len([key for key in i18n.MESSAGES["en"] if re.fullmatch(r"medal\.[a-z0-9-]+", key)]), len(OWN))

    def test_names_dont_repeat_within_a_language(self):
        for lang in i18n.LANGUAGES:
            names = [i18n.MESSAGES[lang][f"medal.{medal.id}"] for medal in OWN] + [game.name for game in medals.GAMES]
            self.assertEqual(len(names), len(set(names)), lang)

    def test_phases_and_requirements_are_known(self):
        for medal in medals.MEDALS:
            self.assertIn(medal.phase, {"play", "rich", "event", "room", "titles"}, medal.id)
            self.assertIn(medal.requires, {"", "lastfm"}, medal.id)

    def test_titles_have_names_and_numbers(self):
        self.assertEqual(len(medals.TITLES), 8)
        for title in medals.TITLES:
            for lang in i18n.LANGUAGES:
                self.assertIn(f"title.{title}", i18n.MESSAGES[lang])
                self.assertIsInstance(i18n.MESSAGES[lang][f"title.{title}.value"], tuple)

    def test_games_can_be_matched(self):
        self.assertGreaterEqual(len(medals.GAMES), 20)
        self.assertIn("apex-legends", medals.GAMES_BY_SLUG)
        for game in medals.GAMES:
            with self.subTest(game=game.slug):
                self.assertRegex(game.slug, r"^[a-z0-9-]+$")
                self.assertTrue(game.names or game.artists)
                for name in game.names + game.artists:
                    self.assertEqual(name, curation.normalize(name))
                self.assertIn(f"game-{game.slug}", medals.BY_ID)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run them to see them fail**

Run: `python -m unittest tests.test_medals`
Expected: ERROR (`ImportError: cannot import name 'medals'`).

- [ ] **Step 3: Create `spotify_assistant/medals.py`**

Copy the Python block of the catalog file's section "Code: `spotify_assistant/medals.py`" verbatim, then replace
`GAMES: tuple[Game, ...] = ()  # filled from the games section` with the `GAMES` tuple from the catalog's "Games"
section (one `Game(slug, name, names, context, artists)` per row, names and artists already normalized).

- [ ] **Step 4: Generate `spotify_assistant/medal_names.py`**

Write `make_medal_names.py` in the scratchpad:

```python
"""Writes spotify_assistant/medal_names.py from the catalog's tables (names and "how" lines)."""
import json
import re
import sys
from pathlib import Path

repo = Path(sys.argv[1])
catalog = (repo / "docs/superpowers/specs/2026-10-15-achievements-catalog.md").read_text(encoding="utf-8")
section = catalog.split("## Medals", 1)[1].split("## Code", 1)[0]
names = {"pt": {}, "en": {}}
for line in section.splitlines():
    cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
    if len(cells) != 6 or not re.fullmatch(r"[a-z0-9-]+", cells[0]) or cells[0] == "id":
        continue
    medal_id, _, pt, en, how_pt, how_en = cells
    names["pt"][f"medal.{medal_id}"], names["en"][f"medal.{medal_id}"] = pt, en
    names["pt"][f"medal.{medal_id}.how"], names["en"][f"medal.{medal_id}.how"] = how_pt, how_en
lines = [
    '"""Medal names and "how" lines. SPOILERS: generated from docs/superpowers/specs/2026-10-15-achievements-catalog.md.',
    "",
    'i18n merges them into MESSAGES; a "how" line only ever reaches whoever earned the medal.',
    '"""',
    "",
    "NAMES: dict[str, dict[str, str]] = {",
]
for lang in ("pt", "en"):
    lines.append(f'    "{lang}": {{')
    lines += [f"        {json.dumps(key)}: {json.dumps(text, ensure_ascii=False)}," for key, text in names[lang].items()]
    lines.append("    },")
lines.append("}")
(repo / "spotify_assistant/medal_names.py").write_text("\n".join(lines) + "\n", encoding="utf-8")
print(len(names["pt"]) // 2, "medals")
```

Run: `python -I <scratchpad>/make_medal_names.py C:\dev\spotfyprsonal`
Expected: `138 medals`.

- [ ] **Step 5: Titles, the game "how" and the merge in `spotify_assistant/i18n.py`**

Add to `MESSAGES["pt"]` (anywhere inside the dict, e.g. after the Friends messages):

```python
        # Achievements (the medal names come from medal_names.py, merged at the end of this file)
        "medal.game.how": "Ouviu música de {game}.",
        "title.marathoner": "Maratonista",
        "title.alternative": "Mais alternativo",
        "title.explorer": "Explorador",
        "title.night-owl": "Coruja",
        "title.early-bird": "Madrugador",
        "title.duo": "Dupla do mês",
        "title.trendsetter": "Lançador de tendência",
        "title.time-traveler": "Viajante do tempo",
        "title.marathoner.value": ("{value} música", "{value} músicas"),
        "title.alternative.value": ("mediana de {value} fã", "mediana de {value} fãs"),
        "title.explorer.value": ("{value} artista novo", "{value} artistas novos"),
        "title.night-owl.value": ("{value} música de madrugada", "{value} músicas de madrugada"),
        "title.early-bird.value": ("{value} música cedinho", "{value} músicas cedinho"),
        "title.duo.value": ("{value} coincidência", "{value} coincidências"),
        "title.trendsetter.value": ("{value} artista que alguém pegou de você", "{value} artistas que alguém pegou de você"),
        "title.time-traveler.value": ("{value} década", "{value} décadas"),
```

and to `MESSAGES["en"]`:

```python
        # Achievements (the medal names come from medal_names.py, merged at the end of this file)
        "medal.game.how": "Played music from {game}.",
        "title.marathoner": "Marathoner",
        "title.alternative": "Most Alternative",
        "title.explorer": "Explorer",
        "title.night-owl": "Night Owl",
        "title.early-bird": "Early Bird",
        "title.duo": "Duo of the Month",
        "title.trendsetter": "Trendsetter",
        "title.time-traveler": "Time Traveler",
        "title.marathoner.value": ("{value} song", "{value} songs"),
        "title.alternative.value": ("median of {value} fan", "median of {value} fans"),
        "title.explorer.value": ("{value} new artist", "{value} new artists"),
        "title.night-owl.value": ("{value} song after midnight", "{value} songs after midnight"),
        "title.early-bird.value": ("{value} early song", "{value} early songs"),
        "title.duo.value": ("{value} match", "{value} matches"),
        "title.trendsetter.value": ("{value} artist someone picked up from you", "{value} artists someone picked up from you"),
        "title.time-traveler.value": ("{value} decade", "{value} decades"),
```

At the end of `i18n.py`:

```python
# Medal names and "how" lines live apart: they're spoilers (see medal_names.py).
from .medal_names import NAMES as _MEDAL_NAMES  # noqa: E402

for _lang in LANGUAGES:
    MESSAGES[_lang].update(_MEDAL_NAMES[_lang])
```

- [ ] **Step 6: Run the tests**

Run: `python -m unittest tests.test_medals tests.test_i18n`
Expected: OK.

- [ ] **Step 7: Commit**

```bash
git add spotify_assistant/medals.py spotify_assistant/medal_names.py spotify_assistant/i18n.py tests/test_medals.py docs/superpowers/specs/2026-10-15-achievements-catalog.md
git commit -m "Achievements: the catalog and its names (spoilers)"
```

---

### Task 3: Rules: from plays to running numbers and checks

**Files:**
- Create: `spotify_assistant/medal_rules.py`
- Test: `tests/test_medal_rules.py`

**Interfaces:**
- Consumes: `medals.*` (Task 2), `lastfm.Listeners`.
- Produces: `Context(first_name, finds, playlists, listeners, fans)`; `new_stats() -> dict`;
  `update(stats, play, ctx)`; `rich_update(stats, play, ctx)`; `stat_value(stats, name) -> float` (KeyError for
  unknown names); `check(medal, stats, play | None, ctx) -> bool`; `RULES`; `matches_game(game, play) -> bool`;
  helpers `local(at)`, `first_artist(play)`, `artist_key(artist)`, `release(play) -> (year, day | None) | None`,
  `easter(year)`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_medal_rules.py`:

```python
import unittest
from datetime import date, datetime

from spotify_assistant import medal_rules, medals
from spotify_assistant.lastfm import Listeners
from spotify_assistant.medal_rules import Context


def at(year=2026, month=10, day=14, hour=12, minute=0, second=0):
    """A time on the room's clock, as plays store it (2026-10-14 is a Wednesday)."""
    return datetime(year, month, day, hour, minute, second).timestamp()


def play(uri="t", title="Song", artists=("Artist",), when=None, ms=200_000, release="2020-01-01",
         album_name="Album", album_id="al", album_type="album", tracks=10, number=None, context=None):
    return {"uri": f"spotify:track:{uri}", "title": title,
            "artists": [{"id": name.lower().replace(" ", "-"), "name": name} for name in artists],
            "image": None, "duration_ms": ms, "at": at() if when is None else when,
            "album": {"id": album_id, "name": album_name, "type": album_type, "release": release, "tracks": tracks},
            "track_number": number, "context": context}


def earn(plays, ctx=Context(), phase="play", stats=None):
    """Runs plays through the rules like the engine: the medals earned, each with the play that earned it."""
    stats = stats or medal_rules.new_stats()
    earned = {}
    for item in plays:
        (medal_rules.update if phase == "play" else medal_rules.rich_update)(stats, item, ctx)
        for medal in medals.MEDALS:
            if medal.phase == phase and medal.id not in earned and medal_rules.check(medal, stats, item, ctx):
                earned[medal.id] = item
    return earned


class VolumeTest(unittest.TestCase):
    def test_counts_plays_songs_and_artists(self):
        plays = [play(uri=f"s{n}", artists=(f"A{n % 60}",), when=at() + n * 300) for n in range(100)]
        earned = earn(plays)
        self.assertIs(earned["first-play"], plays[0])
        self.assertIs(earned["plays-100"], plays[99])
        self.assertIs(earned["artists-50"], plays[49])
        self.assertNotIn("songs-500", earned)

    def test_hours_add_durations(self):
        plays = [play(uri=f"s{n}", ms=3_600_000, when=at(day=1) + n * 3600) for n in range(24)]
        self.assertIs(earn(plays)["hours-24"], plays[23])


class DayTest(unittest.TestCase):
    def test_a_day_starts_at_midnight(self):
        late = [play(uri=f"a{n}", when=at(hour=23, minute=10) + n * 60) for n in range(30)]
        early = [play(uri=f"b{n}", when=at(day=15, hour=0, minute=1) + n * 60) for n in range(30)]
        self.assertNotIn("day-plays-50", earn(late + early))
        more = [play(uri=f"c{n}", when=at(hour=23, minute=40) + n) for n in range(20)]
        self.assertIn("day-plays-50", earn(late + more))

    def test_repeats_parts_and_clock_hours(self):
        self.assertIn("day-repeat-10", earn([play(uri="hit", when=at(hour=10) + n * 240) for n in range(10)]))
        parts = [play(uri=f"p{hour}", when=at(hour=hour)) for hour in (2, 8, 14, 20)]
        self.assertIn("day-parts", earn(parts))
        self.assertNotIn("day-clock-12", earn(parts))
        self.assertIn("day-clock-12", earn([play(uri=f"h{hour}", when=at(hour=hour)) for hour in range(12)]))

    def test_decades_in_one_day(self):
        years = (1965, 1975, 1985, 1995, 2005)
        self.assertIn("day-decades-5", earn([play(uri=f"d{y}", release=f"{y}-01-01", when=at() + n)
                                             for n, y in enumerate(years)]))


class StreakTest(unittest.TestCase):
    def test_days_in_a_row_and_breaks(self):
        self.assertIn("streak-7", earn([play(uri=f"w{d}", when=at(day=1 + d)) for d in range(7)]))
        self.assertNotIn("streak-7", earn([play(uri=f"w{d}", when=at(day=1 + d)) for d in (0, 1, 2, 4, 5, 6, 7)]))

    def test_coming_back_after_two_weeks(self):
        self.assertNotIn("comeback", earn([play(when=at(day=1)), play(when=at(day=14))]))
        self.assertIn("comeback", earn([play(when=at(day=1)), play(when=at(day=15, hour=13))]))

    def test_weekends_in_a_row(self):
        weekends = [play(uri=f"{w}{d}", when=at(day=3 + 7 * w + d)) for w in range(4) for d in (0, 1)]  # Oct 3 is a Saturday
        self.assertIn("weekends-4", earn(weekends))
        self.assertNotIn("weekends-4", earn(weekends[:6] + [play(when=at(day=31))]))


class ClockTest(unittest.TestCase):
    def test_moments(self):
        cases = {"midnight": at(hour=0, minute=0, second=30), "three-am": at(hour=3, minute=59),
                 "sunrise": at(hour=5, minute=29), "christmas": at(month=12, day=25), "music-day": at(month=6, day=21),
                 "friday-13": at(month=2, day=13), "carnival": at(month=2, day=17),
                 "leap-day": at(year=2028, month=2, day=29), "new-year": at(month=12, day=31, hour=23, minute=55)}
        for medal_id, when in cases.items():
            with self.subTest(medal=medal_id):
                self.assertIn(medal_id, earn([play(when=when)]))
        self.assertIn("new-year", earn([play(when=at(year=2027, month=1, day=1, hour=0, minute=10))]))
        self.assertNotIn("midnight", earn([play(when=at(hour=0, minute=1))]))
        self.assertNotIn("carnival", earn([play(when=at(month=2, day=18))]))  # Ash Wednesday

    def test_words_on_their_day(self):
        self.assertIn("lovebirds", earn([play(title="Meu Amor", when=at(month=6, day=12))]))
        self.assertNotIn("lovebirds", earn([play(title="Meu Amor", when=at(month=6, day=13))]))
        self.assertIn("halloween", earn([play(title="Ghost Town", when=at(month=10, day=31))]))
        self.assertIn("monday-song", earn([play(title="Manic Monday", when=at(day=12))]))
        self.assertIn("friday-song", earn([play(title="Sextou", when=at(day=16))]))

    def test_a_hundred_nights(self):
        plays = [play(uri=f"n{n}", when=at(day=1 + n // 10, hour=1, minute=n % 10)) for n in range(100)]
        self.assertIn("night-100", earn(plays))

    def test_easter(self):
        self.assertEqual(medal_rules.easter(2026), date(2026, 4, 5))
        self.assertEqual(medal_rules.easter(2027), date(2027, 3, 28))


class ReleaseTest(unittest.TestCase):
    def test_old_records(self):
        self.assertTrue({"before-1970", "before-1950", "before-1930"} <= set(earn([play(release="1929-05-01")])))
        self.assertNotIn("before-1930", earn([play(release="1930")]))
        self.assertNotIn("before-1970", earn([play(release="")]))  # no date: never counts

    def test_release_days(self):
        self.assertIn("same-day", earn([play(release="2026-10-14")]))
        self.assertNotIn("same-day", earn([play(release="2026-10")]))
        self.assertIn("anniversary", earn([play(release="1999-10-14")]))
        self.assertNotIn("anniversary", earn([play(release="2026-10-14")]))
        self.assertIn("fifty-years", earn([play(release="1976")]))

    def test_every_decade(self):
        plays = [play(uri=f"d{y}", release=str(y), when=at() + n) for n, y in enumerate(range(1955, 2035, 10))]
        self.assertIn("decades-all", earn(plays))
        self.assertNotIn("decades-all", earn(plays[1:]))


class RunTest(unittest.TestCase):
    def test_same_artist_different_artists_same_song(self):
        self.assertIn("same-artist-10", earn([play(uri=f"s{n}", artists=("Banda",), when=at() + n * 200)
                                              for n in range(10)]))
        diverse = [play(uri=f"d{n}", artists=(f"A{n}",), when=at() + n * 200) for n in range(20)]
        self.assertIn("diverse-20", earn(diverse))
        broken = diverse[:10] + [play(uri="x", artists=("A3",), when=at() + 2000)] + \
            [play(uri=f"e{n}", artists=(f"B{n}",), when=at() + 2200 + n * 200) for n in range(9)]
        self.assertNotIn("diverse-20", earn(broken))
        self.assertIn("same-song-3", earn([play(uri="loop", when=at() + n * 200) for n in range(3)]))

    def test_nonstop_hours(self):
        plays = [play(uri=f"n{n}", ms=600_000, when=at(hour=8) + n * 600) for n in range(18)]
        self.assertIn("nonstop-3h", earn(plays))
        gap = plays[:9] + [play(uri=f"g{n}", ms=600_000, when=at(hour=11) + n * 600) for n in range(9)]
        self.assertNotIn("nonstop-3h", earn(gap))

    def test_lengths_and_credits(self):
        self.assertIn("long-song-10", earn([play(ms=600_000)]))
        self.assertNotIn("long-song-20", earn([play(ms=600_000)]))
        self.assertIn("short-song", earn([play(ms=45_000)]))
        self.assertIn("crowd", earn([play(artists=("A", "B", "C", "D"))]))
        self.assertIn("short-run-10", earn([play(uri=f"q{n}", ms=90_000, when=at() + n * 100) for n in range(10)]))

    def test_a_whole_album_in_order(self):
        album = [play(uri=f"t{n}", number=n, tracks=6, when=at() + n * 300) for n in range(1, 7)]
        self.assertIn("album-full", earn(album))
        self.assertNotIn("album-full", earn(album[:3] + album[4:]))  # a track skipped
        five = [play(uri=f"t{n}", number=n, tracks=5, when=at() + n * 300) for n in range(1, 6)]
        self.assertNotIn("album-full", earn(five))
        long = [play(uri=f"l{n}", number=n, tracks=15, album_id="dbl", when=at() + n * 300) for n in range(1, 16)]
        self.assertIn("album-full-long", earn(long))

    def test_the_panels_own_finds_and_playlists(self):
        ctx = Context(finds=frozenset({"spotify:track:found"}), playlists=frozenset({"spotify:playlist:fav"}))
        hooked = [play(uri="found", when=at() + n * 300) for n in range(3)]
        self.assertIn("hooked", earn(hooked, ctx))
        self.assertNotIn("hooked", earn(hooked[:2], ctx))
        from_fav = play(context={"type": "playlist", "uri": "spotify:playlist:fav"})
        self.assertIn("panel-playlist", earn([from_fav], ctx))
        self.assertNotIn("panel-playlist", earn([from_fav]))
        made = medal_rules.new_stats()
        made["made"]["spotify:playlist:fav"] = 1
        self.assertIn("panel-playlist", earn([from_fav], stats=made))


class WordsTest(unittest.TestCase):
    def titles(self, titles):
        return [play(uri=f"w{n}", title=title, when=at() + n) for n, title in enumerate(titles)]

    def test_collections(self):
        rainbow = ["Red", "Laranja Mecânica", "Yellow", "Verde", "Blue Monday", "Indigo", "Purple Rain"]
        self.assertIn("rainbow", earn(self.titles(rainbow)))
        self.assertNotIn("rainbow", earn(self.titles(rainbow[:6])))
        week = ["Manic Monday", "Ruby Tuesday", "Wednesday Morning", "Thursday", "Friday I'm in Love",
                "Saturday Night", "Sunday Bloody Sunday"]
        self.assertIn("weekdays", earn(self.titles(week)))
        self.assertIn("seasons", earn(self.titles(["Spring", "Verão", "Autumn Leaves", "Winter"])))
        numbers = ["One", "Two", "Três", "Four", "Cinco", "Six", "Seven", "Oito", "Nine", "Ten"]
        self.assertIn("numbers", earn(self.titles(numbers)))
        self.assertIn("places-5", earn(self.titles(["Rio", "Paris", "Tokyo Drift", "London Calling", "Bahia"])))
        letters = [play(uri=f"l{n}", artists=(f"{chr(97 + n)}band",), when=at() + n) for n in range(20)]
        self.assertIn("alphabet-20", earn(letters))
        self.assertNotIn("alphabet-26", earn(letters))

    def test_single_songs(self):
        self.assertIn("saudade", earn([play(title="Saudades de Casa")]))
        self.assertIn("long-title", earn([play(title="One Two Three Four Five Six Seven Eight Nine Ten")]))
        self.assertNotIn("long-title", earn([play(title="One Two Three (Live at Some Very Long Venue Name)")]))
        self.assertIn("self-titled", earn([play(title="Bad Company", artists=("Bad Company",))]))
        self.assertIn("title-track", earn([play(title="Kind of Blue", album_name="Kind of Blue (Legacy Edition)")]))
        self.assertNotIn("title-track", earn([play(title="Single", album_name="Single", album_type="single")]))
        self.assertIn("digit-artist", earn([play(artists=("2Pac",))]))
        self.assertIn("namesake", earn([play(artists=("Paulo Ricardo",))], Context(first_name="paulo")))
        self.assertNotIn("namesake", earn([play(artists=("Paulinho",))], Context(first_name="paulo")))
        self.assertNotIn("namesake", earn([play(artists=("Al Green",))], Context(first_name="al")))  # too short

    def test_specific_artists_and_songs(self):
        self.assertIn("linkin-paulo", earn([play(artists=("Steve Aoki", "Linkin Park"))]))
        self.assertIn("apex-predator", earn([play(title="You Are The Jumpmaster", artists=("Stephen Barton",))]))
        self.assertIn("rickroll", earn([play(title="Never Gonna Give You Up - 2022 Remaster", artists=("Rick Astley",))]))
        self.assertNotIn("rickroll", earn([play(title="Never Gonna Give You Up", artists=("Cover Band",))]))
        self.assertIn("ipanema", earn([play(title="Garota de Ipanema", artists=("Tom Jobim",))]))


class GameTest(unittest.TestCase):
    def test_name_with_a_hint_or_the_games_own_artist(self):
        halo = medals.Game("halo", "Halo", ("halo",), context=True, artists=("halo",))
        self.assertTrue(medal_rules.matches_game(halo, play(title="Finish the Fight", artists=("Martin O'Donnell",),
                                                            album_name="Halo 3 (Original Soundtrack)")))
        self.assertFalse(medal_rules.matches_game(halo, play(title="Halo", artists=("Beyoncé",),
                                                             album_name="I Am... Sasha Fierce")))
        self.assertTrue(medal_rules.matches_game(halo, play(title="Heroes", artists=("Halo",), album_name="Infinite")))
        self.assertFalse(medal_rules.matches_game(halo, play(title="Halo (Original Mix)", artists=("DJ X",))))
        apex = medals.Game("apex-legends", "Apex Legends", ("apex legends",))
        self.assertTrue(medal_rules.matches_game(apex, play(title='Main Theme (From "Apex Legends")')))
        self.assertFalse(medal_rules.matches_game(apex, play(title="Apex", album_name="Legends")))

    def test_every_game_medal_works_end_to_end(self):
        for game in medals.GAMES:
            with self.subTest(game=game.slug):
                hint = f"{game.names[0]} original soundtrack" if game.names else "x"
                credit = (game.artists[0],) if game.artists else ("Someone",)
                self.assertIn(f"game-{game.slug}", earn([play(album_name=hint, artists=credit)]))


class RichTest(unittest.TestCase):
    def ctx(self, listeners=None, fans=None):
        return Context(listeners=lambda item: listeners, fans=lambda item: fans)

    def test_rare_songs_need_a_record(self):
        rare = earn([play()], self.ctx(Listeners(40, "u")), phase="rich")
        self.assertTrue({"rare-1000", "rare-100", "rare-50"} <= set(rare))
        self.assertNotIn("rare-10", rare)
        self.assertEqual(earn([play()], self.ctx(Listeners(None, None)), phase="rich"), {})
        self.assertIn("megahit", earn([play()], self.ctx(Listeners(3_000_000, "u")), phase="rich"))

    def test_collecting_different_rare_songs(self):
        ctx = self.ctx(Listeners(99, None))
        self.assertIn("rare-collect-10", earn([play(uri=f"r{n}", when=at() + n) for n in range(10)], ctx, "rich"))
        self.assertNotIn("rare-collect-10", earn([play(uri="same", when=at() + n) for n in range(10)], ctx, "rich"))

    def test_artist_size(self):
        self.assertTrue({"fans-1000", "fans-100"} <= set(earn([play()], self.ctx(fans=50), phase="rich")))
        self.assertIn("giant", earn([play()], self.ctx(fans=20_000_000), phase="rich"))
        self.assertEqual(earn([play()], self.ctx(fans=None), phase="rich"), {})

    def test_basement_to_stadium_in_one_day(self):
        ctx = Context(fans=lambda item: {"spotify:track:small": 500, "spotify:track:big": 20_000_000}[item["uri"]])
        same_day = [play(uri="small", when=at(hour=9)), play(uri="big", when=at(hour=21))]
        self.assertIn("day-extremes", earn(same_day, ctx, "rich"))
        apart = [play(uri="small", when=at(hour=23)), play(uri="big", when=at(day=15, hour=1))]
        self.assertNotIn("day-extremes", earn(apart, ctx, "rich"))


class NumbersTest(unittest.TestCase):
    def test_titles_won(self):
        stats = medal_rules.new_stats()
        stats["titles"] = [{"month": "2026-11", "title": "duo"}, {"month": "2026-12", "title": "duo"},
                           {"month": "2027-01", "title": "duo"}, {"month": "2027-01", "title": "explorer"}]
        values = [medal_rules.stat_value(stats, f"titles:{key}") for key in ("count", "kinds", "double", "streak")]
        self.assertEqual(values, [4, 2, 2, 3])

    def test_every_medal_names_a_rule_and_a_known_number(self):
        for medal in medals.MEDALS:
            with self.subTest(medal=medal.id):
                self.assertIn(medal.rule, medal_rules.RULES)
                if medal.rule == "total":
                    medal_rules.stat_value(medal_rules.new_stats(), medal.params["stat"])
        with self.assertRaises(KeyError):
            medal_rules.stat_value(medal_rules.new_stats(), "nonsense")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run them to see them fail**

Run: `python -m unittest tests.test_medal_rules`
Expected: ERROR (`ImportError: cannot import name 'medal_rules'`).

- [ ] **Step 3: Implement `spotify_assistant/medal_rules.py`**

```python
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
    """(year, day) of the play's release; the day is None when Spotify only gives the year or the month."""
    text = (play.get("album") or {}).get("release") or ""
    if len(text) < 4 or not text[:4].isdigit():
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
    """Tracks 1..N of one album, one after another, N being the album's total."""
    album = play.get("album") or {}
    number, total = play.get("track_number"), album.get("tracks")
    state = stats["album"]
    if not album.get("id") or not number or not total:
        state.clear()
        return
    if number == 1:
        state.clear()
        state.update(id=album["id"], next=2)
    elif state.get("id") == album["id"] and state.get("next") == number:
        state["next"] = number + 1
    else:
        state.clear()
        return
    if state["next"] == total + 1:
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
```

- [ ] **Step 4: Run the tests**

Run: `python -m unittest tests.test_medal_rules tests.test_medals`
Expected: OK.

- [ ] **Step 5: Commit**

```bash
git add spotify_assistant/medal_rules.py tests/test_medal_rules.py
git commit -m "Achievements: the rules that turn plays into medals"
```

---

### Task 4: Each person's achievements: joining, plays, panel events, privacy

**Files:**
- Create: `spotify_assistant/achievements.py`
- Test: `tests/test_achievements.py`

**Interfaces:**
- Consumes: `medal_rules.*` (Task 3), `medals.*` (Task 2), `social.sharing/allowed`, `favorites.load/recent`,
  `reviews.mine`, `accounts.display_name`, `lastfm.ListenerCounts.cached` (Task 1).
- Produces: `Unreadable`; `load(user_id) -> dict`; `taking_part(user_id) -> bool`; `participants() -> list[str]`;
  `set_on(user_id, on, now=None)`; `forget(user_id)`; `available(lastfm) -> list[Medal]`;
  `medal_texts(medal_id) -> (name, how)`; `context(user_id, counts, fans) -> Context`;
  `process(user_id, plays, ctx, lastfm) -> list[str]`; `note(user_id, event, lastfm=False, **detail) -> list[str]`;
  `mark_seen(user_id, ids)`; `set_highlights(user_id, ids)`; `summary(user_id, lastfm) -> {"on", "new"}`;
  `highlights_of(user_id, lastfm) -> list[{"id", "name"}]`; `view(viewer, lastfm, fans, now=None) -> dict`;
  `MAX_HIGHLIGHTS = 10`. Later tasks add `ArtistFans`, `enrich`, `rich_pass` (Task 5), `room_pass`, `close_month`
  and the race in `view` (Task 6).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_achievements.py`:

```python
import json
import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from spotify_assistant import achievements, config, i18n, medals, reviews, social
from spotify_assistant.medal_rules import Context
from tests.test_medal_rules import at, play


def no_fans(name):
    return None


class Room(unittest.TestCase):
    """Three people in a temporary room: paulo (the owner), ana and bia."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.data = Path(tmp.name)
        patcher = mock.patch.object(config, "DATA_DIR", self.data)
        patcher.start()
        self.addCleanup(patcher.stop)
        (self.data / "owner.txt").write_text("paulo", encoding="utf-8")
        for user_id in ("paulo", "ana", "bia"):
            folder = self.data / "users" / user_id
            folder.mkdir(parents=True)
            (folder / "token.json").write_text("{}", encoding="utf-8")
            (folder / "profile.json").write_text(json.dumps({"name": user_id.title()}), encoding="utf-8")

    def join(self, *people):
        for user_id in people:
            social.set_share(user_id, True)
            achievements.set_on(user_id, True, now=at(day=1))

    def save_plays(self, user_id, plays):
        (self.data / "users" / user_id / "plays.json").write_text(json.dumps(plays), encoding="utf-8")


class ParticipationTest(Room):
    def test_joining_counts_the_history_already_collected(self):
        social.set_share("paulo", True)
        history = [play(uri=f"s{n}", when=at(day=1) + n * 300) for n in range(100)]
        achievements.set_on("paulo", True, now=at(day=14))
        self.assertIn("plays-100", achievements.process("paulo", history, Context(), lastfm=False))
        self.assertEqual(achievements.load("paulo")["earned"]["plays-100"]["song"]["uri"], history[99]["uri"])
        self.assertEqual(achievements.load("paulo")["through"], history[-1]["at"])
        self.assertEqual(achievements.process("paulo", history, Context(), lastfm=False), [])  # nothing twice
        self.assertEqual(achievements.load("paulo")["stats"]["plays"], 100)

    def test_back_after_leaving_skips_what_was_played_meanwhile(self):
        self.join("paulo")
        achievements.process("paulo", [play(when=at(day=1, hour=13))], Context(), False)
        achievements.set_on("paulo", False)
        self.assertEqual(achievements.process("paulo", [play(uri="x", when=at(day=2))], Context(), False), [])
        achievements.set_on("paulo", True, now=at(day=3))
        achievements.process("paulo", [play(uri="x", when=at(day=2)), play(uri="y", when=at(day=4))], Context(), False)
        self.assertEqual(achievements.load("paulo")["stats"]["plays"], 2)  # day 1 and day 4

    def test_only_people_in_friends_take_part(self):
        achievements.set_on("ana", True)
        self.assertFalse(achievements.taking_part("ana"))  # not sharing in Friends
        social.set_share("ana", True)
        self.assertTrue(achievements.taking_part("ana"))
        self.assertEqual(achievements.participants(), ["ana"])

    def test_erase_removes_the_file_and_past_titles(self):
        self.join("paulo", "ana")
        room = {"since": "2026-09", "months": {"2026-09": {"duo": {"users": ["ana", "paulo"], "value": 3},
                                                           "explorer": {"users": ["ana"], "value": 9}}}}
        (self.data / "achievements.json").write_text(json.dumps(room), encoding="utf-8")
        achievements.forget("ana")
        self.assertFalse((self.data / "users" / "ana" / "achievements.json").exists())
        months = json.loads((self.data / "achievements.json").read_text(encoding="utf-8"))["months"]
        self.assertEqual(months["2026-09"], {"duo": {"users": ["paulo"], "value": 3}})

    def test_an_unreadable_file_is_left_alone(self):
        self.join("paulo")
        path = self.data / "users" / "paulo" / "achievements.json"
        path.write_text("{oops", encoding="utf-8")
        with self.assertRaises(achievements.Unreadable):
            achievements.process("paulo", [play()], Context(), False)
        self.assertEqual(achievements.note("paulo", "block"), [])
        self.assertFalse(achievements.taking_part("paulo"))
        self.assertEqual(path.read_text(encoding="utf-8"), "{oops")


class EventsTest(Room):
    def test_panel_events_count_for_participants_only(self):
        self.assertEqual(achievements.note("ana", "hunt", kind="roulette"), [])
        self.assertFalse((self.data / "users" / "ana" / "achievements.json").exists())  # nothing kept for outsiders
        self.join("ana")
        self.assertEqual(achievements.note("ana", "hunt", kind="roulette", rare=True), ["roulette-1", "roulette-rare"])
        for kind in ("sense", "rabbit"):
            achievements.note("ana", "hunt", kind=kind)
        self.assertIn("all-discoveries", achievements.note("ana", "hunt", kind="news"))
        self.assertIsNone(achievements.load("ana")["earned"]["roulette-1"]["song"])

    def test_the_listener_cap_medal_needs_the_key(self):
        self.join("ana")
        self.assertNotIn("listeners-tight", achievements.note("ana", "hunt", kind="roulette", listeners=50))
        self.assertIn("listeners-tight", achievements.note("ana", "hunt", kind="roulette", listeners=50, lastfm=True))

    def test_review_medals_follow_the_reviews(self):
        self.join("ana")
        reviews.save("ana", {"id": "a" * 22, "name": "Kind of Blue"}, 5, "x" * 500, True)
        self.assertEqual(achievements.note("ana", "review"), ["review-1", "review-five", "review-long"])

    def test_playlists_made_in_the_panel_count_for_later_plays(self):
        self.join("ana")
        achievements.note("ana", "playlist", uri="spotify:playlist:p1")
        from_it = play(context={"type": "playlist", "uri": "spotify:playlist:p1"})
        self.assertIn("panel-playlist", achievements.process("ana", [from_it], Context(), False))


class ViewTest(Room):
    def setUp(self):
        super().setUp()
        self.join("paulo", "ana")
        achievements.process("paulo", [play(title="Saudade")], Context(), False)

    def view(self, user_id):
        return achievements.view(user_id, False, no_fans, now=at())

    def test_outsiders_see_nothing(self):
        self.assertEqual(self.view("bia"), {"sharing": False, "on": False})
        social.set_share("bia", True)
        self.assertEqual(self.view("bia"), {"sharing": True, "on": False})

    def test_how_only_for_whoever_earned_it(self):
        saudade = next(medal for medal in self.view("paulo")["me"]["medals"] if medal["id"] == "saudade")
        self.assertEqual(saudade["how"], i18n.t("medal.saudade.how"))
        self.assertEqual(saudade["song"]["title"], "Saudade")
        paulo = next(person for person in self.view("ana")["people"] if person["id"] == "paulo")
        shown = next(medal for medal in paulo["medals"] if medal["id"] == "saudade")
        self.assertNotIn("how", shown)
        self.assertEqual(shown["holders"], 1)

    def test_a_medal_nobody_earned_never_shows(self):
        seen = self.view("ana")
        earned = set(achievements.load("paulo")["earned"]) | set(achievements.load("ana")["earned"])
        ids = set(re.findall(r'"id": "([a-z0-9-]+)"', json.dumps(seen))) - {"paulo", "ana"} - set(medals.TITLES)
        self.assertLessEqual(ids, earned)
        self.assertEqual(seen["total"], len([medal for medal in medals.MEDALS if medal.requires != "lastfm"]))

    def test_new_until_seen_and_highlights(self):
        self.assertIn("saudade", self.view("paulo")["new"])
        achievements.mark_seen("paulo", list(achievements.load("paulo")["earned"]) + ["rare-10"])
        self.assertEqual(self.view("paulo")["new"], [])
        self.assertNotIn("rare-10", achievements.load("paulo")["seen"])
        achievements.set_highlights("paulo", ["saudade", "rare-10", "saudade"])
        self.assertEqual(achievements.load("paulo")["highlights"], ["saudade"])
        self.assertEqual([medal["id"] for medal in self.view("ana")["people"][0]["highlights"]], ["saudade"])
        self.assertEqual(achievements.highlights_of("paulo", False), [{"id": "saudade", "name": i18n.t("medal.saudade")}])
        self.assertEqual(achievements.summary("paulo", False), {"on": True, "new": 0})

    def test_people_who_leave_disappear(self):
        achievements.set_on("paulo", False)
        self.assertEqual(self.view("ana")["people"], [])
        self.assertEqual(achievements.highlights_of("paulo", False), [])
        self.assertEqual(achievements.summary("paulo", False), {"on": False, "new": 0})


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run them to see them fail**

Run: `python -m unittest tests.test_achievements`
Expected: ERROR (`ImportError: cannot import name 'achievements'`).

- [ ] **Step 3: Implement `spotify_assistant/achievements.py`**

```python
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
    """What the tab shows `viewer` (someone allowed in Friends). Only participants get more than the switch.
    `fans(name)` gives cached artist fans (the month's race needs them)."""
    now = time.time() if now is None else now
    mine = load(viewer)
    sharing = social.sharing(viewer)
    if not (mine["on"] and sharing):
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
```

- [ ] **Step 4: Run the tests**

Run: `python -m unittest tests.test_achievements tests.test_medal_rules tests.test_medals`
Expected: OK.

- [ ] **Step 5: Commit**

```bash
git add spotify_assistant/achievements.py tests/test_achievements.py
git commit -m "Achievements: joining, plays, panel events and what each person sees"
```

---

### Task 5: Last.fm and fans lookups, and the rich pass

**Files:**
- Modify: `spotify_assistant/achievements.py` (add `ArtistFans`, `enrich`, `rich_pass`)
- Test: `tests/test_achievements.py` (add `LookupTest`)

**Interfaces:**
- Consumes: `Deezer.search_artist(name) -> dict | None`, `ListenerCounts.get/cached`, `LastFmError`, `DeezerError`.
- Produces: `ArtistFans(path=None, now=time.time)` with `known(name) -> bool`, `cached(name) -> int | None`,
  `get(dz, name) -> int | None`, `save()`; `enrich(plays, after, counts, fans, dz, budget=LOOKUPS_PER_LOOP)`;
  `rich_pass(user_id, plays, ctx, lastfm, counts, fans) -> list[str]`; `LOOKUPS_PER_LOOP = 300`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_achievements.py` (before `if __name__`), and add these imports at the top:
`from spotify_assistant.deezer import DeezerError` and `from spotify_assistant.lastfm import LastFmError, Listeners`.

```python
class FakeCounts:
    """Last.fm with a cache: titles it knows have listeners, others no record."""

    def __init__(self, listeners=None, error=None):
        self.listeners, self.error, self.asked, self.known = listeners or {}, error, [], {}

    def cached(self, artist, title):
        return self.known.get((artist, title))

    def get(self, artist, title, fresh_s=None):
        self.asked.append((artist, title))
        if self.error:
            raise LastFmError(self.error)
        self.known[(artist, title)] = Listeners(self.listeners.get(title), None)
        return self.known[(artist, title)]


class FakeDeezer:
    def __init__(self, fans=None, error=False):
        self.fans, self.error, self.asked = fans or {}, error, []

    def search_artist(self, name):
        self.asked.append(name)
        if self.error:
            raise DeezerError("down")
        return {"nb_fan": self.fans[name]} if name in self.fans else None


class LookupTest(Room):
    def fans(self):
        return achievements.ArtistFans(path=self.data / "fans.json")

    def plays(self, count):
        return [play(uri=f"s{n}", title=f"Song {n}", artists=(f"A{n}",), when=at() + n) for n in range(count)]

    def test_artist_fans_are_asked_once_and_kept(self):
        dz, fans = FakeDeezer({"Banda": 500}), self.fans()
        self.assertFalse(fans.known("Banda"))
        self.assertEqual((fans.get(dz, "Banda"), fans.get(dz, "BANDA "), fans.get(dz, "Ninguém")), (500, 500, None))
        fans.save()
        again = self.fans()
        self.assertTrue(again.known("Ninguém"))
        self.assertEqual((again.cached("Ninguém"), again.cached("banda")), (None, 500))
        self.assertEqual(dz.asked, ["Banda", "Ninguém"])

    def test_lookups_are_capped_per_loop(self):
        counts, dz, fans = FakeCounts(), FakeDeezer(), self.fans()
        achievements.enrich(self.plays(5), 0, counts, fans, dz, budget=3)
        self.assertEqual((len(counts.asked), len(dz.asked)), (3, 3))
        achievements.enrich(self.plays(5), 0, counts, fans, dz, budget=3)
        self.assertEqual((len(counts.asked), len(dz.asked)), (5, 5))  # the next loop goes on from there

    def test_a_failure_stops_only_that_kind_of_lookup(self):
        counts, dz = FakeCounts(error="down"), FakeDeezer()
        achievements.enrich(self.plays(5), 0, counts, self.fans(), dz)
        self.assertEqual((len(counts.asked), len(dz.asked)), (1, 5))
        counts, dz = FakeCounts(), FakeDeezer(error=True)
        achievements.enrich(self.plays(5), 0, counts, self.fans(), dz)
        self.assertEqual((len(counts.asked), len(dz.asked)), (5, 1))

    def test_rich_medals_wait_for_their_numbers(self):
        self.join("paulo")
        plays = [play(uri="a", title="Rara", artists=("Pequena",), when=at()),
                 play(uri="b", title="Outra", artists=("Grande",), when=at() + 300)]
        counts, dz, fans = FakeCounts({"Rara": 30, "Outra": 5000}), FakeDeezer({"Pequena": 50, "Grande": 20_000_000}), self.fans()
        ctx = achievements.context("paulo", counts, fans)
        achievements.enrich(plays, 0, counts, fans, dz, budget=1)  # only the first play's numbers
        new = achievements.rich_pass("paulo", plays, ctx, True, counts, fans)
        self.assertIn("rare-50", new)
        self.assertNotIn("giant", new)
        data = achievements.load("paulo")
        self.assertEqual(data["rich_through"], plays[0]["at"])
        self.assertEqual(data["earned"]["rare-50"]["lastfm"], {"listeners": 30, "url": None})
        self.assertEqual(data["earned"]["rare-50"]["song"]["title"], "Rara")
        achievements.enrich(plays, data["rich_through"], counts, fans, dz)
        self.assertIn("giant", achievements.rich_pass("paulo", plays, ctx, True, counts, fans))

    def test_without_a_key_there_are_no_rare_medals(self):
        self.join("paulo")
        dz, fans = FakeDeezer({"Pequena": 50}), self.fans()
        plays = [play(artists=("Pequena",))]
        achievements.enrich(plays, 0, None, fans, dz)
        new = achievements.rich_pass("paulo", plays, achievements.context("paulo", None, fans), False, None, fans)
        self.assertIn("fans-100", new)
        self.assertFalse(any(medal_id.startswith("rare") for medal_id in new))

    def test_a_blank_credit_is_not_looked_up(self):
        counts, dz = FakeCounts(), FakeDeezer()
        achievements.enrich([play(artists=("\xa0, \xa0",))], 0, counts, self.fans(), dz)
        self.assertEqual((counts.asked, dz.asked), ([], []))
```

- [ ] **Step 2: Run them to see them fail**

Run: `python -m unittest tests.test_achievements.LookupTest`
Expected: ERROR (`AttributeError: module 'spotify_assistant.achievements' has no attribute 'ArtistFans'`).

- [ ] **Step 3: Implement**

In `spotify_assistant/achievements.py`, add imports `import unicodedata`, `from typing import Callable`,
`from .deezer import Deezer, DeezerError`, and extend `from .lastfm import ListenerCounts` to
`from .lastfm import LastFmError, ListenerCounts`. Add constants after `MAX_HIGHLIGHTS`:

```python
LOOKUPS_PER_LOOP = 300  # Last.fm and fans lookups of each kind per person per loop; the rest wait for the next one
FANS_FILE = "fans-cache.json"
FANS_FRESH_S = 30 * 86400
FANS_MAX_ENTRIES = 100_000
```

and, after `process`:

```python
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
        if going["fans"] and not fans.known(name):
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
              fans: ArtistFans) -> list[str]:
    """Plays whose numbers are known, in order, into the "rich" medals; stops at the first play still waiting."""
    with _lock:
        data = load(user_id)
        if not data["on"]:
            return []
        pending = _pending(data, "rich", lastfm)
        new, last = [], None
        for item in sorted(plays, key=lambda item: item["at"]):
            if item["at"] <= data["rich_through"]:
                continue
            name = _artist_name(item)
            if name and ((counts is not None and counts.cached(name, item["title"]) is None) or not fans.known(name)):
                break  # its numbers aren't known yet: the next loop picks up from here
            medal_rules.rich_update(data["stats"], item, ctx)
            new += _award_due(data, pending, item, ctx, item["at"])
            last = item["at"]
        if last is not None:
            data["rich_through"] = last
            _write(_file(user_id), data)
        return new
```

- [ ] **Step 4: Run the tests**

Run: `python -m unittest tests.test_achievements`
Expected: OK.

- [ ] **Step 5: Commit**

```bash
git add spotify_assistant/achievements.py tests/test_achievements.py
git commit -m "Achievements: Last.fm and fans lookups in the background"
```

---

### Task 6: Matches between participants and the monthly titles

**Files:**
- Create: `spotify_assistant/monthly.py`
- Modify: `spotify_assistant/achievements.py` (add `room_pass`, `close_month`, race and months in `view`)
- Test: `tests/test_achievements.py` (add `RoomTest`, `StandingsTest`, `CloseMonthTest`)

**Interfaces:**
- Consumes: `medal_rules.local/release/first_artist`, `medals.TITLES`, `social.MATCH_WINDOW_S`, `social.MATCH_DAYS`.
- Produces: `monthly.month_of(at) -> "YYYY-MM"`, `monthly.previous_month(at)`, `monthly.picked_up(mine, theirs) -> list[str]`,
  `monthly.standings(month, plays_by_user, firsts_by_user, fans) -> {title: {"users": [...], "value": number}}`,
  `monthly.MIN_PLAYS = 50`; `achievements.room_pass(plays_by_user, lastfm, now=None) -> {user: [ids]}`;
  `achievements.close_month(plays_by_user, fans, lastfm, now=None) -> str | None`; `view(...)["race"]` and
  `["months"]` as lists of `{"id", "name", "holders": [names], "value": text}` (months: `{"month", "titles"}`).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_achievements.py` (and `from spotify_assistant import monthly` at the top):

```python
class RoomTest(Room):
    def test_matches_between_participants(self):
        self.join("paulo", "ana", "bia")
        plays = {"paulo": [play(uri="x", when=at(hour=10)), play(uri="y", when=at(hour=11))],
                 "ana": [play(uri="x", when=at(hour=10, minute=3))],
                 "bia": [play(uri="y", when=at(hour=15))]}
        new = achievements.room_pass(plays, False, now=at(hour=20))
        self.assertTrue({"match-1", "match-sync", "match-everyone"} <= set(new["paulo"]))
        self.assertTrue({"match-1", "match-sync"} <= set(new["ana"]))
        self.assertNotIn("match-everyone", new["ana"])  # Ana and Bia never matched
        self.assertEqual(set(new["bia"]) & {"match-sync", "match-everyone"}, set())
        self.assertIn(achievements.load("paulo")["earned"]["match-1"]["song"]["uri"],
                      {"spotify:track:x", "spotify:track:y"})
        self.assertEqual(achievements.room_pass(plays, False, now=at(hour=20)), {"paulo": [], "ana": [], "bia": []})

    def test_three_people_on_one_song(self):
        self.join("paulo", "ana", "bia")
        plays = {who: [play(uri="z", when=at(hour=hour))] for who, hour in (("paulo", 9), ("ana", 12), ("bia", 14))}
        new = achievements.room_pass(plays, False, now=at(hour=20))
        self.assertTrue(all("trio" in new[who] for who in plays))
        self.assertEqual(achievements.load("bia")["earned"]["trio"]["song"]["uri"], "spotify:track:z")

    def test_picking_up_artists_after_someone(self):
        self.join("paulo", "ana")
        paulo = [play(uri=f"p{n}", artists=(f"Novo {n}",), when=at(day=1) + n) for n in range(5)]
        ana = [play(uri=f"a{n}", artists=(f"Novo {n}",), when=at(day=10) + n) for n in range(5)]
        achievements.process("paulo", paulo, Context(), False)
        achievements.process("ana", ana, Context(), False)
        new = achievements.room_pass({"paulo": paulo, "ana": ana}, False, now=at(day=10, hour=20))
        self.assertIn("trendsetter", new["paulo"])
        self.assertIn("follower", new["ana"])
        self.assertIsNone(achievements.load("paulo")["earned"]["trendsetter"]["song"])


def month_of_plays(prefix, count, hour=12, release="2020-01-01", artists=25):
    return [play(uri=f"{prefix}{n}", artists=(f"{prefix}-artist-{n % artists}",), release=release,
                 when=at(day=1 + n % 28, hour=hour, minute=n % 60)) for n in range(count)]


class StandingsTest(unittest.TestCase):
    def test_fewer_than_fifty_plays_dont_compete_and_ties_share(self):
        result = monthly.standings("2026-10", {"paulo": month_of_plays("p", 60), "ana": month_of_plays("a", 40)}, {}, no_fans)
        self.assertEqual(result["marathoner"], {"users": ["paulo"], "value": 60})
        tie = monthly.standings("2026-10", {"paulo": month_of_plays("p", 60), "ana": month_of_plays("a", 60)}, {}, no_fans)
        self.assertEqual(tie["marathoner"], {"users": ["ana", "paulo"], "value": 60})
        self.assertNotIn("night-owl", tie)  # nobody played at night: nobody holds it

    def test_hours_decades_and_fans(self):
        plays = {"paulo": month_of_plays("p", 60, hour=2, release="1975"), "ana": month_of_plays("a", 60, hour=6)}
        fans = lambda name: 100 if name.startswith("p-") else 5000
        result = monthly.standings("2026-10", plays, {}, fans)
        self.assertEqual(result["night-owl"]["users"], ["paulo"])
        self.assertEqual(result["early-bird"]["users"], ["ana"])
        self.assertEqual(result["alternative"], {"users": ["paulo"], "value": 100})
        plays["ana"] += [play(uri="old", release="1965", when=at(day=2))]
        self.assertEqual(monthly.standings("2026-10", plays, {}, fans)["time-traveler"]["users"], ["ana"])

    def test_the_duo_and_first_heard_artists(self):
        shared = [play(uri=f"s{n}", when=at(day=5, hour=10) + n * 60) for n in range(5)]
        plays = {"paulo": month_of_plays("p", 55) + shared, "ana": month_of_plays("a", 55) + shared,
                 "bia": month_of_plays("b", 60)}
        firsts = {"paulo": {"x": at(day=2), "y": at(day=3)}, "ana": {"x": at(day=9), "y": at(day=12)}, "bia": {}}
        result = monthly.standings("2026-10", plays, firsts, no_fans)
        self.assertEqual(result["duo"], {"users": ["ana", "paulo"], "value": 5})
        self.assertEqual(result["explorer"], {"users": ["ana", "paulo"], "value": 2})  # two new artists each
        self.assertEqual(result["trendsetter"], {"users": ["paulo"], "value": 2})  # Ana picked up both after Paulo did


class CloseMonthTest(Room):
    def test_closes_last_month_once_from_the_first_month_on(self):
        self.join("paulo", "ana")
        plays = {"paulo": [play(uri=f"p{n}", when=at(day=1 + n % 28, hour=1)) for n in range(60)], "ana": []}
        self.assertIsNone(achievements.close_month(plays, no_fans, False, now=at(day=20)))  # September predates it
        self.assertEqual(achievements.close_month(plays, no_fans, False, now=at(month=11, day=1, hour=0, minute=5)),
                         "2026-10")
        room = json.loads((self.data / "achievements.json").read_text(encoding="utf-8"))
        self.assertEqual(room["months"]["2026-10"]["marathoner"], {"users": ["paulo"], "value": 60})
        self.assertIn("title-1", achievements.load("paulo")["earned"])
        self.assertIsNone(achievements.close_month(plays, no_fans, False, now=at(month=11, day=2)))  # only once

    def test_the_tab_shows_the_race_and_past_months(self):
        self.join("paulo", "ana")
        plays = [play(uri=f"p{n}", when=at(day=1 + n % 28, hour=1)) for n in range(60)]
        self.save_plays("paulo", plays)
        achievements.close_month({"paulo": plays, "ana": []}, no_fans, False, now=at(day=20))
        seen = achievements.view("ana", False, no_fans, now=at(day=20))
        race = {title["id"]: title for title in seen["race"]}
        self.assertEqual(race["marathoner"]["holders"], ["Paulo"])
        self.assertEqual(race["marathoner"]["value"], i18n.t("title.marathoner.value", count=60, value="60"))
        achievements.close_month({"paulo": plays, "ana": []}, no_fans, False, now=at(month=11, day=1))
        months = achievements.view("ana", False, no_fans, now=at(month=11, day=1))["months"]
        self.assertEqual([month["month"] for month in months], ["2026-10"])
```

- [ ] **Step 2: Run them to see them fail**

Run: `python -m unittest tests.test_achievements`
Expected: ERROR (`ImportError: cannot import name 'monthly'`).

- [ ] **Step 3: Create `spotify_assistant/monthly.py`**

```python
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
```

- [ ] **Step 4: Add `room_pass`, `close_month` and the race to `spotify_assistant/achievements.py`**

Add imports `from . import i18n, monthly` (extend the existing `from . import ...` line) and `from .medals import TITLES`
(extend the existing medals import). Add `SYNC_S = 5 * 60` and `MONTHS_SHOWN = 12` after the other constants. Add after
`rich_pass`:

```python
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
        firsts = {user_id: datas[user_id]["stats"]["artists"] for user_id in people}
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
```

In `view`, replace `"race": [],` and `"months": [],` with:

```python
        "race": _titles_view(monthly.standings(monthly.month_of(now), {user_id: social.plays(user_id) for user_id in datas},
                                               {user_id: data["stats"]["artists"] for user_id, data in datas.items()}, fans)),
        "months": _past_months(),
```

and add:

```python
def _past_months() -> list[dict]:
    try:
        months = _read_room()["months"]
    except Unreadable:
        return []
    closed = [(month, titles) for month, titles in sorted(months.items(), reverse=True) if titles]
    return [{"month": month, "titles": _titles_view(titles)} for month, titles in closed[:MONTHS_SHOWN]]
```

- [ ] **Step 5: Run the tests**

Run: `python -m unittest tests.test_achievements tests.test_medal_rules tests.test_medals`
Expected: OK.

- [ ] **Step 6: Commit**

```bash
git add spotify_assistant/monthly.py spotify_assistant/achievements.py tests/test_achievements.py
git commit -m "Achievements: matches between participants and the monthly titles"
```

---

### Task 7: The server: API, background loop, panel events, Friends

**Files:**
- Modify: `spotify_assistant/dashboard.py`
- Modify: `spotify_assistant/i18n.py` (server messages `ach.*`)
- Test: `tests/test_dashboard.py`

**Interfaces:**
- Consumes: everything `achievements.*` produces (Tasks 4–6).
- Produces: routes `GET /api/achievements`, `POST /api/achievements` (`{"on", "forget"}`),
  `POST /api/achievements/seen` (`{"ids"}`), `POST /api/achievements/highlights` (`{"ids"}`),
  `GET /api/achievements/summary`; `/api/overview` gains `"achievements": {"on", "new"} | None`; each friend in
  `/api/friends` gains `"medals": [{"id", "name"}]`; `App._achievements_loop()`.

- [ ] **Step 1: Write the failing tests**

In `tests/test_dashboard.py`, add `achievements` to the `from spotify_assistant import ...` line and add to `ServerTest`:

```python
    def test_achievements_need_friends_and_their_own_switch(self):
        get = lambda: json.loads(self.request("/api/achievements")[1])
        self.assertEqual(get(), {"sharing": False, "on": False})
        self.assertEqual(json.loads(self.request("/api/overview")[1])["achievements"], {"on": False, "new": 0})
        status, data = self.post("/api/achievements", {"on": True})
        self.assertEqual((status, data["error"]), (409, "As conquistas vêm do que você ouve: entre no Amigos primeiro."))
        self.post("/api/friends", {"share": True})
        status, data = self.post("/api/achievements", {"on": True})
        self.assertEqual((status, data["on"]), (200, True))
        self.assertEqual(data["message"], "Pronto! Suas medalhas aparecem aqui conforme você ouve.")
        self.post("/api/friends", {"share": False, "forget": True})  # leaving Friends erases them
        self.assertFalse((self.data / "users" / "paulo" / "achievements.json").exists())
        self.assertEqual(get(), {"sharing": False, "on": False})

    def test_the_owner_turning_friends_off_erases_achievements(self):
        self.post("/api/friends", {"share": True}, as_user="ana")
        self.post("/api/achievements", {"on": True}, as_user="ana")
        self.post("/api/friends/access", {"user": "ana", "allowed": False})
        self.assertFalse((self.data / "users" / "ana" / "achievements.json").exists())
        self.assertEqual(self.request("/api/achievements", as_user="ana")[0], 403)

    def test_discoveries_reviews_and_blocks_count_for_participants(self):
        with mock.patch.object(dashboard.App, "_run_hunt", staticmethod(lambda *args: None)):
            self.assertEqual(self.post("/api/hunts", {"kind": "roulette"})[0], 200)  # not taking part yet
            self.post("/api/friends", {"share": True})
            self.post("/api/achievements", {"on": True})
            self.post("/api/hunts", {"kind": "roulette", "rare": True})
        data = achievements.load("paulo")
        self.assertTrue({"roulette-1", "roulette-rare"} <= set(data["earned"]))
        self.assertEqual(data["stats"]["events"]["roulette"], 1)
        self.post("/api/reviews", {"album": "1weenld61qoidwYuZ1GESA", "rating": 5, "text": "Obra."})
        self.post("/api/blocked", {"artist": "Alguém"})
        self.assertTrue({"review-five", "block-1"} <= set(achievements.load("paulo")["earned"]))

    def test_highlights_and_seen_take_only_earned_medals(self):
        self.post("/api/friends", {"share": True})
        self.post("/api/achievements", {"on": True})
        achievements.note("paulo", "block")
        status, data = self.post("/api/achievements/highlights", {"ids": ["block-1", "rare-10"]})
        self.assertEqual((status, [medal["id"] for medal in data["me"]["highlights"]]), (200, ["block-1"]))
        self.assertEqual(self.post("/api/achievements/highlights", {"ids": [f"x{n}" for n in range(11)]})[0], 400)
        self.assertEqual(self.post("/api/achievements/highlights", {"ids": "block-1"})[0], 400)
        self.assertEqual(json.loads(self.request("/api/achievements/summary")[1]), {"on": True, "new": 1})
        self.assertEqual(self.post("/api/achievements/seen", {"ids": ["block-1"]})[0], 200)
        self.assertEqual(json.loads(self.request("/api/achievements/summary")[1]), {"on": True, "new": 0})
        self.assertEqual(self.post("/api/achievements/seen", {"ids": ["block-1"]}, as_user="ana")[0], 403)

    def test_friends_show_highlights_only_between_participants(self):
        for who in ("paulo", "ana"):
            self.post("/api/friends", {"share": True}, as_user=who)
        self.post("/api/achievements", {"on": True}, as_user="ana")
        achievements.note("ana", "block")
        achievements.set_highlights("ana", ["block-1"])
        card = lambda: json.loads(self.request("/api/friends")[1])["friends"][0]
        self.assertEqual(card()["medals"], [])  # Paulo doesn't take part
        self.post("/api/achievements", {"on": True})
        self.assertEqual([medal["id"] for medal in card()["medals"]], ["block-1"])

    def test_the_loop_turns_plays_into_medals(self):
        self.post("/api/friends", {"share": True})
        self.post("/api/achievements", {"on": True})
        plays = [{"uri": "spotify:track:1", "title": "Saudade", "artists": [{"id": "md", "name": "Miles Davis"}],
                  "image": None, "duration_ms": 562000, "at": 1_800_000_000.0,
                  "album": {"id": "al", "name": "Kind of Blue", "type": "album", "release": "1959-08-17", "tracks": 5},
                  "track_number": 1, "context": None}]
        (self.data / "users" / "paulo" / "plays.json").write_text(json.dumps(plays), encoding="utf-8")
        app = self.server.app
        app.deezer = mock.Mock(search_artist=mock.Mock(return_value={"nb_fan": 50}))
        app._achievements_loop()
        self.assertTrue({"first-play", "saudade", "fans-100"} <= set(achievements.load("paulo")["earned"]))
        self.assertTrue((self.data / "fans-cache.json").exists())
```

- [ ] **Step 2: Run them to see them fail**

Run: `python -m unittest tests.test_dashboard`
Expected: FAIL/ERROR on the new tests (`KeyError: 'achievements'`, 404 routes, `AttributeError: _achievements_loop`).

- [ ] **Step 3: Server messages in `spotify_assistant/i18n.py`**

`MESSAGES["pt"]`:

```python
        "ach.need_friends": "As conquistas vêm do que você ouve: entre no Amigos primeiro.",
        "ach.joined": "Pronto! Suas medalhas aparecem aqui conforme você ouve.",
        "ach.left": "Você saiu das conquistas. As medalhas ficam guardadas se quiser voltar.",
        "ach.forgot": "Você saiu e as suas conquistas foram apagadas.",
        "ach.off": "Isto é só para quem participa das conquistas.",
        "ach.highlights_saved": "Destaques salvos.",
        "ach.too_many_highlights": "Escolha no máximo {max} destaques.",
        "ach.bad_ids": "Não entendi quais medalhas.",
        "ach.unreadable": "Não consegui ler as suas conquistas agora. Tente mais tarde.",
```

`MESSAGES["en"]`:

```python
        "ach.need_friends": "Achievements come from what you play: join Friends first.",
        "ach.joined": "Done! Your medals show up here as you listen.",
        "ach.left": "You left achievements. Your medals are kept if you come back.",
        "ach.forgot": "You left and your achievements were erased.",
        "ach.off": "This is only for people taking part in achievements.",
        "ach.highlights_saved": "Highlights saved.",
        "ach.too_many_highlights": "Pick {max} highlights at most.",
        "ach.bad_ids": "I couldn't tell which medals.",
        "ach.unreadable": "I couldn't read your achievements right now. Try again later.",
```

- [ ] **Step 4: Wire `spotify_assistant/dashboard.py`**

1. Add `achievements` to the `from . import ...` line.
2. `App.__init__`, after `self.listener_counts = ...`:

```python
        self.artist_fans = achievements.ArtistFans()  # fans per artist, for the achievements (cached 30 days)
```

3. `overview`, add to the returned dict:

```python
            "achievements": (achievements.summary(user.id, self.listener_counts is not None)
                             if social.allowed(user.id) else None),
```

4. `start_hunt`, right after `hunt, task = self._hunt_task(...)`:

```python
        recipe = hunt.recipe or {}
        achievements.note(user.id, "hunt", lastfm=self.listener_counts is not None, kind=recipe.get("kind"),
                          rare=bool(recipe.get("rare")), text=bool(recipe.get("text")),
                          listeners=recipe.get("max_listeners"))
```

5. `create_playlist`, just before `return {"message": message, ...}`:

```python
        achievements.note(user.id, "playlist", uri=playlist["uri"])
        if every:
            achievements.note(user.id, "favorite")
```

6. `set_blocked`, inside `if body.get("blocked", True):` after `self._drop_artist_from_hunt(user, key)`:

```python
            achievements.note(user.id, "block")
```

7. `save_review`, after `reviews.save(...)`:

```python
        achievements.note(user.id, "review")
```

8. `set_friends_access`, after `social.set_allowed(target, allow)`:

```python
            if not allow:
                achievements.forget(target)  # out of Friends: their medals go with their history
```

9. `set_sharing`, after `social.set_share(user.id, share, forget=forget)`:

```python
        if not share:
            achievements.forget(user.id)  # leaving Friends erases the achievements built on it
```

10. `friends`, before the `for uid, items in everyone.items():` loop add
`medals_on = achievements.taking_part(user.id)` and `lastfm_on = self.listener_counts is not None`, and in the
friend dict add `"medals": achievements.highlights_of(uid, lastfm_on) if medals_on else [],`.

11. `collector`, just before `self._collector_wake.wait(social.COLLECT_EVERY_S)`:

```python
            self._achievements_loop()
```

12. New methods after `_collect`:

```python
    def _achievements_loop(self) -> None:
        """Medals for the people taking part, from the plays just collected (never asks Spotify)."""
        people = achievements.participants()
        if not people:
            return
        lastfm_on = self.listener_counts is not None
        plays = {uid: social.plays(uid) for uid in people}
        for uid in people:
            try:
                ctx = achievements.context(uid, self.listener_counts, self.artist_fans)
                achievements.process(uid, plays[uid], ctx, lastfm_on)
                achievements.enrich(plays[uid], achievements.load(uid)["rich_through"], self.listener_counts,
                                    self.artist_fans, self.deezer)
                achievements.rich_pass(uid, plays[uid], ctx, lastfm_on, self.listener_counts, self.artist_fans)
            except achievements.Unreadable as err:
                log.warning("Achievements left alone: %s", err)
            except Exception:
                log.exception("Achievements of %s failed", uid)
        try:
            achievements.room_pass(plays, lastfm_on)
            achievements.close_month(plays, self.artist_fans.cached, lastfm_on)
        except Exception:
            log.exception("Room achievements failed")
        if self.listener_counts:
            self.listener_counts.save()
        self.artist_fans.save()

    # Achievements: hidden medals and monthly titles, opt-in inside Friends

    def achievements_state(self, user: Profile) -> dict:
        if not social.allowed(user.id):
            raise UserError(t("friends.off"), 403)
        try:
            return achievements.view(user.id, self.listener_counts is not None, self.artist_fans.cached)
        except achievements.Unreadable as err:
            log.warning("Achievements: %s", err)
            raise UserError(t("ach.unreadable"), 500) from None

    def set_achievements(self, user: Profile, body: dict) -> dict:
        if not social.allowed(user.id):
            raise UserError(t("friends.off"), 403)
        on, forget = bool(body.get("on")), bool(body.get("forget"))
        if on and not social.sharing(user.id):
            raise UserError(t("ach.need_friends"), 409)
        if forget:
            achievements.forget(user.id)
        else:
            achievements.set_on(user.id, on)
        if on:
            self._collector_wake.set()  # the history already collected becomes medals right away
        message = t("ach.joined") if on else t("ach.forgot" if forget else "ach.left")
        return {**self.achievements_state(user), "message": message}

    @staticmethod
    def _medal_ids(body: dict) -> list[str]:
        ids = body.get("ids")
        if not isinstance(ids, list) or not all(isinstance(medal_id, str) for medal_id in ids):
            raise UserError(t("ach.bad_ids"))
        return ids

    def achievements_seen(self, user: Profile, body: dict) -> dict:
        if not achievements.taking_part(user.id):
            raise UserError(t("ach.off"), 403)
        achievements.mark_seen(user.id, self._medal_ids(body))
        return achievements.summary(user.id, self.listener_counts is not None)

    def achievements_highlights(self, user: Profile, body: dict) -> dict:
        if not achievements.taking_part(user.id):
            raise UserError(t("ach.off"), 403)
        ids = self._medal_ids(body)
        if len(ids) > achievements.MAX_HIGHLIGHTS:
            raise UserError(t("ach.too_many_highlights", max=achievements.MAX_HIGHLIGHTS))
        achievements.set_highlights(user.id, ids)
        return {**self.achievements_state(user), "message": t("ach.highlights_saved")}

    def achievements_summary(self, user: Profile) -> dict:
        return achievements.summary(user.id, self.listener_counts is not None)
```

13. Routes in `_route`, after the Friends routes:

```python
        if method == "GET" and path == "/api/achievements":
            return app.achievements_state(user)
        if method == "POST" and path == "/api/achievements":
            return app.set_achievements(user, body)
        if method == "GET" and path == "/api/achievements/summary":
            return app.achievements_summary(user)
        if method == "POST" and path == "/api/achievements/seen":
            return app.achievements_seen(user, body)
        if method == "POST" and path == "/api/achievements/highlights":
            return app.achievements_highlights(user, body)
```

- [ ] **Step 5: Run the tests**

Run: `python -m unittest discover -s tests`
Expected: OK (all tests, including `test_i18n`).

- [ ] **Step 6: Commit**

```bash
git add spotify_assistant/dashboard.py spotify_assistant/i18n.py tests/test_dashboard.py
git commit -m "Server: achievements API, background loop and panel events"
```

---

### Task 8: The panel: the Achievements tab

**Files:**
- Modify: `spotify_assistant/static/app.js`
- Modify: `spotify_assistant/static/i18n.js`
- Modify: `spotify_assistant/static/app.css`
- Create (scratchpad, not in the repo): `shots-achievements.mjs`
- Test: `tests/test_i18n.py` (existing parity and used-keys tests) and a headless-Chrome screen check

**Interfaces:**
- Consumes: the routes and payloads of Task 7.
- Produces: view `achievements` (`#achievements`, alias `#conquistas`), `MAX_HIGHLIGHTS = 10` in app.js.

- [ ] **Step 1: Browser texts in `static/i18n.js`**

Add to the `pt` object:

```json
    "view.achievements": "Conquistas",
    "ach.description": "Medalhas escondidas e títulos do mês entre quem participa. Ninguém sabe o que libera cada uma.",
    "ach.need_friends": "As conquistas vêm do que você ouve, lido pelo Amigos. Entre no Amigos primeiro.",
    "ach.go_friends": "Ir para o Amigos",
    "ach.invite": "Participe das conquistas: medalhas que aparecem conforme você ouve, e a disputa dos títulos do mês.",
    "ach.notice": "Quem participa vê as medalhas dos outros participantes e a música que liberou cada uma.",
    "ach.join": "Participar das conquistas",
    "ach.new_title": ["Você tem 1 conquista nova", "Você tem {count} conquistas novas"],
    "ach.reveal": "Toque para revelar",
    "ach.next": "Próxima",
    "ach.done": "Pronto",
    "ach.count": "{count} de {total} medalhas",
    "ach.no_highlights": "Nenhum destaque ainda.",
    "ach.pick_highlights": "Escolher destaques",
    "ach.highlights_hint": "Escolha até {max} medalhas para mostrar no seu perfil.",
    "ach.save_highlights": "Salvar destaques",
    "ach.cancel": "Cancelar",
    "ach.race": "Disputa do mês",
    "ach.race_empty": "Ninguém chegou a 50 músicas este mês ainda.",
    "ach.mine": "Suas medalhas",
    "ach.none_yet": "Nenhuma medalha ainda. Continue ouvindo.",
    "ach.room": "A sala",
    "ach.room_empty": "Ninguém mais participa ainda.",
    "ach.see_medals": "Ver medalhas",
    "ach.hide_medals": "Esconder medalhas",
    "ach.months": "Meses anteriores",
    "ach.only_you": "Só você tem",
    "ach.holders": ["{count} de {total} pessoas tem", "{count} de {total} pessoas têm"],
    "ach.earned_on": "Ganha em {date}",
    "ach.leave_text": "Você participa das conquistas.",
    "ach.leave": "Sair e guardar as medalhas",
    "ach.forget": "Sair e apagar",
    "ach.forget_confirm": "Clique de novo para apagar tudo",
    "ach.new_toast": "Você ganhou uma conquista nova! Veja em Conquistas.",
    "ach.new_badge": ["1 conquista nova", "{count} conquistas novas"],
    "ach.open_tab": "Abrir Conquistas",
```

and to the `en` object:

```json
    "view.achievements": "Achievements",
    "ach.description": "Hidden medals and monthly titles among those taking part. Nobody knows what unlocks each one.",
    "ach.need_friends": "Achievements come from what you play, read by Friends. Join Friends first.",
    "ach.go_friends": "Go to Friends",
    "ach.invite": "Take part in achievements: medals that turn up as you listen, and the race for the monthly titles.",
    "ach.notice": "Everyone taking part sees the other participants' medals and the song that unlocked each one.",
    "ach.join": "Take part in achievements",
    "ach.new_title": ["You have 1 new achievement", "You have {count} new achievements"],
    "ach.reveal": "Tap to reveal",
    "ach.next": "Next",
    "ach.done": "Done",
    "ach.count": "{count} of {total} medals",
    "ach.no_highlights": "No highlights yet.",
    "ach.pick_highlights": "Pick highlights",
    "ach.highlights_hint": "Pick up to {max} medals to show on your profile.",
    "ach.save_highlights": "Save highlights",
    "ach.cancel": "Cancel",
    "ach.race": "This month's race",
    "ach.race_empty": "Nobody has reached 50 songs this month yet.",
    "ach.mine": "Your medals",
    "ach.none_yet": "No medals yet. Keep listening.",
    "ach.room": "The room",
    "ach.room_empty": "Nobody else is taking part yet.",
    "ach.see_medals": "See medals",
    "ach.hide_medals": "Hide medals",
    "ach.months": "Past months",
    "ach.only_you": "Only you have it",
    "ach.holders": ["{count} of {total} people has it", "{count} of {total} people have it"],
    "ach.earned_on": "Earned on {date}",
    "ach.leave_text": "You're taking part in achievements.",
    "ach.leave": "Leave and keep my medals",
    "ach.forget": "Leave and erase",
    "ach.forget_confirm": "Click again to erase everything",
    "ach.new_toast": "You earned a new achievement! See it in Achievements.",
    "ach.new_badge": ["1 new achievement", "{count} new achievements"],
    "ach.open_tab": "Open Achievements",
```

- [ ] **Step 2: The tab in `static/app.js`**

1. `VIEWS`: add `achievements: "view.achievements",` after `friends`. `VIEW_ALIASES`: add `conquistas: "achievements",`.
   Add near the other constants: `const MAX_HIGHLIGHTS = 10;  // the server's achievements.MAX_HIGHLIGHTS`.
2. `go()`: replace `if (key === "friends" && state.overview && !state.overview.friends) key = "home";` with
   `if ((key === "friends" || key === "achievements") && state.overview && !state.overview.friends) key = "home";`.
3. `renderShelf()`: the `item` arrow function gains a `badge` field and a last child
   `badge > 0 && h("span", { class: "nav-badge", "aria-label": t("ach.new_badge", { count: badge }) }, String(badge))`;
   the views filter becomes `.filter(([key]) => (key !== "friends" && key !== "achievements") || state.overview.friends)`;
   the room items pass `badge: key === "achievements" ? state.overview.achievements?.new : 0`.
4. `openView()`: after `if (key === "reviews") loadReviews();` add `if (key === "achievements") loadAchievements();`.
5. `renderIntro()`: add `achievements: achievementsView,` to the map.
6. `loadOverview()`: replace its first line with

```js
  const before = state.overview?.achievements?.new ?? 0;
  state.overview = await api("/api/overview");
  const fresh = state.overview.achievements?.new || 0;
  if (fresh > before && state.view !== "achievements") toast(t("ach.new_toast"));
```

7. `init()`: after `setInterval(tick, 500);` add `setInterval(pollMedals, 120_000);`.
8. `friendsView()`: in `card`, after the name line add
   `friend.medals?.length > 0 && h("ul", { class: "highlight-row" }, friend.medals.map(highlightChip)),`;
   in the returned list (sharing branch), before `h("p", { class: "meta friends-me" }, ...)` add `achievementsSwitch(),`.
9. New section, after the Friends functions (`leaveFriends`):

```js
// ---------- Achievements: hidden medals and monthly titles among the people taking part (inside Friends)

async function loadAchievements() {
  try {
    state.achievements = await api("/api/achievements");
  } catch (error) {
    state.achievements = { error: error.message };
  }
  if (state.view === "achievements") renderIntro();
}

/** New medals show as a number on the tab; the server works them out every 15 minutes. */
async function pollMedals() {
  if (!state.overview?.friends || document.hidden) return;
  let summary;
  try {
    summary = await api("/api/achievements/summary");
  } catch {
    return;
  }
  const before = state.overview.achievements?.new || 0;
  state.overview.achievements = summary;
  if (summary.new > before && state.view !== "achievements") toast(t("ach.new_toast"));
  if (summary.new !== before) renderShelf();
}

function achievementsView() {
  const data = state.achievements;
  const head = viewHead("keep", t("view.achievements"), t("ach.description"));
  if (!data) return [head, h("p", { class: "meta" }, t("common.loading"))];
  if (data.error) return [head, h("p", { class: "meta is-warning" }, data.error)];
  if (!data.sharing) {
    return [head, h("section", { class: "friends-join" },
      h("p", null, t("ach.need_friends")),
      h("button", { class: "play-button", type: "button", onclick: () => go("friends") }, t("ach.go_friends")))];
  }
  if (!data.on) {
    return [head, h("section", { class: "friends-join" },
      h("p", null, t("ach.invite")),
      h("p", { class: "meta" }, t("ach.notice")),
      h("button", { class: "play-button", type: "button", onclick: joinAchievements }, t("ach.join")))];
  }
  return [
    head,
    revealSection(data),
    profileSection(data),
    raceSection(data.race, t("ach.race"), t("ach.race_empty")),
    h("section", { class: "home-section" },
      h("div", { class: "section-head" }, h("h2", { class: "section-title" }, t("ach.mine"))),
      data.me.medals.length ? h("ul", { class: "medal-grid" }, data.me.medals.map((medal) => medalCard(medal, data, true)))
        : h("p", { class: "meta" }, t("ach.none_yet"))),
    roomSection(data),
    data.months.length > 0 && h("section", { class: "home-section" },
      h("div", { class: "section-head" }, h("h2", { class: "section-title" }, t("ach.months"))),
      data.months.map((month) => raceSection(month.titles, monthLabel(month.month), "", true))),
    listenersHint(),
    h("p", { class: "meta friends-me" }, t("ach.leave_text"), " ",
      h("button", { class: "text-button", type: "button", onclick: () => leaveAchievements(false) }, t("ach.leave")), " ",
      h("button", { class: "text-button", type: "button", onclick: () => leaveAchievements(true) },
        t(state.confirmForgetMedals ? "ach.forget_confirm" : "ach.forget"))),
  ];
}

/** Inside Friends: the switch, or a way to the tab. */
function achievementsSwitch() {
  const on = state.overview?.achievements?.on;
  return h("section", { class: "home-section" },
    h("div", { class: "section-head" }, h("h2", { class: "section-title" }, t("view.achievements"))),
    on ? h("p", { class: "meta" }, t("ach.leave_text"), " ",
      h("button", { class: "text-button", type: "button", onclick: () => go("achievements") }, t("ach.open_tab")))
      : [h("p", { class: "meta" }, t("ach.invite"), " ", t("ach.notice")),
        h("button", { class: "play-button", type: "button", onclick: joinAchievements }, t("ach.join"))]);
}

async function joinAchievements() {
  try {
    state.achievements = await api("/api/achievements", { on: true });
    toast(state.achievements.message);
  } catch (error) {
    toast(error.message, true);
    return;
  }
  await loadOverview();
  if (state.view === "friends") renderIntro();
  else go("achievements");
}

/** Leaving keeps the medals for a return; erasing takes two clicks. */
async function leaveAchievements(forget) {
  if (forget && !state.confirmForgetMedals) {
    state.confirmForgetMedals = true;
    renderIntro();
    return;
  }
  state.confirmForgetMedals = false;
  try {
    state.achievements = await api("/api/achievements", { on: false, forget });
    toast(state.achievements.message);
  } catch (error) {
    toast(error.message, true);
  }
  renderIntro();
  loadOverview();
}

/** A badge whose shape and colors come from the medal's id: nothing in it hints at the rule. */
function medalEmblem(medal) {
  let hash = 0;
  for (const char of medal.id) hash = (hash * 31 + char.charCodeAt(0)) >>> 0;
  const shapes = ["is-round", "is-hex", "is-shield", "is-star"];
  return h("span", { class: `medal-emblem ${shapes[hash % shapes.length]}`, style: `--hue: ${hash % 360}`, "aria-hidden": "true" },
    medal.name.slice(0, 1));
}

function songLine(song) {
  return h("span", { class: "medal-song" },
    song.image ? h("img", { class: "track-art", src: song.image, alt: "", loading: "lazy" }) : h("span", { class: "track-art" }),
    h("span", { class: "track-text" },
      h("span", { class: "track-title" }, song.title),
      h("span", { class: "track-sub" }, song.artist)));
}

function medalCard(medal, data, own) {
  const rarity = own && medal.holders === 1 ? t("ach.only_you")
    : t("ach.holders", { count: medal.holders, total: data.participants });
  return h("li", { class: "medal-card" },
    medalEmblem(medal),
    h("div", { class: "medal-text" },
      h("p", { class: "medal-name" }, medal.name),
      own && medal.how && h("p", { class: "meta" }, medal.how),
      h("p", { class: "meta" }, t("ach.earned_on", { date: new Date(medal.at * 1000).toLocaleDateString(LOCALE) }), " · ", rarity),
      medal.lastfm && h("p", { class: "meta" }, lastfmLine(medal.lastfm)),
      medal.song && h("button", {
        class: "medal-song-button",
        type: "button",
        title: t("action.play_title", { title: medal.song.title }),
        onclick: () => command({ action: "play", uris: [medal.song.uri] }),
      }, songLine(medal.song))));
}

/** New medals one at a time: the card turns over to show what was earned (and how). */
function revealSection(data) {
  const fresh = data.new.map((id) => data.me.medals.find((medal) => medal.id === id)).filter(Boolean);
  if (!fresh.length) return null;
  const index = Math.min(state.reveal || 0, fresh.length - 1);
  const medal = fresh[index];
  const open = state.revealOpen === medal.id;
  const last = index === fresh.length - 1;
  return h("section", { class: "home-section reveal" },
    h("div", { class: "section-head" }, h("h2", { class: "section-title" }, t("ach.new_title", { count: fresh.length }))),
    h("button", {
      class: `reveal-card${open ? " is-open" : ""}`,
      type: "button",
      "aria-label": open ? medal.name : t("ach.reveal"),
      onclick: () => { state.revealOpen = medal.id; renderIntro(); },
    },
      h("span", { class: "reveal-face reveal-back", "aria-hidden": "true" }, "?"),
      h("span", { class: "reveal-face reveal-front", "aria-hidden": open ? null : "true" },
        medalEmblem(medal),
        h("strong", { class: "medal-name" }, medal.name),
        h("span", { class: "meta" }, medal.how),
        medal.song && songLine(medal.song))),
    !open && h("p", { class: "meta" }, t("ach.reveal")),
    open && h("button", { class: "play-button", type: "button", onclick: () => nextReveal(fresh, last) },
      t(last ? "ach.done" : "ach.next")));
}

async function nextReveal(fresh, last) {
  if (!last) {
    state.reveal = (state.reveal || 0) + 1;
    renderIntro();
    return;
  }
  try {
    state.overview.achievements = await api("/api/achievements/seen", { ids: fresh.map((medal) => medal.id) });
  } catch (error) {
    toast(error.message, true);
    return;
  }
  state.reveal = 0;
  state.revealOpen = null;
  renderShelf();
  await loadAchievements();
}

function highlightChip(medal) {
  return h("li", { class: "highlight-chip", title: medal.name }, medalEmblem(medal), h("span", null, medal.name));
}

function profileSection(data) {
  const me = data.me;
  const editing = Boolean(state.highlightDraft);
  return h("section", { class: "home-section profile-card" },
    h("div", { class: "section-head" },
      h("h2", { class: "section-title" }, me.name),
      h("p", { class: "meta" }, t("ach.count", { count: me.count, total: data.total }))),
    editing ? highlightPicker(me)
      : me.highlights.length ? h("ul", { class: "highlight-row" }, me.highlights.map(highlightChip))
        : h("p", { class: "meta" }, t("ach.no_highlights")),
    !editing && me.medals.length > 0 && h("button", {
      class: "text-button",
      type: "button",
      onclick: () => { state.highlightDraft = me.highlights.map((medal) => medal.id); renderIntro(); },
    }, t("ach.pick_highlights")));
}

function highlightPicker(me) {
  const toggle = (id, input) => {
    const draft = state.highlightDraft;
    if (!input.checked) {
      state.highlightDraft = draft.filter((other) => other !== id);
    } else if (draft.length >= MAX_HIGHLIGHTS) {
      input.checked = false;
      toast(t("ach.highlights_hint", { max: MAX_HIGHLIGHTS }));
    } else {
      draft.push(id);
    }
  };
  return h("div", { class: "highlight-picker" },
    h("p", { class: "meta" }, t("ach.highlights_hint", { max: MAX_HIGHLIGHTS })),
    h("ul", { class: "highlight-options" }, me.medals.map((medal) => h("li", null,
      h("label", { class: "highlight-option" },
        h("input", { type: "checkbox", checked: state.highlightDraft.includes(medal.id), onchange: (event) => toggle(medal.id, event.target) }),
        medalEmblem(medal),
        h("span", null, medal.name))))),
    h("div", { class: "actions" },
      h("button", { class: "play-button", type: "button", onclick: saveHighlights }, t("ach.save_highlights")),
      h("button", { class: "text-button", type: "button", onclick: () => { state.highlightDraft = null; renderIntro(); } },
        t("ach.cancel"))));
}

async function saveHighlights() {
  try {
    state.achievements = await api("/api/achievements/highlights", { ids: state.highlightDraft });
    toast(state.achievements.message);
  } catch (error) {
    toast(error.message, true);
    return;
  }
  state.highlightDraft = null;
  renderIntro();
}

function raceSection(titles, heading, empty, past = false) {
  return h("section", { class: past ? "race is-past" : "home-section race" },
    h("div", { class: "section-head" }, h(past ? "h3" : "h2", { class: "section-title" }, heading)),
    titles.length ? h("ul", { class: "race-list" }, titles.map((title) => h("li", { class: "race-item" },
      h("p", { class: "race-title" }, title.name),
      h("p", { class: "meta" }, listFormat.format(title.holders), " · ", title.value))))
      : h("p", { class: "meta" }, empty));
}

function monthLabel(month) {
  const [year, number] = month.split("-").map(Number);
  return new Date(year, number - 1, 1).toLocaleDateString(LOCALE, { month: "long", year: "numeric" });
}

function roomSection(data) {
  const card = (person) => {
    const open = state.openPerson === person.id;
    return h("li", { class: "friend-card" },
      h("p", { class: "friend-name" }, person.name),
      h("p", { class: "meta" }, t("ach.count", { count: person.count, total: data.total })),
      person.highlights.length > 0 && h("ul", { class: "highlight-row" }, person.highlights.map(highlightChip)),
      person.medals.length > 0 && h("button", {
        class: "text-button",
        type: "button",
        "aria-expanded": String(open),
        onclick: () => { state.openPerson = open ? null : person.id; renderIntro(); },
      }, t(open ? "ach.hide_medals" : "ach.see_medals")),
      open && h("ul", { class: "medal-grid is-compact" }, person.medals.map((medal) => medalCard(medal, data, false))));
  };
  return h("section", { class: "home-section" },
    h("div", { class: "section-head" }, h("h2", { class: "section-title" }, t("ach.room"))),
    data.people.length ? h("ul", { class: "friend-grid" }, data.people.map(card)) : h("p", { class: "meta" }, t("ach.room_empty")));
}
```

- [ ] **Step 3: Styles in `static/app.css`** (after the Friends rules)

```css
/* Achievements: medals, the reveal card, highlights and the month's race */
.medal-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: 14px; margin: 0; padding: 0; list-style: none; }
.medal-grid.is-compact { grid-template-columns: 1fr; margin-top: 12px; }
.medal-card { display: flex; gap: 14px; align-items: flex-start; padding: 16px 18px; border-radius: 8px; background: var(--velvet); }
.medal-text { min-width: 0; }
.medal-name { margin: 0; font-weight: 700; }
.medal-text .meta { margin: 2px 0 0; }
.medal-emblem { flex: none; display: grid; place-items: center; width: 52px; height: 52px; color: var(--ink); font-size: 20px; font-weight: 800;
  background: radial-gradient(circle at 35% 30%, hsl(var(--hue) 70% 80%), hsl(var(--hue) 55% 48%)); }
.medal-emblem.is-round { border-radius: 50%; }
.medal-emblem.is-hex { clip-path: polygon(25% 4%, 75% 4%, 100% 50%, 75% 96%, 25% 96%, 0 50%); }
.medal-emblem.is-shield { clip-path: polygon(50% 0, 100% 15%, 92% 70%, 50% 100%, 8% 70%, 0 15%); }
.medal-emblem.is-star { clip-path: polygon(50% 0, 62% 35%, 98% 35%, 69% 57%, 79% 91%, 50% 70%, 21% 91%, 31% 57%, 2% 35%, 38% 35%); font-size: 14px; }
.medal-song-button { display: block; margin-top: 8px; padding: 0; border: 0; background: none; color: inherit; text-align: left; cursor: pointer; }
.medal-song { display: flex; gap: 10px; align-items: center; min-width: 0; }
.medal-song .track-art { width: 36px; height: 36px; }
.reveal-card { position: relative; display: block; width: min(340px, 100%); min-height: 240px; margin: 0 0 14px; padding: 0; border: 0;
  border-radius: 12px; background: none; color: inherit; cursor: pointer; perspective: 900px; }
.reveal-face { position: absolute; inset: 0; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 10px;
  padding: 20px; border-radius: 12px; text-align: center; backface-visibility: hidden; transition: transform .6s ease; }
.reveal-back { background: linear-gradient(135deg, var(--velvet-raised), var(--line)); color: var(--mood); font-size: 64px; font-weight: 800; }
.reveal-front { background: var(--velvet); transform: rotateY(180deg); }
.reveal-card.is-open .reveal-back { transform: rotateY(180deg); }
.reveal-card.is-open .reveal-front { transform: rotateY(360deg); }
@media (prefers-reduced-motion: reduce) { .reveal-face { transition: none; } }
.highlight-row { display: flex; flex-wrap: wrap; gap: 8px; margin: 8px 0 0; padding: 0; list-style: none; }
.highlight-chip { display: flex; align-items: center; gap: 8px; padding: 4px 12px 4px 4px; border-radius: 999px; background: var(--velvet-raised); font-size: 14px; }
.highlight-chip .medal-emblem { width: 28px; height: 28px; font-size: 12px; }
.highlight-options { display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 8px; margin: 8px 0; padding: 0; list-style: none; }
.highlight-option { display: flex; align-items: center; gap: 10px; cursor: pointer; }
.highlight-option .medal-emblem { width: 32px; height: 32px; font-size: 13px; }
.race-list { display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 10px; margin: 0; padding: 0; list-style: none; }
.race-item { padding: 12px 16px; border-radius: 8px; background: var(--velvet); }
.race-title { margin: 0; font-weight: 700; }
.race.is-past { margin-top: 12px; }
.nav-badge { margin-left: 6px; padding: 0 6px; border-radius: 999px; background: var(--mood); color: var(--ink); font-size: 12px; font-weight: 700; }
```

- [ ] **Step 4: Run the tests**

Run: `python -m unittest discover -s tests`
Expected: OK (`test_i18n` checks the new keys exist in both languages and are used correctly).

- [ ] **Step 5: Screen check (headless Chrome, fake panel, mocked data)**

Start the fake panel: `python -I <scratchpad>/fake_panel.py C:\dev\spotfyprsonal <scratchpad>` (background), then write
`shots-achievements.mjs` in the scratchpad by copying `shots2.mjs` (same CDP helpers, port 9336, profile
`profile-cdp3`) and replacing everything between `await evaluate(\`localStorage.setItem(...)\`)` and the final
`console.log` with:

```js
const MEDALS = [
  { id: "m-a", name: "Primeira", how: "Fez algo pela primeira vez.", at: 1792000000, holders: 1,
    song: { uri: "spotify:track:a", title: "Pullopantti", artist: "Slim Mill", image: null }, lastfm: null },
  { id: "m-b", name: "Segunda medalha com nome longo", how: "Fez outra coisa bem descrita aqui.", at: 1791900000, holders: 2,
    song: null, lastfm: { listeners: 42, url: "https://www.last.fm/music/X/_/Y" } },
];
const MOCK = {
  sharing: true, on: true, total: 170, participants: 3, lastfm: true,
  me: { id: "paulo", name: "Paulo", count: 2, highlights: [MEDALS[0]], medals: MEDALS },
  new: ["m-a", "m-b"],
  people: [{ id: "ana", name: "Ana", count: 1, highlights: [MEDALS[1]], medals: [{ ...MEDALS[1], how: undefined }] }],
  race: [{ id: "marathoner", name: "Maratonista", holders: ["Paulo"], value: "312 músicas" },
         { id: "duo", name: "Dupla do mês", holders: ["Paulo", "Ana"], value: "12 coincidências" }],
  months: [{ month: "2026-09", titles: [{ id: "explorer", name: "Explorador", holders: ["Ana"], value: "40 artistas novos" }] }],
};
const mock = `(() => { state.overview.friends = true; state.overview.achievements = { on: true, new: 2 };
  state.achievements = ${JSON.stringify(MOCK)}; state.view = "achievements"; renderShelf(); renderIntro(); })()`;
for (const [name, size] of [["phone", phone], ["desktop", { width: 1366, height: 900 }]]) {
  await open("?a#home", size);
  await evaluate(mock);
  await sleep(500);
  await shot(`${name}-reveal`);
  await evaluate(`document.querySelector(".reveal-card").click()`);
  await sleep(900);
  await shot(`${name}-revealed`);
  report[name] = await evaluate(`({
    overflow: document.documentElement.scrollWidth > window.innerWidth,
    badge: document.querySelector(".nav-badge")?.textContent ?? null,
    howShownForOthers: [...document.querySelectorAll(".friend-card .medal-card")].some((card) => card.textContent.includes("Fez outra")),
  })`);
  await evaluate(`state.openPerson = "ana"; state.highlightDraft = ["m-a"]; renderIntro()`);
  await sleep(400);
  await shot(`${name}-profile`);
}
await evaluate(`state.achievements = { sharing: true, on: false }; renderIntro()`);
await sleep(300);
await shot("invite");
```

Run: `node <scratchpad>/shots-achievements.mjs <scratchpad> ach`
Expected: `overflow: false` at both sizes, `badge: "2"`, `howShownForOthers: false`, "Console clean". Look at every
screenshot (reveal card before and after turning, profile with the picker open, Ana's medals open, the invitation).
Stop the fake panel afterwards.

- [ ] **Step 6: Commit**

```bash
git add spotify_assistant/static/app.js spotify_assistant/static/i18n.js spotify_assistant/static/app.css
git commit -m "Panel: the Achievements tab (reveal, profile highlights, race, room)"
```

---

### Task 9: Docs and rollout

**Files:**
- Modify: `README.md`, `README.pt-BR.md`, `CLAUDE.md`

- [ ] **Step 1: README (en), a section after the Friends section**

```markdown
### Achievements

Inside Friends, each person can also take part in achievements: more than 100 hidden medals (plus one per game with a
memorable soundtrack) that turn up as you listen, and eight monthly titles the participants compete for. Nobody knows
what unlocks a medal until they earn it; only whoever earned it sees how. Participants see each other's medals and
the song behind each one. Everything is worked out in the background from what Friends already collects (no extra
Spotify requests); medals about rare songs need the Last.fm key.
```

README.pt-BR.md, the same section in Portuguese:

```markdown
### Conquistas

Dentro do Amigos, cada pessoa também pode participar das conquistas: mais de 100 medalhas escondidas (e uma para cada
jogo de trilha marcante) que aparecem conforme você ouve, e oito títulos do mês disputados entre os participantes.
Ninguém sabe o que libera uma medalha até ganhar; só quem ganhou vê como. Os participantes veem as medalhas uns dos
outros e a música que liberou cada uma. Tudo é calculado no fundo, a partir do que o Amigos já coleta (sem pedidos a
mais ao Spotify); as medalhas de músicas raras precisam da chave do Last.fm.
```

- [ ] **Step 2: CLAUDE.md**

In "Map", after the `social.py` entry:

```markdown
- `achievements.py` / `medal_rules.py` / `monthly.py`: Achievements (opt-in inside Friends): each person's medals in
  `data/users/<id>/achievements.json`, the closed months in `data/achievements.json`, worked out by the collector loop
  (plays, Last.fm listeners, artist fans in `data/fans-cache.json`, matches). `medals.py` and `medal_names.py` are the
  catalog: spoilers the owner chose not to read; don't name medals to the owner, in commits or in docs.
```

In "Rules", after the Friends privacy rule (the `social.py` bullet) add:

```markdown
- Achievements: participants see each other's medals and the song behind each one; nothing for non-participants; a
  medal nobody has earned never reaches the browser, and only whoever earned a medal sees how.
```

- [ ] **Step 3: Run the tests and commit**

Run: `python -m unittest discover -s tests`
Expected: OK.

```bash
git add README.md README.pt-BR.md CLAUDE.md
git commit -m "Docs: achievements"
```

- [ ] **Step 4: Rollout (after the final review and merge; owner approval for push and deploy)**

1. Push `main`, then on the server: `bash ~/sala-de-escuta/scripts/install-linux.sh`.
2. The owner turns achievements on in Friends and opens the tab; the first loop (within 15 minutes, or right away
   because joining wakes the collector) turns the last 90 days into medals.
3. Check `data/assistant.log` on the server for "Achievements" warnings after the first loop. No loops of real
   discoveries.
