import io
import json
import tempfile
import unittest
import urllib.error
import urllib.parse
from pathlib import Path

from spotify_assistant import lyrics

SYNCED = "[00:12.50] First line\n[00:15.00]\n[ar: Someone]\n[00:20.10][01:05.00] Chorus\n[00:17.3] Second"
RECORD = {"id": 7, "duration": 250.0, "instrumental": False, "plainLyrics": "First line\nChorus",
          "syncedLyrics": SYNCED}


class Lrclib:
    """A fake urlopen that answers like LRCLIB; remembers what was asked."""

    def __init__(self, get=None, search=None, status=200, retry_after=None):
        self.get, self.search, self.status, self.retry_after = get, search, status, retry_after
        self.asked = []

    def __call__(self, request, timeout):
        url = urllib.parse.urlsplit(request.full_url)
        query = dict(urllib.parse.parse_qsl(url.query))
        self.asked.append((url.path.rsplit("/", 1)[-1], query))
        if self.status != 200:
            headers = {"Retry-After": self.retry_after} if self.retry_after else {}
            raise urllib.error.HTTPError(request.full_url, self.status, "error", headers, io.BytesIO(b"{}"))
        answer = self.get if url.path.endswith("/get") else self.search
        if answer is None:
            raise urllib.error.HTTPError(request.full_url, 404, "not found", {}, io.BytesIO(b'{"code":404}'))
        return io.BytesIO(json.dumps(answer).encode())


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def library(server, clock=None):
    return lyrics.Lyrics(lyrics.Lrclib(opener=server, clock=clock or Clock()), Path(tempfile.mkdtemp()),
                         now=clock or Clock())


SONG = {"artist": "Foo Fighters", "title": "Everlong - Remastered", "album": "The Colour and the Shape",
        "duration_ms": 250_400}


class ParseTest(unittest.TestCase):
    def test_lines_in_time_order_with_repeats_and_breaks(self):
        self.assertEqual(lyrics.parse_lrc(SYNCED), [
            [12500, "First line"], [15000, ""], [17300, "Second"], [20100, "Chorus"], [65000, "Chorus"]])

    def test_text_without_times_isnt_synced(self):
        self.assertEqual(lyrics.parse_lrc("just words\nno times"), [])


class LookupTest(unittest.TestCase):
    def test_synced_lyrics_come_with_their_times(self):
        server = Lrclib(get=RECORD)
        found = library(server).get("abc", **SONG)
        self.assertEqual(found["status"], "synced")
        self.assertEqual(found["lines"][0], [12500, "First line"])
        name, query = server.asked[0]
        self.assertEqual((name, query["track_name"], query["artist_name"], query["duration"]),
                         ("get", "Everlong", "Foo Fighters", "250"))

    def test_plain_and_instrumental(self):
        plain = library(Lrclib(get={**RECORD, "syncedLyrics": None})).get("a", **SONG)
        self.assertEqual(plain, {"status": "plain", "text": "First line\nChorus"})
        instrumental = library(Lrclib(get={**RECORD, "instrumental": True, "syncedLyrics": None,
                                           "plainLyrics": None})).get("b", **SONG)
        self.assertEqual(instrumental, {"status": "instrumental"})

    def test_a_different_album_name_falls_back_to_the_search_by_length(self):
        results = [{**RECORD, "duration": 300.0, "syncedLyrics": "[00:01.00] Live version"},
                   {**RECORD, "duration": 251.0, "syncedLyrics": None, "plainLyrics": "Studio, plain"},
                   {**RECORD, "duration": 249.0, "syncedLyrics": "[00:01.00] Studio, synced"}]
        server = Lrclib(get=None, search=results)
        found = library(server).get("abc", **SONG)
        self.assertEqual(found["lines"], [[1000, "Studio, synced"]])  # same length, and synced wins
        self.assertEqual([name for name, _ in server.asked], ["get", "search"])

    def test_nothing_close_enough_is_missing_and_asked_again_a_week_later(self):
        clock = Clock()
        server = Lrclib(get=None, search=[{**RECORD, "duration": 400.0}])
        songs = library(server, clock)
        self.assertEqual(songs.get("abc", **SONG), {"status": "missing"})
        self.assertEqual(songs.get("abc", **SONG), {"status": "missing"})
        self.assertEqual(len(server.asked), 2)  # the second time came from the cache
        clock.now += lyrics.MISSING_RETRY_S + 1
        server.get = RECORD
        self.assertEqual(songs.get("abc", **SONG)["status"], "synced")

    def test_found_lyrics_are_kept_on_disk(self):
        server = Lrclib(get=RECORD)
        folder = Path(tempfile.mkdtemp())
        lyrics.Lyrics(lyrics.Lrclib(opener=server), folder).get("abc", **SONG)
        again = lyrics.Lyrics(lyrics.Lrclib(opener=Lrclib(status=500)), folder).get("abc", **SONG)
        self.assertEqual(again["status"], "synced")
        self.assertEqual(len(server.asked), 1)

    def test_too_many_requests_pauses_every_lookup(self):
        clock = Clock()
        server = Lrclib(status=429, retry_after="5")
        songs = library(server, clock)
        for _ in range(2):
            with self.assertRaises(lyrics.LyricsError) as caught:
                songs.get("abc", **SONG)
            self.assertEqual(caught.exception.kind, "busy")
        self.assertEqual(len(server.asked), 1)  # the second one waited without asking
        clock.now += lyrics.MIN_PAUSE_S + 1
        server.status, server.get = 200, RECORD
        self.assertEqual(songs.get("abc", **SONG)["status"], "synced")

    def test_other_failures_are_down_and_not_kept(self):
        for status in (500, 503):
            with self.subTest(status=status), self.assertRaises(lyrics.LyricsError) as caught:
                library(Lrclib(status=status)).get("abc", **SONG)
            self.assertEqual(caught.exception.kind, "down")

    def test_only_spotify_track_ids_name_a_file(self):
        with self.assertRaises(ValueError):
            library(Lrclib(get=RECORD)).get("../etc", **SONG)
