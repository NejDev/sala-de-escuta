import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from spotify_assistant import config, social
from spotify_assistant.api import SpotifyError

NOW = 1_800_000_000.0
DAY = 86400


def play(uri, artist, at, title=None):
    return {"uri": f"spotify:track:{uri}", "title": title or uri, "artists": [{"id": artist, "name": artist.upper()}],
            "image": None, "duration_ms": 1000, "at": at}


def listened(artists_and_counts, start=NOW - DAY):
    """Plays spread over the last day: [("a", 5), ("b", 3)] -> 5 songs by a, 3 by b."""
    plays, minute = [], 0
    for artist, count in artists_and_counts:
        for index in range(count):
            minute += 1
            plays.append(play(f"{artist}{index}", artist, start + minute * 60))
    return plays


def taste(**sources):
    """A taste profile: taste(top={"a": 1.0}, playlists={...}); artist names are the ids in capitals."""
    return {"sources": sources, "names": {key: key.upper() for weights in sources.values() for key in weights}}


def spread(*artists):
    return {artist: 1.0 for artist in artists}


def affinity(plays_a, plays_b, taste_a=None, taste_b=None):
    taste_a, taste_b = taste_a or {}, taste_b or {}
    names = {**social.artist_names(plays_a, taste_a), **social.artist_names(plays_b, taste_b)}
    return social.affinity(social.profile(plays_a, taste_a, NOW), social.profile(plays_b, taste_b, NOW), names)


class AffinityTest(unittest.TestCase):
    def test_same_taste_is_high_different_is_zero(self):
        mine = listened([("a", 8), ("b", 4), ("c", 2), ("d", 2), ("e", 2)])
        self.assertEqual(affinity(mine, listened([("a", 8), ("b", 4), ("c", 2), ("d", 2), ("e", 2)]))["percent"], 100)
        self.assertEqual(affinity(mine, listened([("v", 4), ("w", 4), ("x", 4), ("y", 4), ("z", 4)]))["percent"], 0)
        some = affinity(mine, listened([("a", 6), ("w", 4), ("x", 4), ("y", 4), ("z", 4)]))
        self.assertTrue(0 < some["percent"] < 100)
        self.assertEqual(some["shared"], ["A"])

    def test_playlists_and_most_played_count_beyond_the_last_songs(self):
        # Their last songs share nothing, but they like the same artists.
        mine = listened([("p", 4), ("q", 4), ("r", 4)])
        theirs = listened([("s", 4), ("t", 4), ("u", 4)])
        self.assertIsNone(affinity(mine, theirs))  # 3 artists each: too little to say
        both = taste(top=spread("radiohead", "bjork", "portishead"), playlists=spread("radiohead", "massive", "air"))
        other = taste(top=spread("radiohead", "portishead", "tricky"), liked=spread("air", "bjork"))
        found = affinity(mine, theirs, both, other)
        self.assertGreater(found["percent"], 30)
        self.assertLessEqual(set(found["shared"]), {"RADIOHEAD", "PORTISHEAD", "BJORK", "AIR"})  # only what both like
        self.assertIn("RADIOHEAD", found["shared"])

    def test_needs_some_history(self):
        self.assertIsNone(affinity(listened([("a", 3)]), listened([("a", 30)])))

    def test_only_the_last_month_of_plays_counts(self):
        old = listened([("v", 4), ("w", 4), ("x", 4), ("y", 4), ("z", 4)], start=NOW - 60 * DAY)
        self.assertIsNone(affinity(old, listened([("v", 4), ("w", 4), ("x", 4), ("y", 4), ("z", 4)])))


class MatchTest(unittest.TestCase):
    def test_same_song_close_in_time(self):
        mine = [play("s", "a", NOW - 3 * 3600), play("t", "a", NOW - 3 * 3600)]
        theirs = [play("s", "a", NOW - 3600), play("t", "a", NOW - 20 * 3600)]  # t: 17 h apart
        found = social.matches(mine, theirs, NOW)
        self.assertEqual([(m["track"]["uri"], m["gap_s"]) for m in found], [("spotify:track:s", 2 * 3600)])

    def test_feed_has_only_matches_newest_first(self):
        everyone = {
            "me": [play("s", "a", NOW - 7200), play("t", "a", NOW - 2 * DAY)],
            "ana": [play("s", "a", NOW - 3600), play("t", "a", NOW - 2 * DAY + 60), play("alone", "b", NOW - 600)],
        }
        events = social.feed(everyone, {"me": "Eu", "ana": "Ana"}, "me", NOW)
        # What Ana played alone ("alone") never shows up.
        self.assertEqual([(e["friend"], e["track"]["uri"]) for e in events],
                         [("Ana", "spotify:track:s"), ("Ana", "spotify:track:t")])


class FakeSpotify:
    def __init__(self, items=()):
        self.items = list(items)
        self.asked = []
        self.read = []

    def recently_played(self, after=None):
        self.asked.append(after)
        return self.items

    def top_artists(self, time_range):
        if time_range == "long_term":
            raise SpotifyError(500, "down")
        return [{"id": "bjork", "name": "Björk"}, {"id": "air", "name": "Air"}]

    def my_playlists(self):
        yield {"id": "mine", "owner": {"id": "ana"}}
        yield {"id": "followed", "owner": {"id": "spotify"}}

    def playlist_items(self, playlist_id, max_items=None):
        self.read.append(playlist_id)
        return [{"type": "track", "artists": [{"id": "air", "name": "Air"}, {"id": "beck", "name": "Beck"}]},
                {"type": "episode", "artists": [{"id": "podcast", "name": "A podcast"}]}]

    def saved_tracks(self, max_items=100):
        raise SpotifyError(403, "not allowed")


def item(uri, when):
    stamp = datetime.fromtimestamp(when, timezone.utc).isoformat().replace("+00:00", "Z")
    return {"played_at": stamp, "track": {"uri": uri, "name": uri, "duration_ms": 1,
                                          "artists": [{"id": "a", "name": "A"}], "album": {"images": []}}}


class StorageTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        patcher = mock.patch.object(config, "DATA_DIR", Path(tmp.name))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_collect_adds_only_new_plays_and_keeps_90_days(self):
        social.set_share("ana", True)
        sp = FakeSpotify([item("spotify:track:1", NOW - 600), item("spotify:track:2", NOW - 300)])
        self.assertEqual(social.collect(sp, "ana", NOW), 2)
        self.assertEqual(social.collect(sp, "ana", NOW), 0)  # same answer again: nothing new
        self.assertEqual(sp.asked[1], int((NOW - 300) * 1000))  # asks only for what came after
        self.assertEqual(len(social.plays("ana")), 2)
        later = NOW + 100 * DAY
        social.collect(FakeSpotify([item("spotify:track:3", later - 60)]), "ana", later)
        self.assertEqual([p["uri"] for p in social.plays("ana")], ["spotify:track:3"])

    def test_taste_from_most_played_own_playlists_and_likes(self):
        sp = FakeSpotify()
        built = social.build_taste(sp, "ana", with_top=True, pause=lambda seconds: None, now=NOW)
        self.assertEqual(sp.read, ["mine"])  # only playlists she made
        self.assertEqual(set(built["sources"]), {"top", "playlists"})  # likes failed: left out, the rest kept
        self.assertEqual(set(built["sources"]["playlists"]), {"air", "beck"})  # episodes don't count
        self.assertEqual(built["names"]["bjork"], "Björk")
        self.assertFalse(social.taste_due("ana", with_top=True, now=NOW + 60))
        self.assertTrue(social.taste_due("ana", with_top=True, now=NOW + social.TASTE_EVERY_S + 1))
        without_top = social.build_taste(sp, "bia", with_top=False, pause=lambda seconds: None, now=NOW)
        self.assertNotIn("top", without_top["sources"])
        self.assertTrue(social.taste_due("bia", with_top=True, now=NOW + 60))  # authorized later: read again
        social.set_share("ana", False, forget=True)
        self.assertEqual(social.taste("ana"), {})  # leaving deletes it too

    def test_leaving_can_delete_the_history(self):
        social.set_share("ana", True)
        social.collect(FakeSpotify([item("spotify:track:1", NOW - 60)]), "ana", NOW)
        social.set_share("ana", False)
        self.assertFalse(social.sharing("ana"))
        self.assertEqual(len(social.plays("ana")), 1)  # kept (and hidden) unless asked
        social.set_share("ana", False, forget=True)
        self.assertEqual(social.plays("ana"), [])


class PlayTest(unittest.TestCase):
    def test_keeps_what_achievements_need(self):
        item = {"played_at": "2026-10-15T12:00:00Z", "context": {"type": "album", "uri": "spotify:album:al"},
                "track": {"uri": "spotify:track:t", "name": "So What", "duration_ms": 562000, "track_number": 1, "disc_number": 1,
                          "artists": [{"id": "md", "name": "Miles Davis"}],
                          "album": {"id": "al", "name": "Kind of Blue", "album_type": "album",
                                    "release_date": "1959-08-17", "total_tracks": 5, "images": []}}}
        played = social._play(item)
        self.assertEqual(played["album"], {"id": "al", "name": "Kind of Blue", "type": "album",
                                           "release": "1959-08-17", "tracks": 5})
        self.assertEqual((played["track_number"], played["disc_number"], played["context"]),
                         (1, 1, {"type": "album", "uri": "spotify:album:al"}))
        self.assertIsNone(social._play({**item, "context": None})["context"])


if __name__ == "__main__":
    unittest.main()
