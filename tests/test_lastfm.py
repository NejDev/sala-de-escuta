import http.client
import io
import json
import os
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

from spotify_assistant import config, lastfm


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

    def test_similar_tracks_closest_first(self):
        payload = {"similartracks": {"track": [
            {"name": "Blue in Green", "playcount": "900", "match": "1.0", "artist": {"name": "Miles Davis"}},
            {"name": "Naima", "playcount": 5000, "match": 0.7, "artist": {"name": "John Coltrane"}},
            {"name": "", "match": 0.5, "artist": {"name": "Sem título"}},
            {"name": "Sem artista", "match": 0.4},
        ]}}
        server = LastFmServer((payload, 200))
        found = client(server).similar("Miles Davis", "So What - Remastered 2005")
        self.assertEqual(found, [lastfm.Similar("Miles Davis", "Blue in Green", 1.0, 900),
                                 lastfm.Similar("John Coltrane", "Naima", 0.7, 5000)])
        self.assertIn("method=track.getSimilar", server.urls[0])
        self.assertIn("track=So+What&", server.urls[0])

    def test_similar_to_an_unknown_track_is_none(self):
        self.assertIsNone(client(LastFmServer(({"error": 6, "message": "Track not found"}, 200))).similar("X", "Y"))
        self.assertEqual(client(LastFmServer(({"similartracks": {"track": []}}, 200))).similar("X", "Y"), [])
        with self.assertRaises(lastfm.LastFmError):
            client(LastFmServer(({"error": 10}, 403))).similar("X", "Y")

    def test_the_cache_asks_for_similar_tracks_every_time(self):
        server = LastFmServer(({"similartracks": {"track": [
            {"name": "Naima", "playcount": 5, "match": 1, "artist": {"name": "John Coltrane"}}]}}, 200))
        counts = lastfm.ListenerCounts(client(server), Path(tempfile.mkdtemp()) / "cache.json")
        for _ in range(2):
            self.assertEqual(counts.similar("Miles Davis", "So What"), [lastfm.Similar("John Coltrane", "Naima", 1.0, 5)])
        self.assertEqual(len(server.urls), 2)

    def test_what_last_fm_says_about_a_track(self):
        payload = {"track": {"name": "So What", "url": PAGE, "listeners": "1234", "playcount": "56789",
                             "toptags": {"tag": [{"name": "jazz"}, {"name": "seen live"}, {"name": "Modal Jazz"},
                                                 {"name": "favorites"}, {"name": "x" * 40}]},
                             "wiki": {"summary": "Opens &quot;Kind of Blue&quot;.\n <a href=\"" + PAGE + "\">Read more on Last.fm</a>. User-contributed text."}}}
        server = LastFmServer((payload, 200))
        found = client(server).info("Miles Davis", "So What")
        self.assertEqual(found, lastfm.TrackInfo(1234, 56789, PAGE, ("jazz", "Modal Jazz"), 'Opens "Kind of Blue".'))
        self.assertIn("method=track.getInfo", server.urls[0])
        self.assertIsNone(client(LastFmServer(({"error": 6}, 200))).info("X", "Y"))
        bare = client(LastFmServer(({"track": {"url": PAGE}}, 200))).info("X", "Y")
        self.assertEqual(bare, lastfm.TrackInfo(0, 0, PAGE, (), ""))

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

    def test_broken_connections_are_down(self):
        class Truncated(io.BytesIO):
            def read(self, *args):
                raise http.client.IncompleteRead(b"{\"track\"")

        failures = [ConnectionResetError("reset by peer"), http.client.RemoteDisconnected("closed"),
                    TimeoutError("timed out")]
        openers = [lambda request, timeout, failure=failure: (_ for _ in ()).throw(failure) for failure in failures]
        openers.append(lambda request, timeout: Truncated())
        for opener in openers:
            with self.subTest(opener=opener), self.assertRaises(lastfm.LastFmError) as caught:
                client(opener).track("X", "Y")
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

    def test_cached_reads_without_asking(self):
        counts = self.counts()
        self.assertIsNone(counts.cached("Miles Davis", "So What"))
        counts.get("Miles Davis", "So What")
        self.now[0] += lastfm.FRESH_S * 2  # however old
        self.assertEqual(counts.cached("MILES DAVIS", "So What (Live)"), lastfm.Listeners(1234, PAGE))
        self.assertEqual(len(self.server.urls), 1)

    def test_a_shorter_freshness_asks_again_sooner(self):
        counts = self.counts()
        counts.get("Banda", "Lançamento")
        self.now[0] += 86400
        counts.get("Banda", "Lançamento")  # still fresh for the default month
        self.assertEqual(len(self.server.urls), 1)
        counts.get("Banda", "Lançamento", fresh_s=86400)
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


class SettingsTest(unittest.TestCase):
    def test_the_key_comes_from_env(self):
        with mock.patch.object(config, "load_env"), \
                mock.patch.dict(os.environ, {"SPOTIFY_CLIENT_ID": "x", "LASTFM_API_KEY": " chave "}):
            self.assertEqual(config.load_settings().lastfm_key, "chave")
        with mock.patch.object(config, "load_env"), mock.patch.dict(os.environ, {"SPOTIFY_CLIENT_ID": "x"}, clear=True):
            self.assertEqual(config.load_settings().lastfm_key, "")


if __name__ == "__main__":
    unittest.main()
