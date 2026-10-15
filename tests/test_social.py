import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from spotify_assistant import config, social

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


class AffinityTest(unittest.TestCase):
    def test_same_taste_is_high_different_is_zero(self):
        mine = listened([("a", 8), ("b", 4)])
        self.assertEqual(social.affinity(mine, listened([("a", 8), ("b", 4)]), NOW)["percent"], 100)
        self.assertEqual(social.affinity(mine, listened([("x", 12)]), NOW)["percent"], 0)
        some = social.affinity(mine, listened([("a", 6), ("z", 6)]), NOW)
        self.assertTrue(0 < some["percent"] < 100)
        self.assertEqual(some["shared"], ["A"])

    def test_needs_some_history(self):
        self.assertIsNone(social.affinity(listened([("a", 3)]), listened([("a", 30)]), NOW))

    def test_only_the_last_month_counts(self):
        old = listened([("x", 20)], start=NOW - 60 * DAY)
        self.assertIsNone(social.affinity(old, listened([("x", 20)]), NOW))


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
    def __init__(self, items):
        self.items = items
        self.asked = []

    def recently_played(self, after=None):
        self.asked.append(after)
        return self.items


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

    def test_leaving_can_delete_the_history(self):
        social.set_share("ana", True)
        social.collect(FakeSpotify([item("spotify:track:1", NOW - 60)]), "ana", NOW)
        social.set_share("ana", False)
        self.assertFalse(social.sharing("ana"))
        self.assertEqual(len(social.plays("ana")), 1)  # kept (and hidden) unless asked
        social.set_share("ana", False, forget=True)
        self.assertEqual(social.plays("ana"), [])


if __name__ == "__main__":
    unittest.main()
