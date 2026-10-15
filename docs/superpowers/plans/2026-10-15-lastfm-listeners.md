# Last.fm Listeners Filter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A "Song listeners: at most" filter, counted on Last.fm, in every discovery that has the fans filter.

**Architecture:** A small Last.fm client with a 30-day disk cache (`lastfm.py`) feeds a `ListenerCap` that each
discovery in `discovery.py` consults before searching a track on Spotify. The dashboard builds the client only when
`LASTFM_API_KEY` is set, validates `max_listeners`, keeps it in favorites' recipes and turns Last.fm failures into
messages. The panel shows the filter only when the room has a key and credits Last.fm with links.

**Tech Stack:** Python 3.12 standard library (`urllib`, `json`, `threading`), vanilla JS in `static/app.js`,
`unittest` with fakes.

**Spec:** `docs/superpowers/specs/2026-10-15-lastfm-listeners-design.md`

## Global Constraints

- Python 3.12 standard library only; no new packages.
- Every text a person sees goes through `t()`, in both languages: `spotify_assistant/i18n.py` and
  `spotify_assistant/static/i18n.js` (keep the latter valid JSON after `const STRINGS = `).
- Never mention Deezer in the UI. Last.fm is credited wherever its numbers show, as text with a link; no Last.fm logo.
- Tests use fakes only: nothing calls Last.fm or Spotify for real. Never run real discoveries in loops.
- Code, comments, docs and commit messages in English; match the surrounding comment density and naming.
- Windows shell: bash heredocs with Python triple-quoted strings break. Use the Edit tool, or write patch scripts to the
  scratchpad and run them with `python -I`.
- Run tests with `python -m unittest discover -s tests` from the repo root.
- Commits end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Before each commit, check the staged diff
  for the Spotify Client ID, tokens, the Tailscale address, the owner's Spotify id and any Last.fm key. Never commit
  `.env`, `data/` or `playlists.json`.
- Spec deviation (deliberate): instead of a module-level `discovery.listener_counts`, the dashboard owns one
  `lastfm.ListenerCounts` and hands its `get` to each `ListenerCap`. Same behavior, easier to fake in tests.

## Review Focus

1. Titles and artists in non-Latin scripts (Hangul, kana, Cyrillic) must get distinct cache keys:
   `curation.normalize` drops them to empty strings, so two K-pop songs would share one cached count. Pinned by
   `test_non_latin_titles_get_their_own_entries` (Task 1).
2. Last.fm answering 200 with an unexpected body (HTML, a list, no `track`) must read as "down", never crash a
   discovery. Pinned by `test_unexpected_answers_are_down` (Task 1).
3. A corrupted `data/lastfm-cache.json` must start empty instead of breaking every discovery. Pinned by
   `test_unreadable_file_starts_empty` (Task 1).
4. A cap saved in the browser while the room has no key (or after the key is removed) must not be sent, or every
   discovery would fail with 400. Pinned by the `sizeBody()` code and the screen check in Task 4.
5. Odd caps: `"0"` is valid (only tracks with no record pass); `"-1"`, `"muitos"` are refused with
   `err.listeners_invalid`. Pinned by `test_listener_cap_is_validated` (Task 3).

---

### Task 1: Last.fm client and cache

**Files:**
- Create: `spotify_assistant/lastfm.py`
- Modify: `spotify_assistant/config.py` (constants block, after `MUSICBRAINZ_CACHE_FILE`)
- Modify: `CLAUDE.md` (Map section)
- Test: `tests/test_lastfm.py` (new)

**Interfaces:**
- Consumes: `curation.normalize`, `curation.base_title`, `config.LASTFM_CACHE_FILE`.
- Produces:
  - `lastfm.Listeners(count: int | None, url: str | None)` (frozen dataclass; `count is None` means no record).
  - `lastfm.LastFmError(kind: str)` with `.kind in {"key", "limit", "down"}`.
  - `lastfm.LastFm(key: str, opener=urllib.request.urlopen, clock=time.monotonic, sleep=time.sleep)` with
    `.track(artist: str, title: str) -> Listeners`.
  - `lastfm.ListenerCounts(client: LastFm, path: Path | None = None, now=time.time)` with
    `.get(artist: str, title: str) -> Listeners` and `.save() -> None`.
  - `lastfm.cache_key(artist: str, title: str) -> str`.
  - Constants `MIN_INTERVAL_S = 0.25`, `LIMIT_PAUSE_S = 600`, `FRESH_S = 30 * 86400`, `MAX_ENTRIES = 100_000`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_lastfm.py`:

```python
import io
import json
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

from spotify_assistant import lastfm


class LastFmServer:
    """A fake urlopen that answers like Last.fm: errors come as JSON with a 4xx/5xx status."""

    def __init__(self, *answers):
        self.answers = list(answers)  # (payload, status); the last one keeps repeating
        self.urls = []

    def __call__(self, request, timeout):
        self.urls.append(request.full_url)
        payload, status = self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]
        body = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        if status >= 400:
            raise urllib.error.HTTPError(request.full_url, status, "error", {}, io.BytesIO(body))
        return io.BytesIO(body)


class Clock:
    def __init__(self):
        self.now = 1000.0
        self.slept = []

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.slept.append(round(seconds, 3))
        self.now += seconds


def client(server, clock=None):
    clock = clock or Clock()
    return lastfm.LastFm("chave", opener=server, clock=clock, sleep=clock.sleep)


PAGE = "https://www.last.fm/music/Miles+Davis/_/So+What"
TRACK = {"track": {"name": "So What", "url": PAGE, "listeners": "1234"}}


class ClientTest(unittest.TestCase):
    def test_reads_listeners_and_page(self):
        server = LastFmServer((TRACK, 200))
        found = client(server).track("Miles Davis", "So What - Remastered 2005 (Live)")
        self.assertEqual(found, lastfm.Listeners(1234, PAGE))
        self.assertIn("track=So+What&", server.urls[0])  # the title goes without its version
        self.assertIn("autocorrect=1", server.urls[0])

    def test_unknown_track_has_no_record(self):
        for status in (200, 400):
            found = client(LastFmServer(({"error": 6, "message": "Track not found"}, status))).track("X", "Y")
            self.assertEqual(found, lastfm.Listeners(None, None))

    def test_missing_count_reads_as_zero(self):
        self.assertEqual(client(LastFmServer(({"track": {"url": "u"}}, 200))).track("X", "Y"), lastfm.Listeners(0, "u"))

    def test_errors_say_what_went_wrong(self):
        cases = [({"error": 10}, 403, "key"), ({"error": 26}, 403, "key"), ({"error": 11}, 503, "down"),
                 ({"error": 8}, 500, "down"), (b"<html>Bad gateway</html>", 502, "down")]
        for payload, status, kind in cases:
            with self.subTest(payload=payload), self.assertRaises(lastfm.LastFmError) as caught:
                client(LastFmServer((payload, status))).track("X", "Y")
            self.assertEqual(caught.exception.kind, kind)

    def test_unexpected_answers_are_down(self):
        for payload in (b"<html>maintenance</html>", [1, 2], {"something": "else"}):
            with self.subTest(payload=payload), self.assertRaises(lastfm.LastFmError) as caught:
                client(LastFmServer((payload, 200))).track("X", "Y")
            self.assertEqual(caught.exception.kind, "down")

    def test_network_failure_is_down(self):
        def offline(request, timeout):
            raise urllib.error.URLError("no route")

        with self.assertRaises(lastfm.LastFmError) as caught:
            client(offline).track("X", "Y")
        self.assertEqual(caught.exception.kind, "down")

    def test_rate_limit_pauses_ten_minutes_without_asking(self):
        clock = Clock()
        server = LastFmServer(({"error": 29, "message": "Rate limit exceeded"}, 429), (TRACK, 200))
        api = client(server, clock)
        for _ in range(2):
            with self.assertRaises(lastfm.LastFmError) as caught:
                api.track("X", "Y")
            self.assertEqual(caught.exception.kind, "limit")
        self.assertEqual(len(server.urls), 1)  # the second call never went out
        clock.now += lastfm.LIMIT_PAUSE_S
        self.assertEqual(api.track("X", "Y").count, 1234)

    def test_requests_are_at_least_a_quarter_second_apart(self):
        clock = Clock()
        api = client(LastFmServer((TRACK, 200)), clock)
        for _ in range(3):
            api.track("X", "Y")
        self.assertEqual(clock.slept, [0.25, 0.25])


class CacheTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.file = Path(tmp.name) / "lastfm-cache.json"
        self.now = [1_000_000.0]
        self.server = LastFmServer((TRACK, 200))

    def counts(self):
        return lastfm.ListenerCounts(client(self.server), path=self.file, now=lambda: self.now[0])

    def test_asks_once_per_track_for_thirty_days(self):
        counts = self.counts()
        counts.get("Miles Davis", "So What")
        counts.get("MILES DAVIS", "So What (Live)")  # the same track: case and version don't count
        self.assertEqual(len(self.server.urls), 1)
        self.now[0] += lastfm.FRESH_S
        counts.get("Miles Davis", "So What")
        self.assertEqual(len(self.server.urls), 2)

    def test_no_record_is_remembered_across_restarts(self):
        self.server = LastFmServer(({"error": 6}, 200))
        counts = self.counts()
        self.assertEqual(counts.get("X", "Y"), lastfm.Listeners(None, None))
        counts.save()
        self.assertEqual(self.counts().get("X", "Y"), lastfm.Listeners(None, None))
        self.assertEqual(len(self.server.urls), 1)

    def test_errors_are_not_cached(self):
        self.server = LastFmServer(({"error": 11}, 503), (TRACK, 200))
        counts = self.counts()
        with self.assertRaises(lastfm.LastFmError):
            counts.get("X", "Y")
        self.assertEqual(counts.get("X", "Y").count, 1234)

    def test_non_latin_titles_get_their_own_entries(self):
        self.assertNotEqual(lastfm.cache_key("아이유", "좋은 날"), lastfm.cache_key("아이유", "밤편지"))
        self.assertEqual(lastfm.cache_key("아이유", "좋은 날 (Live)"), lastfm.cache_key("아이유", "좋은 날"))

    def test_oldest_entries_go_past_the_limit(self):
        with mock.patch.object(lastfm, "MAX_ENTRIES", 10):
            counts = self.counts()
            for number in range(11):
                self.now[0] += 1
                counts.get("Artista", f"Faixa {number}")
            counts.save()
        kept = json.loads(self.file.read_text(encoding="utf-8"))
        self.assertEqual(len(kept), 9)  # trimmed to 90% of the limit, so it doesn't trim on every lookup
        self.assertNotIn(lastfm.cache_key("Artista", "Faixa 0"), kept)
        self.assertIn(lastfm.cache_key("Artista", "Faixa 10"), kept)

    def test_unreadable_file_starts_empty(self):
        self.file.write_text("{oops", encoding="utf-8")
        self.assertEqual(self.counts().get("Miles Davis", "So What").count, 1234)

    def test_save_only_writes_when_something_changed(self):
        self.counts().save()
        self.assertFalse(self.file.exists())


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m unittest tests.test_lastfm`
Expected: ERROR, `ImportError: cannot import name 'lastfm' from 'spotify_assistant'`.

- [ ] **Step 3: Add the cache path to config**

In `spotify_assistant/config.py`, after the line `MUSICBRAINZ_CACHE_FILE = DATA_DIR / "musicbrainz-cache.json"`, add:

```python
LASTFM_CACHE_FILE = DATA_DIR / "lastfm-cache.json"
```

- [ ] **Step 4: Write the client and cache**

Create `spotify_assistant/lastfm.py`:

```python
"""Last.fm: how many people listened to a track (optional; needs LASTFM_API_KEY in .env).

Used by the discoveries' listener filter. Each track is asked once every 30 days and remembered in
data/lastfm-cache.json. Last.fm's terms ask for credit wherever its numbers show, with a link to the track.
"""
from __future__ import annotations

import json
import threading
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from . import config, curation

API_URL = "https://ws.audioscrobbler.com/2.0/"
USER_AGENT = "SalaDeEscuta/1.0 (+https://github.com/NejDev/sala-de-escuta)"
MIN_INTERVAL_S = 0.25  # at most 4 requests per second for the whole panel (Last.fm no longer publishes a number)
TIMEOUT_S = 10
LIMIT_PAUSE_S = 10 * 60  # after Last.fm says "rate limit exceeded"
FRESH_S = 30 * 86400  # listener counts grow: ask again after a month
MAX_ENTRIES = 100_000  # about 15 MB; Last.fm's terms cap stored data at 100 MB
NOT_FOUND = 6
KEY_ERRORS = {10, 26}  # invalid or suspended key
RATE_LIMITED = 29


@dataclass(frozen=True)
class Listeners:
    count: int | None  # None: Last.fm has no record of the track
    url: str | None  # the track's page on Last.fm


class LastFmError(RuntimeError):
    def __init__(self, kind: str) -> None:
        super().__init__(kind)
        self.kind = kind  # "key" (not accepted), "limit" (paused for a while) or "down"


class LastFm:
    def __init__(
        self, key: str, opener: Callable = urllib.request.urlopen,
        clock: Callable[[], float] = time.monotonic, sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.key = key
        self._opener = opener
        self._clock = clock
        self._sleep = sleep
        self._lock = threading.Lock()
        self._last: float | None = None
        self._paused_until = 0.0

    def _wait_turn(self) -> None:
        """One request at a time, MIN_INTERVAL_S apart; none at all while Last.fm asked for a pause."""
        with self._lock:
            now = self._clock()
            if now < self._paused_until:
                raise LastFmError("limit")
            if self._last is not None and now < self._last + MIN_INTERVAL_S:
                self._sleep(self._last + MIN_INTERVAL_S - now)
                now = self._last + MIN_INTERVAL_S
            self._last = now

    def track(self, artist: str, title: str) -> Listeners:
        """Listeners of a track; the title goes without its version ("So What - Remastered" -> "So What")."""
        self._wait_turn()
        query = urllib.parse.urlencode({
            "method": "track.getInfo", "artist": artist, "track": curation.base_title(title),
            "autocorrect": 1, "format": "json", "api_key": self.key,
        })
        request = urllib.request.Request(f"{API_URL}?{query}", headers={"User-Agent": USER_AGENT})
        try:
            with self._opener(request, timeout=TIMEOUT_S) as response:
                data = json.loads(response.read())
        except urllib.error.HTTPError as err:  # Last.fm sends its errors as JSON with a 4xx status
            data = _error_body(err)
        except (urllib.error.URLError, TimeoutError, ValueError) as err:
            raise LastFmError("down") from err
        if not isinstance(data, dict):
            raise LastFmError("down")
        code = data.get("error")
        if code == NOT_FOUND:
            return Listeners(None, None)
        if code in KEY_ERRORS:
            raise LastFmError("key")
        if code == RATE_LIMITED:
            with self._lock:
                self._paused_until = self._clock() + LIMIT_PAUSE_S
            raise LastFmError("limit")
        if code or not isinstance(data.get("track"), dict):
            raise LastFmError("down")
        track = data["track"]
        try:
            count = int(track.get("listeners") or 0)
        except (TypeError, ValueError):
            count = 0
        return Listeners(count, track.get("url"))


def _error_body(err: urllib.error.HTTPError) -> dict:
    try:
        data = json.loads(err.read())
    except ValueError:
        raise LastFmError("down") from err
    if not isinstance(data, dict) or "error" not in data:
        raise LastFmError("down") from err
    return data


def _fold(text: str) -> str:
    """Case and spacing don't count; unlike curation.normalize, Hangul, kana and Cyrillic survive."""
    return " ".join(unicodedata.normalize("NFKC", text).casefold().split())


def cache_key(artist: str, title: str) -> str:
    return f"{_fold(artist)}|{_fold(curation.base_title(title))}"


class ListenerCounts:
    """Cached lookups in front of the client: each track is asked once every 30 days."""

    def __init__(self, client: LastFm, path: Path | None = None, now: Callable[[], float] = time.time) -> None:
        self.client = client
        self._path = path
        self._now = now
        self._lock = threading.Lock()
        self._data: dict[str, dict] | None = None
        self._dirty = False

    def _file(self) -> Path:
        return self._path or config.LASTFM_CACHE_FILE

    def _entries(self) -> dict[str, dict]:
        """Called with the lock held."""
        if self._data is None:
            try:
                data = json.loads(self._file().read_text(encoding="utf-8"))
            except (FileNotFoundError, ValueError):
                data = {}
            self._data = data if isinstance(data, dict) else {}
        return self._data

    def get(self, artist: str, title: str) -> Listeners:
        key = cache_key(artist, title)
        with self._lock:
            entry = self._entries().get(key)
        if entry and self._now() - entry["at"] < FRESH_S:
            return Listeners(entry["n"], entry["url"])
        found = self.client.track(artist, title)  # errors propagate and nothing is cached
        with self._lock:
            entries = self._entries()
            entries[key] = {"n": found.count, "url": found.url, "at": self._now()}
            if len(entries) > MAX_ENTRIES:  # keep the newest 90%, so trimming doesn't happen on every lookup
                newest = sorted(entries, key=lambda name: entries[name]["at"], reverse=True)[: int(MAX_ENTRIES * 0.9)]
                self._data = {name: entries[name] for name in newest}
            self._dirty = True
        return found

    def save(self) -> None:
        with self._lock:
            if not self._dirty or self._data is None:
                return
            path = self._file()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(self._data, ensure_ascii=False), encoding="utf-8")
            self._dirty = False
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python -m unittest tests.test_lastfm`
Expected: PASS (17 tests).

- [ ] **Step 6: Add the module to CLAUDE.md's map**

In `CLAUDE.md`, after the line starting with ``- `api.py`:``, add:

```markdown
- `lastfm.py`: Last.fm client and its 30-day cache (`data/lastfm-cache.json`): song listeners for the discoveries'
  filter. Optional: only with `LASTFM_API_KEY` in `.env`.
```

- [ ] **Step 7: Run the whole suite**

Run: `python -m unittest discover -s tests`
Expected: all tests pass.

- [ ] **Step 8: Commit**

```bash
git add spotify_assistant/lastfm.py spotify_assistant/config.py tests/test_lastfm.py CLAUDE.md
git commit -m "Last.fm client with a 30-day cache of song listeners"
```

---

### Task 2: The listener cap in every discovery

**Files:**
- Modify: `spotify_assistant/discovery.py` (constants, `Find`, `find_from`, `within_size` neighbors, `sense`,
  `_add_find`, `obscure_album_pick`, `world_genre_pick`, `roulette`, `news`, `artist_picks`, `rabbit_hole`)
- Test: `tests/test_discovery.py`

**Interfaces:**
- Consumes: `lastfm.Listeners`, `lastfm.LastFmError` (Task 1).
- Produces:
  - `discovery.ListenerCap(max: int | None = None, lookup: Callable[[str, str], Listeners] | None = None)` with
    `.active -> bool` and `.check(artist: str, title: str) -> tuple[bool, dict | None]` (fits, `{"listeners": int | None, "url": str | None}`
    or `None` when there's no cap). `discovery.NO_CAP = ListenerCap()`.
  - `Find.lastfm: dict | None = None`; `find_from(..., lastfm: dict | None = None)`.
  - `discovery.within_listeners(tracks: list[dict], listeners: ListenerCap, want: int, hunt: Hunt | None = None) -> list[dict]`
    (each kept track is a copy with a `"lastfm"` key).
  - `discovery.LISTENER_SCAN_MAX = 240`.
  - New keyword `listeners: ListenerCap = NO_CAP` on `sense`, `roulette`, `world_genre_pick`, `obscure_album_pick`,
    `news`, `rabbit_hole`, `artist_picks`.
  - New server messages `sense.checking_listeners` and `sense.no_listeners` (added here, both languages).

- [ ] **Step 1: Write the failing tests**

In `tests/test_discovery.py`, add to the imports:

```python
from spotify_assistant import config, discovery, i18n, lastfm
```

(replacing the existing `from spotify_assistant import config, discovery, i18n`), and append these classes at the end
of the file, before `if __name__ == "__main__":` if present (otherwise at the very end):

```python
class FakeLastFm:
    """Listeners by title; titles it doesn't know have no record. Remembers who was asked about."""

    def __init__(self, listeners=None, error=None):
        self.listeners = listeners or {}
        self.error = error
        self.asked = []

    def __call__(self, artist, title):
        self.asked.append((artist, title))
        if self.error:
            raise lastfm.LastFmError(self.error)
        if title not in self.listeners:
            return lastfm.Listeners(None, None)
        return lastfm.Listeners(self.listeners[title], f"https://www.last.fm/_/{title}")


class HipsterSpotify(FakeSpotify):
    """One barely-played album with a well-known track and a hidden one."""

    def search(self, query, kind, offset=0):
        if query.startswith("tag:hipster"):
            return [{"id": "al", "name": "Disco", "album_type": "album", "artists": [{"name": "Banda"}], "images": []}]
        return super().search(query, kind, offset)

    def album_tracks(self, album_id):
        return [{"uri": "spotify:track:h1", "name": "Famosa", "artists": [{"name": "Banda"}], "duration_ms": 1},
                {"uri": "spotify:track:h2", "name": "Escondida", "artists": [{"name": "Banda"}], "duration_ms": 1}]


class ListenerCapTest(FreshMatches):
    def setUp(self):
        super().setUp()
        discovery.fan_counts = discovery.FanCounts()

    def test_check(self):
        fake = FakeLastFm({"Pequena": 50, "Grande": 500})
        cap = discovery.ListenerCap(100, fake)
        self.assertEqual(cap.check("A", "Pequena"), (True, {"listeners": 50, "url": "https://www.last.fm/_/Pequena"}))
        self.assertEqual(cap.check("A", "Grande")[0], False)
        self.assertEqual(cap.check("A", "Sumida"), (True, {"listeners": None, "url": None}))  # no record fits
        self.assertEqual(discovery.ListenerCap(0, fake).check("A", "Pequena")[0], False)
        self.assertEqual(discovery.NO_CAP.check("A", "Pequena"), (True, None))
        self.assertEqual(len(fake.asked), 4)  # NO_CAP asked nothing

    def test_genre_pick_skips_tracks_over_the_cap_before_spotify(self):
        deezer = FakeDeezer(
            playlists={"fado": [{"id": "p", "nb_tracks": 30, "title": "Fado"}]},
            tracks={"p": [dz_track(1, 120, title="Grande"), dz_track(2, 120, title="Pequena")]},
        )
        sp = FakeSpotify()
        sp.search = mock.Mock(wraps=sp.search)
        cap = discovery.ListenerCap(100, FakeLastFm({"Grande": 5000, "Pequena": 30}))
        find = discovery.world_genre_pick(sp, deezer, random.Random(1), genre="fado", listeners=cap)
        self.assertEqual(find.uri, "spotify:track:2")
        self.assertEqual(find.lastfm, {"listeners": 30, "url": "https://www.last.fm/_/Pequena"})
        self.assertNotIn(mock.call("isrc:ISRC1", "track"), sp.search.call_args_list)

    def test_barely_played_album_offers_its_hidden_track(self):
        cap = discovery.ListenerCap(100, FakeLastFm({"Famosa": 9000, "Escondida": 10}))
        for seed in range(6):
            find = discovery.obscure_album_pick(HipsterSpotify(), random.Random(seed), listeners=cap)
            self.assertEqual((find.uri, find.lastfm["listeners"]), ("spotify:track:h2", 10))

    def test_rabbit_hole_keeps_the_artists_tracks_under_the_cap(self):
        deezer = FakeDeezer(
            artists={"Chet Baker": {"id": 1, "name": "Chet Baker", "nb_fan": 500000}},
            related={1: [{"id": 2, "name": "Sonny Clark", "nb_fan": 3800}],
                     2: [{"id": 3, "name": "Tina Brooks", "nb_fan": 644}]},
            tops={2: [{"id": 21, "title": "Cool Struttin'"}],
                  3: [{"id": 31, "title": "Eu e a Brisa"}, {"id": 32, "title": "Rapaz de Bem"}, {"id": 33, "title": "Mar Aberto"}]},
        )
        fake = FakeLastFm({"Eu e a Brisa": 900, "Rapaz de Bem": 12})
        sp = FakeSpotify()
        sp.search = mock.Mock(wraps=sp.search)
        hunt = discovery.Hunt("rabbit", "Toca do coelho")
        discovery.rabbit_hole(hunt, sp, deezer, random.Random(), ["Chet Baker"], walks=1,
                              listeners=discovery.ListenerCap(100, fake))
        self.assertEqual([f.uri for f in hunt.finds], ["spotify:track:21", "spotify:track:32", "spotify:track:33"])
        self.assertIn(("Tina Brooks", "Eu e a Brisa"), fake.asked)  # asked with the hop's artist
        self.assertNotIn(mock.call("isrc:ISRC31", "track"), sp.search.call_args_list)

    def test_news_checks_each_release_before_spotify(self):
        today = date.today()
        deezer = FakeDeezer(
            playlists={"k-pop": [{"id": "p", "nb_tracks": 30, "title": "K-pop"}]},
            tracks={"p": [song(1, "x", 10, "Banda"), song(2, "x", 20, "Outra")]},
            albums={10: [{"id": 100, "title": "Hit", "release_date": today.isoformat(), "record_type": "single"}],
                    20: [{"id": 200, "title": "Lado B", "release_date": today.isoformat(), "record_type": "single"}]},
            album_songs={100: [song(1001, "Hit", 10, "Banda")], 200: [song(2001, "Lado B", 20, "Outra")]},
        )
        sp = FakeSpotify()
        sp.search = mock.Mock(wraps=sp.search)
        hunt = discovery.Hunt("news", "Novidades: K-pop")
        discovery.news(hunt, sp, deezer, "k-pop", days=7,
                       listeners=discovery.ListenerCap(100, FakeLastFm({"Hit": 80_000, "Lado B": 40})))
        self.assertEqual([(f.uri, f.lastfm["listeners"]) for f in hunt.finds], [("spotify:track:2001", 40)])
        self.assertNotIn(mock.call("isrc:ISRC1001", "track"), sp.search.call_args_list)

    def test_sense_only_listens_to_tracks_within_the_cap(self):
        deezer = FakeDeezer(
            playlists={"treino": [{"id": "p", "nb_tracks": 50}]},
            tracks={"p": [dz_track(1, 128), dz_track(2, 130), dz_track(3, 140)]},
        )
        cap = discovery.ListenerCap(100, FakeLastFm({"Faixa 1": 900, "Faixa 2": 10}))
        hunt = discovery.Hunt("sense", "Treino pesado")
        discovery.sense(hunt, {**SPEC, "sources": ["treino"]}, FakeSpotify(), deezer, random.Random(1), MemoryCache(),
                        fake_measure, listeners=cap)
        self.assertEqual(sorted((f.uri, f.lastfm["listeners"]) for f in hunt.finds),
                         [("spotify:track:2", 10), ("spotify:track:3", None)])
        self.assertEqual(hunt.progress, 2)  # Faixa 1's preview was never measured

    def test_sense_says_when_nothing_is_within_the_cap(self):
        deezer = FakeDeezer(playlists={"treino": [{"id": "p", "nb_tracks": 50}]}, tracks={"p": [dz_track(1, 128)]})
        hunt = discovery.Hunt("sense", "Treino pesado")
        discovery.sense(hunt, {**SPEC, "sources": ["treino"]}, FakeSpotify(), deezer, random.Random(1), MemoryCache(),
                        fake_measure, listeners=discovery.ListenerCap(100, FakeLastFm({"Faixa 1": 900})))
        self.assertEqual(hunt.finds, [])
        self.assertIn("limite de ouvintes", hunt.message)

    def test_within_listeners_stops_scanning(self):
        fake = FakeLastFm({f"Faixa {n}": 900 for n in range(5)})
        tracks = [dz_track(n, 120) for n in range(5)]
        with mock.patch.object(discovery, "LISTENER_SCAN_MAX", 3):
            self.assertEqual(discovery.within_listeners(tracks, discovery.ListenerCap(100, fake), want=2), [])
        self.assertEqual(len(fake.asked), 3)
        kept = discovery.within_listeners(tracks, discovery.ListenerCap(1000, FakeLastFm({})), want=2)
        self.assertEqual([(t["id"], t["lastfm"]) for t in kept], [(0, {"listeners": None, "url": None}),
                                                                 (1, {"listeners": None, "url": None})])
        self.assertEqual(discovery.within_listeners(tracks, discovery.NO_CAP, want=2), tracks[:2])

    def test_lastfm_failures_stop_the_roulette(self):
        deezer = FakeDeezer(
            playlists={"fado": [{"id": "p", "nb_tracks": 30, "title": "Fado"}]},
            tracks={"p": [dz_track(1, 120)]},
        )
        hunt = discovery.Hunt("roulette", "Roleta")
        with self.assertRaises(lastfm.LastFmError):
            discovery.roulette(hunt, FakeSpotify(), deezer, random.Random(1), genre="fado",
                               listeners=discovery.ListenerCap(100, FakeLastFm(error="down")))
```

And in the existing `FiltersTest` class, after `test_tight_cap_skips_barely_played_albums`, add:

```python
    def test_tight_listener_cap_skips_barely_played_albums(self):
        _, searched = self.spin(listeners=discovery.ListenerCap(500, FakeLastFm()))
        self.assertTrue(all(query.startswith("isrc:") for query in searched))
```

(`FakeLastFm` is defined later in the module; that's fine, it's only looked up when the test runs.)

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m unittest tests.test_discovery`
Expected: errors such as `AttributeError: module 'spotify_assistant.discovery' has no attribute 'ListenerCap'` and
`TypeError: ... got an unexpected keyword argument 'listeners'`.

- [ ] **Step 3: Add `ListenerCap`, `Find.lastfm` and `within_listeners`**

In `spotify_assistant/discovery.py`:

1. Imports: add `from .lastfm import Listeners` after `from .deezer import Deezer, DeezerError`.
2. Constants: after `TIGHT_CAP = 1_000`, add:

```python
LISTENER_SCAN_MAX = 240  # Sensations: candidates checked on Last.fm at most, before measuring any BPM
```

3. In `class Find`, after `fans: int | None = None  # the artist's fans, when we know them`, add:

```python
    lastfm: dict | None = None  # {"listeners": int | None, "url": str | None} when checked on Last.fm
```

4. After `ANY_SIZE = FanRange()`, add:

```python
@dataclass(frozen=True)
class ListenerCap:
    """Song listeners the person allows at most (counted on Last.fm), and the cached lookup that counts them."""

    max: int | None = None
    lookup: Callable[[str, str], Listeners] | None = None

    @property
    def active(self) -> bool:
        return self.max is not None

    def check(self, artist: str, title: str) -> tuple[bool, dict | None]:
        """(fits, what Last.fm said). A track Last.fm has no record of fits; without a cap nothing is asked."""
        if not self.active:
            return True, None
        found = self.lookup(artist, title)
        return found.count is None or found.count <= self.max, {"listeners": found.count, "url": found.url}


NO_CAP = ListenerCap()
```

5. Replace `find_from` with:

```python
def find_from(track: dict, reason: str = "", bpm: float | None = None, energy: float | None = None,
              image: str | None = None, tag: str = "", released: str | None = None, fans: int | None = None,
              lastfm: dict | None = None) -> Find:
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
        lastfm=lastfm,
    )
```

6. After `within_size`, add:

```python
def within_listeners(
    tracks: list[dict], listeners: ListenerCap, want: int, hunt: Hunt | None = None,
) -> list[dict]:
    """The first `want` tracks within the listener cap, asking Last.fm about LISTENER_SCAN_MAX of them at most."""
    if not listeners.active:
        return tracks[:want]
    kept: list[dict] = []
    for track in tracks[:LISTENER_SCAN_MAX]:
        if hunt and hunt.cancelled:
            break
        fits, heard = listeners.check(track["artist"]["name"], track["title"])
        if fits:
            kept.append({**track, "lastfm": heard})
            if hunt:
                hunt.message = t("sense.checking_listeners", count=len(kept))
            if len(kept) >= want:
                break
    return kept
```

- [ ] **Step 4: Sensations**

In `sense(...)`, add the parameter `listeners: ListenerCap = NO_CAP,` after `size: FanRange = ANY_SIZE,`, and replace:

```python
    by_consensus = spec.get("bpm") is None
    candidates = within_size(dz, candidates, size, CONSENSUS_LISTEN if by_consensus else SENSE_MAX_LISTEN, hunt)
    if hunt.cancelled:
        return
    if not candidates:
        hunt.message = t("sense.no_size", name=spec["name"])
        return
```

with:

```python
    by_consensus = spec.get("bpm") is None
    want = CONSENSUS_LISTEN if by_consensus else SENSE_MAX_LISTEN
    # With a listener cap, more right-sized candidates are gathered: Last.fm turns some of them down.
    candidates = within_size(dz, candidates, size, LISTENER_SCAN_MAX if listeners.active else want, hunt)
    if hunt.cancelled:
        return
    if not candidates:
        hunt.message = t("sense.no_size", name=spec["name"])
        return
    candidates = within_listeners(candidates, listeners, want, hunt)
    if hunt.cancelled:
        return
    if not candidates:
        hunt.message = t("sense.no_listeners", name=spec["name"])
        return
```

In `_add_find`, replace `hunt.finds.append(find_from(match, bpm=bpm, energy=analysis.energy, fans=fans))` with:

```python
        hunt.finds.append(find_from(match, bpm=bpm, energy=analysis.energy, fans=fans, lastfm=track.get("lastfm")))
```

- [ ] **Step 5: Roulette**

Replace the end of `obscure_album_pick` (from `fans = None` to the end of the function) and its signature:

```python
def obscure_album_pick(
    sp: Spotify, rng: random.Random, blocked: Collection[str] = frozenset(),
    dz: Deezer | None = None, size: FanRange = ANY_SIZE, listeners: ListenerCap = NO_CAP,
) -> Find | None:
```

```python
    fans = None
    if size.active and dz is not None:
        first_artist = (album.get("artists") or [{}])[0].get("name", "")
        fans = fan_counts.by_name(dz, first_artist) if first_artist else None
        if fans is None or not size.ok(fans):
            return None
    rng.shuffle(secular)
    for pick in secular[:6]:  # with a listener cap, the album's quieter tracks get their turn
        fits, heard = listeners.check(pick["artists"][0]["name"], pick["name"])
        if fits:
            return find_from(
                pick,
                reason=t("reason.obscure_album", year=year),
                image=pick_image(album.get("images"), 64),
                tag=str(year),
                fans=fans,
                lastfm=heard,
            )
    return None
```

In `world_genre_pick`, add `listeners: ListenerCap = NO_CAP,` to the signature after `size: FanRange = ANY_SIZE,` and
replace the loop section:

```python
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
```

with:

```python
    # With no filter, lean toward the less popular side; with a size or a listener cap, the filters decide.
    pool = tracks if size.active or listeners.active else lesser_known(tracks)
    rng.shuffle(pool)
    for track in pool[:6]:
        fans = fan_counts.by_id(dz, track["artist"]["id"]) if size.active else None
        if size.active and not size.ok(fans):
            continue
        fits, heard = listeners.check(track["artist"]["name"], track["title"])
        if not fits:
            continue
        match = to_spotify(sp, track)
        if match and not blocked_track(match, blocked):
            return find_from(match, reason=t("reason.genre_playlist", genre=genre), tag=genre.capitalize(),
                             fans=fans, lastfm=heard)
    return None
```

In `roulette`, add `listeners: ListenerCap = NO_CAP,` after `rare: bool = False,`, and replace:

```python
    budget = count * (6 if genre or rare or size.active else 4)  # filters throw away more attempts
    playlists_only = bool(genre) or rare or (size.max is not None and size.max <= TIGHT_CAP)
```

with:

```python
    budget = count * (6 if genre or rare or size.active or listeners.active else 4)  # filters throw away more attempts
    tight = any(cap is not None and cap <= TIGHT_CAP for cap in (size.max, listeners.max))
    playlists_only = bool(genre) or rare or tight
```

and pass the cap on in the loop:

```python
                find = world_genre_pick(sp, dz, rng, blocked, genre=genre, size=size, listeners=listeners)
            else:
                find = obscure_album_pick(sp, rng, blocked, dz=dz, size=size, listeners=listeners)
```

(`LastFmError` is not in the loop's `except (SpotifyError, DeezerError)`, so it ends the spin, as intended.)

- [ ] **Step 6: New releases**

In `news(...)`, add `listeners: ListenerCap = NO_CAP,` after `blocked: Collection[str] = frozenset(),`. In the second
loop, replace:

```python
        if track is None or religious_track(track) or blocked_track(track, blocked):
            continue
        match = to_spotify(sp, track)
```

with:

```python
        if track is None or religious_track(track) or blocked_track(track, blocked):
            continue
        fits, heard = listeners.check(artist["name"], track["title"])
        if not fits:
            continue
        match = to_spotify(sp, track)
```

and add `lastfm=heard,` to that `find_from(...)` call, after `fans=fans,`.

- [ ] **Step 7: Rabbit hole**

Replace `artist_picks` with:

```python
def artist_picks(
    sp: Spotify, dz: Deezer, artist: dict, wanted: int, reason: str, taken: set[str],
    blocked: Collection[str] = frozenset(), listeners: ListenerCap = NO_CAP,
) -> list[Find]:
    """The artist's most-played tracks that exist on Spotify (without repeating the same song)."""
    picks: list[Find] = []
    # With a listener cap the artist's biggest hits often don't fit: look further down the list.
    for top in dz.top_tracks(artist["id"], limit=10 if listeners.active else 5):
        title = curation.normalize(curation.base_title(top.get("title", "")))
        if title and title in taken:  # the same song in another recording
            continue
        if religious_track(top):
            continue
        fits, heard = listeners.check(artist["name"], top.get("title", ""))
        if not fits:
            continue
        match = to_spotify(sp, dz.track(top["id"]))  # the "top" entry has no ISRC
        if match and match["uri"] not in taken and not religious_track(match) and not blocked_track(match, blocked):
            taken.update({title, match["uri"]})
            picks.append(find_from(match, reason=reason, fans=artist.get("nb_fan"), lastfm=heard))
        if len(picks) == wanted:
            break
    return picks
```

In `rabbit_hole(...)`, add `listeners: ListenerCap = NO_CAP,` after `size: FanRange = ANY_SIZE,`, and change the call to:

```python
                finds.extend(artist_picks(sp, dz, artist, RABBIT_TRACKS if last else 1, reason, taken, blocked,
                                          listeners))
```

- [ ] **Step 8: Server messages**

In `spotify_assistant/i18n.py`, in the Portuguese block, after the `"sense.checking_size": ...` line, add:

```python
        "sense.checking_listeners": "Conferindo ouvintes no Last.fm: {count} dentro do limite até agora.",
        "sense.no_listeners": "Nenhuma música das playlists sobre “{name}” dentro do limite de ouvintes. Aumente o limite.",
```

In the English block, after its `"sense.checking_size": ...` line, add:

```python
        "sense.checking_listeners": "Checking listeners on Last.fm: {count} within the limit so far.",
        "sense.no_listeners": "No songs from the playlists about “{name}” within the listener limit. Raise the limit.",
```

- [ ] **Step 9: Run the tests to verify they pass**

Run: `python -m unittest tests.test_discovery tests.test_i18n`
Expected: PASS.

- [ ] **Step 10: Run the whole suite**

Run: `python -m unittest discover -s tests`
Expected: all tests pass (the dashboard still calls the discoveries without `listeners`, which defaults to `NO_CAP`).

- [ ] **Step 11: Commit**

```bash
git add spotify_assistant/discovery.py spotify_assistant/i18n.py tests/test_discovery.py
git commit -m "Discoveries: a song listener cap, checked before searching Spotify"
```

---

### Task 3: Server wiring: key, validation, recipes, errors

**Files:**
- Modify: `spotify_assistant/config.py` (`Settings`, `load_settings`)
- Modify: `spotify_assistant/dashboard.py` (imports, `App.__init__`, `fan_range` neighbor, `overview`, `_hunt_task`,
  `_run_hunt`, `_refresh`)
- Modify: `spotify_assistant/i18n.py`
- Modify: `.env.example`
- Test: `tests/test_dashboard.py`, `tests/test_lastfm.py`

**Interfaces:**
- Consumes: `lastfm.LastFm`, `lastfm.ListenerCounts`, `lastfm.LastFmError` (Task 1); `discovery.ListenerCap`,
  `discovery.NO_CAP` and the `listeners=` keyword of each discovery (Task 2).
- Produces:
  - `config.Settings.lastfm_key: str = ""` (fourth field).
  - `dashboard.listener_cap(body: dict, counts) -> discovery.ListenerCap`.
  - `App.listener_counts: lastfm.ListenerCounts | None`.
  - `/api/overview` field `"lastfm": bool`; recipes carry `"max_listeners": int | None`.
  - Server messages `err.listeners_invalid`, `lastfm.no_key`, `lastfm.key`, `lastfm.limit`, `lastfm.down`.

- [ ] **Step 1: Write the failing tests**

In `tests/test_lastfm.py`, add `import os` to the imports, `from spotify_assistant import config, lastfm` (replacing
`from spotify_assistant import lastfm`), and append:

```python
class SettingsTest(unittest.TestCase):
    def test_the_key_comes_from_env(self):
        with mock.patch.object(config, "load_env"), \
                mock.patch.dict(os.environ, {"SPOTIFY_CLIENT_ID": "x", "LASTFM_API_KEY": " chave "}):
            self.assertEqual(config.load_settings().lastfm_key, "chave")
        with mock.patch.object(config, "load_env"), mock.patch.dict(os.environ, {"SPOTIFY_CLIENT_ID": "x"}, clear=True):
            self.assertEqual(config.load_settings().lastfm_key, "")
```

In `tests/test_dashboard.py`, add `from spotify_assistant.lastfm import LastFmError, Listeners` after the existing
`from spotify_assistant.config import Settings`, add this class after `FakeSpotify`:

```python
class FakeCounts:
    """Stands in for the cached Last.fm lookups: no request ever goes out."""

    def __init__(self):
        self.saved = 0

    def get(self, artist, title):
        return Listeners(None, None)

    def save(self):
        self.saved += 1
```

and add these methods to `ServerTest` (after `test_roulette_of_little_known_genres_is_kept_in_the_recipe`):

```python
    def test_overview_says_whether_the_room_has_lastfm(self):
        self.assertFalse(json.loads(self.request("/api/overview")[1])["lastfm"])
        self.server.app.listener_counts = FakeCounts()
        self.assertTrue(json.loads(self.request("/api/overview")[1])["lastfm"])

    def test_listener_cap_is_validated(self):
        def start(body):
            return self.request("/api/hunts", {"kind": "roulette", **body})

        with mock.patch.object(dashboard.App, "_run_hunt", staticmethod(lambda *args: None)):
            status, body = start({"max_listeners": 100})
            self.assertEqual(status, 400)
            self.assertIn("chave do Last.fm", json.loads(body)["error"])  # this room has no key
            self.server.app.listener_counts = FakeCounts()
            self.assertEqual(start({"max_listeners": "muitos"})[0], 400)
            self.assertEqual(start({"max_listeners": -1})[0], 400)
            self.assertEqual(start({"max_listeners": "0"})[0], 200)
            self.assertEqual(start({"max_listeners": 100})[0], 200)
            self.assertEqual(self.server.app.profile("paulo").hunt.recipe["max_listeners"], 100)
            self.assertEqual(start({})[0], 200)
            self.assertIsNone(self.server.app.profile("paulo").hunt.recipe["max_listeners"])

    def test_discovery_with_a_cap_saves_the_lastfm_cache(self):
        counts = self.server.app.listener_counts = FakeCounts()
        user = self.server.app.profile("paulo")
        seen = []
        with mock.patch.object(dashboard.discovery, "roulette", lambda *args, **kwargs: seen.append(kwargs["listeners"])):
            hunt, task = self.server.app._hunt_task(user, self.fake, {"kind": "roulette", "max_listeners": 50}, None)
            task()
        self.assertEqual((seen[0].max, counts.saved), (50, 1))

    def test_lastfm_failures_end_the_discovery_with_a_message(self):
        from spotify_assistant.discovery import Hunt

        def fails():
            raise LastFmError("key")

        self.addCleanup(i18n.use, i18n.DEFAULT)  # _run_hunt sets this thread's language
        hunt = Hunt("roulette", "Roleta")
        dashboard.App._run_hunt(hunt, fails, "pt")
        self.assertEqual((hunt.status, hunt.message), ("error", i18n.MESSAGES["pt"]["lastfm.key"]))

    def test_favorite_with_a_listener_cap_and_no_key_keeps_its_songs(self):
        self.addCleanup(i18n.use, i18n.DEFAULT)  # run_due switches to the favorite's language
        self.make_favorite()
        favorites.change("ana", lambda items: items[0].update(last_run=1, recipe={**items[0]["recipe"], "max_listeners": 100}))
        self.fake.replaced.clear()
        self.server.app.run_due()
        fav = favorites.load("ana")[0]
        # The favorite was made from a Portuguese panel, so its updates speak Portuguese.
        self.assertEqual((fav["status"], fav["message"]), ("error", i18n.MESSAGES["pt"]["lastfm.no_key"]))
        self.assertEqual(self.fake.replaced, [])
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m unittest tests.test_lastfm tests.test_dashboard`
Expected: failures and errors: `AttributeError: 'Settings' object has no attribute 'lastfm_key'`,
`KeyError: 'lastfm'` in the overview test, 200 instead of 400 for `max_listeners` without a key.

- [ ] **Step 3: Settings**

In `spotify_assistant/config.py`, add a field to `Settings`:

```python
@dataclass(frozen=True)
class Settings:
    client_id: str
    redirect_uri: str  # login callback when the panel is opened on the host PC itself
    public_url: str = ""  # public address (tunnel) that friends use to get in, no trailing slash
    lastfm_key: str = ""  # optional: song listeners for the discoveries' filter
```

and in `load_settings()` pass it:

```python
    return Settings(
        client_id,
        os.environ.get("SPOTIFY_REDIRECT_URI") or DEFAULT_REDIRECT_URI,
        os.environ.get("SALA_PUBLIC_URL", "").strip().rstrip("/"),
        os.environ.get("LASTFM_API_KEY", "").strip(),
    )
```

- [ ] **Step 4: Dashboard**

In `spotify_assistant/dashboard.py`:

1. Imports: add `lastfm` to `from . import accounts, artists, config, ...` (keep alphabetical order: after `i18n`), and
   add `from .lastfm import LastFmError` after `from .i18n import t`.
2. In `App.__init__`, after `self.musicbrainz = MusicBrainz()`, add:

```python
        # Song listeners for the discoveries' filter: only when the room has a Last.fm key.
        self.listener_counts = (lastfm.ListenerCounts(lastfm.LastFm(settings.lastfm_key))
                                if settings.lastfm_key else None)
```

3. After the `fan_range` function, add:

```python
def listener_cap(body: dict, counts: lastfm.ListenerCounts | None) -> discovery.ListenerCap:
    """Song listeners asked for in the panel ("max_listeners"; empty = no cap), counted on Last.fm."""
    raw = body.get("max_listeners")
    if raw in (None, ""):
        return discovery.NO_CAP
    try:
        value = int(raw)
    except (TypeError, ValueError):
        raise UserError(t("err.listeners_invalid")) from None
    if value < 0:
        raise UserError(t("err.listeners_invalid"))
    if counts is None:
        raise UserError(t("lastfm.no_key"))
    return discovery.ListenerCap(value, counts.get)
```

4. In `overview`, after `"search_paused_s": gate.remaining("search"),`, add `"lastfm": self.listener_counts is not None,`.
5. In `_hunt_task`, replace:

```python
        size = fan_range(body)
        recipe = {"kind": kind, "min_fans": size.min or None, "max_fans": size.max}
```

with:

```python
        size = fan_range(body)
        listeners = listener_cap(body, self.listener_counts)
        recipe = {"kind": kind, "min_fans": size.min or None, "max_fans": size.max, "max_listeners": listeners.max}
```

   and pass `listeners=listeners` to the four discovery calls:

```python
                    discovery.sense(hunt, spec, sp, self.deezer, rng, cache, blocked=user.blocked, size=size,
                                    listeners=listeners)
```
```python
                discovery.roulette(hunt, sp, self.deezer, rng, blocked=user.blocked, genre=genre, size=size, rare=rare,
                                   listeners=listeners)
```
```python
                discovery.rabbit_hole(hunt, sp, self.deezer, rng, seeds, blocked=user.blocked, size=size,
                                      listeners=listeners)
```
```python
                discovery.news(hunt, sp, self.deezer, genre, size, days, blocked=user.blocked, listeners=listeners)
```

   Then, right before `hunt.recipe = recipe` at the end of `_hunt_task`, add:

```python
        if listeners.active:
            run = task

            def task() -> None:  # the counts learned along the way survive a restart
                try:
                    run()
                finally:
                    self.listener_counts.save()
```

6. In `_run_hunt`, before `except UserError as err:`, add:

```python
        except LastFmError as err:
            kind = err.kind
            log.warning("Discovery stopped by Last.fm: %s", kind)
            hunt.status = "error"
            hunt.message = t(f"lastfm.{kind}")
```

7. In `_refresh`, replace:

```python
            except (DeezerError, UserError) as err:
                status, message = "error", t("err.discovery_failed", error=err)
```

with:

```python
            except DeezerError as err:
                status, message = "error", t("err.discovery_failed", error=err)
            except UserError as err:  # e.g. a listener cap in a room that no longer has a Last.fm key
                status, message = "error", str(err)
            except LastFmError as err:
                kind = err.kind
                status, message = "error", t(f"lastfm.{kind}")
```

   Before changing this, run `grep -rn "falhou (" tests/` and `grep -rn "failed (" tests/`: if a test expects a
   favorite's `UserError` to come wrapped in "discovery failed", update that test's expectation to the plain message.

- [ ] **Step 5: Server messages**

In `spotify_assistant/i18n.py`, Portuguese block, after `"err.fans_order": ...`, add:

```python
        "err.listeners_invalid": "Número de ouvintes inválido.",
        "lastfm.no_key": "Esta sala não tem a chave do Last.fm (LASTFM_API_KEY), então o filtro de ouvintes não está disponível.",
        "lastfm.key": "O Last.fm não aceitou a chave desta sala. Confira LASTFM_API_KEY no .env.",
        "lastfm.limit": "O Last.fm pediu uma pausa. Tente de novo em alguns minutos ou sem o filtro de ouvintes.",
        "lastfm.down": "O Last.fm não respondeu. Tente de novo mais tarde ou sem o filtro de ouvintes.",
```

English block, after `"err.fans_order": ...`, add:

```python
        "err.listeners_invalid": "Invalid number of listeners.",
        "lastfm.no_key": "This room has no Last.fm key (LASTFM_API_KEY), so the listener filter isn't available.",
        "lastfm.key": "Last.fm didn't accept this room's key. Check LASTFM_API_KEY in .env.",
        "lastfm.limit": "Last.fm asked for a break. Try again in a few minutes or without the listener filter.",
        "lastfm.down": "Last.fm didn't answer. Try again later or without the listener filter.",
```

- [ ] **Step 6: `.env.example`**

Append to `.env.example`:

```
# Optional: song listeners counted on Last.fm, for the discoveries' filter.
# Create a free API account at https://www.last.fm/api/account/create and paste the "API key" here.
LASTFM_API_KEY=
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `python -m unittest tests.test_lastfm tests.test_dashboard tests.test_i18n`
Expected: PASS.

- [ ] **Step 8: Run the whole suite**

Run: `python -m unittest discover -s tests`
Expected: all tests pass.

- [ ] **Step 9: Commit**

```bash
git add spotify_assistant/config.py spotify_assistant/dashboard.py spotify_assistant/i18n.py .env.example tests/test_dashboard.py tests/test_lastfm.py
git commit -m "Server: Last.fm key, listener cap validation, recipes and messages"
```

---

### Task 4: Panel, docs and screen check

**Files:**
- Modify: `spotify_assistant/static/app.js` (constants near `SIZE_MAX`, `senseIntro`, `discoverIntro`, `newsIntro`,
  `sizeBody`, `sizeFilters`, `findRow`)
- Modify: `spotify_assistant/static/i18n.js`
- Modify: `README.md`, `README.pt-BR.md`, `CLAUDE.md` (Rules)
- Scratch (not committed): `<scratchpad>/fake_panel.py`, `<scratchpad>/shots.mjs`

**Interfaces:**
- Consumes: `/api/overview` `"lastfm"`; request field `max_listeners`; `find.lastfm` (`{"listeners", "url"}`).
- Produces: browser keys `filter.listeners`, `filter.listeners_hint`, `find.listeners`, `find.no_listeners`.

- [ ] **Step 1: Browser texts**

In `spotify_assistant/static/i18n.js`, Portuguese block, after `"size.no_cap": "Sem teto",`, add:

```json
    "filter.listeners": "Ouvintes da música: no máximo",
    "filter.listeners_hint": "Ouvintes contados no Last.fm.",
    "find.listeners": [
      "{n} ouvinte no Last.fm.",
      "{n} ouvintes no Last.fm."
    ],
    "find.no_listeners": "Sem registro no Last.fm.",
```

English block, after `"size.no_cap": "No limit",`, add:

```json
    "filter.listeners": "Song listeners: at most",
    "filter.listeners_hint": "Listeners counted on Last.fm.",
    "find.listeners": [
      "{n} listener on Last.fm.",
      "{n} listeners on Last.fm."
    ],
    "find.no_listeners": "No record on Last.fm.",
```

- [ ] **Step 2: Check the texts still parse**

Run: `python -m unittest tests.test_i18n`
Expected: PASS. This only guards the JSON and the parity between languages (a syntax error makes `browser_strings()`
fail); the keys get used in Step 3.

- [ ] **Step 3: Filter, hint and request body**

In `spotify_assistant/static/app.js`:

1. After `const SIZE_MAX = [...]`, add:

```js
// Song listeners are counted on Last.fm, only in rooms that have a Last.fm key.
const LISTENERS_MAX = ["", "50", "100", "500", "1000", "10000"];
```

2. Replace `sizeFilters` and `sizeBody`:

```js
function sizeBody() {
  // A cap saved while the room had a Last.fm key is left out once it no longer has one.
  const listeners = state.overview?.lastfm ? state.filters.listeners || null : null;
  return { min_fans: state.filters.min || null, max_fans: state.filters.max || null, max_listeners: listeners };
}
```

```js
function sizeFilters() {
  const options = (values, empty) => values.map((value) => [value, value ? compactNumber.format(Number(value)) : t(empty)]);
  return [
    choice("min-fans", t("filter.min"), options(SIZE_MIN, "size.any"), "min"),
    choice("max-fans", t("filter.max"), options(SIZE_MAX, "size.no_cap"), "max"),
    state.overview?.lastfm && choice("max-listeners", t("filter.listeners"), options(LISTENERS_MAX, "size.no_cap"), "listeners"),
  ];
}

/** Credit for the listener numbers: Last.fm's terms ask for it wherever they show. */
function listenersHint() {
  return state.overview?.lastfm && h("p", { class: "filter-hint" },
    h("a", { href: "https://www.last.fm/", target: "_blank", rel: "noopener" }, t("filter.listeners_hint")));
}
```

3. Use the hint in the three views:
   - `senseIntro`: after `h("p", { class: "filter-hint" }, t("sense.size_hint"))` add `, listenersHint()` inside the same
     `h("div", { class: "filters" }, ...)`.
   - `discoverIntro`: after `h("p", { class: "filter-hint" }, t("discover.size_hint")),` add `listenersHint(),`.
   - `newsIntro`: after `h("button", { class: "play-button", type: "submit" }, t("news.search")),` add `listenersHint(),`.

4. In `findRow`, inside `open && h("div", { class: "find-details" }, ...)`, after `details && h("span", null, details),`
   add `find.lastfm && lastfmLine(find.lastfm),`, and add this function after `findDetails`:

```js
/** "123 listeners on Last.fm", linked to the track's page there (Last.fm's terms ask for the link). */
function lastfmLine(info) {
  if (info.listeners == null) return h("span", null, t("find.no_listeners"));
  const text = t("find.listeners", { count: info.listeners, n: compactNumber.format(info.listeners) });
  return info.url ? h("a", { class: "text-button", href: info.url, target: "_blank", rel: "noopener" }, text)
    : h("span", null, text);
}
```

- [ ] **Step 4: Syntax and i18n check**

Run: `node --check spotify_assistant/static/app.js && python -m unittest tests.test_i18n`
Expected: no output from node; i18n tests PASS (now the four keys are used and exist).

- [ ] **Step 5: Screen check with a fake panel**

Write `<scratchpad>/fake_panel.py` (the scratchpad path from the session's environment), which serves the panel on port
8890 with temporary data and the tests' fake Spotify, with a Last.fm key so the filter shows (no hunt ever runs:
`_run_hunt` is patched):

```python
"""The panel on port 8890 with temporary data and the tests' fake Spotify (never touches real accounts)."""
import json
import sys
import tempfile
from pathlib import Path
from unittest import mock

repo = Path(sys.argv[1])
sys.path.insert(0, str(repo))
from spotify_assistant import auth, config, dashboard
from spotify_assistant.config import Settings
from tests.test_dashboard import CONFIG, FakeCounts, FakeSpotify

data = Path(tempfile.mkdtemp(prefix="sala-fake-"))
(data / "playlists.json").write_text(json.dumps(CONFIG), encoding="utf-8")
token = {"scope": auth.SCOPES, "access_token": "x", "refresh_token": "y", "expires_at": 4_000_000_000}
folder = data / "users" / "paulo"
folder.mkdir(parents=True)
(folder / "token.json").write_text(json.dumps(token), encoding="utf-8")
(folder / "state.json").write_text(json.dumps({"playlists": {"Jazz": "pl-jazz"}}), encoding="utf-8")
(folder / "profile.json").write_text(json.dumps({"name": "Paulo"}), encoding="utf-8")
(data / "owner.txt").write_text("paulo", encoding="utf-8")
for patcher in (mock.patch.object(config, "PLAYLISTS_FILE", data / "playlists.json"),
                mock.patch.object(config, "DATA_DIR", data),
                mock.patch.object(dashboard.gate, "remaining", return_value=0),
                mock.patch.object(dashboard.App, "_run_hunt", staticmethod(lambda *args: None))):
    patcher.start()
fake = FakeSpotify()
app = dashboard.App(Settings("client", "http://127.0.0.1:8890/callback", "http://127.0.0.1:8890"))
app.spotify = lambda user: fake
app.listener_counts = FakeCounts()  # the room "has a key"; nothing ever asks Last.fm
server = dashboard.DashboardServer(("127.0.0.1", 8890), app)
(Path(sys.argv[2]) / "cookie.txt").write_text(app.sessions.create("paulo"), encoding="utf-8")
print("ready", data, flush=True)
server.serve_forever()
```

Write `<scratchpad>/shots.mjs`, a headless Chrome DevTools script (Node 24, Chrome at
`C:/Program Files/Google/Chrome/Application/chrome.exe`) that: sets the `sala` cookie from `cookie.txt` and
`localStorage` (`lang=pt`, `tour-seen=1`); opens `#discover`, `?s#sensations` and `?n#news` at 390×844 (mobile) and
`?d#discover` at 1366×900, screenshotting each; reads the `#max-listeners` options; picks "100" in `#max-listeners`,
clicks the roulette's spin button and records the POST body to `/api/hunts`; then sets `state.hunt` to a mocked done
roulette with one find carrying `lastfm: {listeners: 42, url: "https://www.last.fm/music/X/_/Y"}` and another with
`lastfm: {listeners: null, url: null}`, adds both URIs to `state.openDetails`, sets `state.huntSignature = ""`, calls
`renderHunt()` and screenshots; and prints console errors. Use the same structure as this session's earlier
`shots.mjs` (CDP over `--remote-debugging-port=9334`, `Runtime.evaluate`, `Network.requestWillBeSent` for the POST).
Each navigation must change the URL before the hash (`?x#view`) so the page really reloads.

Run the fake panel in the background (`python -I <scratchpad>/fake_panel.py C:/dev/spotfyprsonal <scratchpad>`), wait
until `http://127.0.0.1:8890/` answers, run `node <scratchpad>/shots.mjs <scratchpad>`, then look at every screenshot.

Expected:
- The "Ouvintes da música: no máximo" select shows in Descobrir, Sensações and Novidades, with
  Sem teto/50/100/500/1 mil/10 mil, and the hint "Ouvintes contados no Last.fm." links to last.fm.
- The POST body contains `"max_listeners":"100"`.
- The mocked finds show "42 ouvintes no Last.fm." as a link and "Sem registro no Last.fm.".
- Phone width: no horizontal scroll; the new select wraps like the fans selects.
- Console clean.

Then edit `fake_panel.py` to drop the `app.listener_counts = FakeCounts()` line, restart it, and confirm with one more
run that the select and the hint are gone and the POST body has `"max_listeners":null` even though `localStorage`
still holds `listeners: "100"` (Review Focus 4). Stop the fake panel and delete its temporary `sala-fake-*` folder.

- [ ] **Step 6: README (both languages) and CLAUDE.md**

In `README.md`, after the paragraph that starts "Both take an optional genre (roulette) and the artist's size in
fans", add:

```markdown
With a Last.fm key, every discovery also takes **song listeners: at most**, counted on Last.fm (people who scrobbled
the song). A song Last.fm has no record of passes and says so. Each song is checked once a month and remembered in
`data/lastfm-cache.json`; songs over the cap are dropped before anything is searched on Spotify.
```

and after the line "`SALA_LANG` in `.env` (`en` or `pt`) sets the language of the command line and of automatic
updates.", add:

```markdown
### Last.fm (optional)

The listener filter needs a free Last.fm API key: create an API account at
https://www.last.fm/api/account/create (any application name; no callback needed), copy the "API key" into
`LASTFM_API_KEY` in `.env` and restart the panel. Without it, the filter doesn't show. Last.fm's terms ask for
credit, so the panel names Last.fm and links each song to its Last.fm page.
```

In `README.pt-BR.md`, after the paragraph that starts "As duas aceitam um gênero opcional (roleta) e o tamanho do
artista em fãs", add:

```markdown
Com uma chave do Last.fm, todas as descobertas também aceitam **ouvintes da música: no máximo**, contados no Last.fm
(pessoas que registraram a música). Uma música sem registro no Last.fm passa e a carta avisa. Cada música é conferida
uma vez por mês e fica guardada em `data/lastfm-cache.json`; as que passam do limite saem antes de qualquer busca no
Spotify.
```

and after the line "`SALA_LANG` no `.env` (`en` ou `pt`) define o idioma da linha de comando e das atualizações
automáticas.", add:

```markdown
### Last.fm (opcional)

O filtro de ouvintes precisa de uma chave grátis da API do Last.fm: crie uma conta de API em
https://www.last.fm/api/account/create (qualquer nome de aplicativo; não precisa de callback), copie a "API key" para
`LASTFM_API_KEY` no `.env` e reinicie o painel. Sem ela, o filtro não aparece. Os termos do Last.fm pedem crédito,
então o painel cita o Last.fm e liga cada música à página dela lá.
```

In `CLAUDE.md`, Rules section, replace the line `- Never mention Deezer in the UI. Never add Spotify logos to the app's branding.` with:

```markdown
- Never mention Deezer in the UI. Never add Spotify logos to the app's branding. Last.fm is credited (text and a link,
  no logo) wherever its numbers show: its terms require it.
```

- [ ] **Step 7: Run the whole suite**

Run: `python -m unittest discover -s tests`
Expected: all tests pass.

- [ ] **Step 8: Commit**

```bash
git add spotify_assistant/static/app.js spotify_assistant/static/i18n.js README.md README.pt-BR.md CLAUDE.md
git commit -m "Panel: song listener filter with Last.fm credit and links"
```

---

### Task 5: Rollout

**Files:** none in the repo.

- [ ] **Step 1: Secret check and push**

Run `git log origin/main..HEAD --stat` and `git diff origin/main..HEAD` and check that no Client ID, token, Tailscale
address, owner id or Last.fm key went in. Then `git push`.

- [ ] **Step 2: Update the server**

Run: `ssh -i ~/.ssh/sala-oracle ubuntu@<public-ip> 'bash ~/sala-de-escuta/scripts/install-linux.sh 2>&1 | tail -2; for i in $(seq 1 90); do curl -s -o /dev/null http://127.0.0.1:8888/ && echo "answering after ${i}s" && break; sleep 1; done'`
Expected: "answering after" a few seconds (the `SO_REUSEADDR` fix from commit `bdd65d2` is now on both sides of the
restart). If it takes about a minute again, report it: the fix didn't hold.

- [ ] **Step 3: The owner's key**

Ask the owner to create the key (README "Last.fm (optional)") and either add `LASTFM_API_KEY=...` to
`~/sala-de-escuta/.env` on the server themselves, or hand it over to be added with
`ssh ... "printf '\nLASTFM_API_KEY=%s\n' '<key>' >> ~/sala-de-escuta/.env"` (never echo the key into logs or commits).
Then restart: `ssh ... 'sudo systemctl restart sala-de-escuta'`.

- [ ] **Step 4: One real check**

Through an SSH tunnel (`ssh -L 8888:127.0.0.1:8888 ...`) and a session created on the server as in CLAUDE.md
("Checking the UI"), confirm `/api/overview` has `"lastfm": true`, then start **one** roulette with
`max_listeners: 1000` and read the hunt until it's done: finds carry `lastfm` with counts ≤ 1000 or `null`. End the
session afterwards. Do not repeat it in a loop.
