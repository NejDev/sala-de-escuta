import tempfile
import unittest
from pathlib import Path
from unittest import mock

from spotify_assistant import config, favorites

SPECS = [{"name": "Tech", "refresh": "weekly"}, {"name": "Jazz"}]


class FavoritesTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        patcher = mock.patch.object(config, "DATA_DIR", Path(tmp.name))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_curated_follow_playlists_json(self):
        items = favorites.sync_curated("dono", SPECS, now=100)
        self.assertEqual([(f["name"], f["every"]) for f in items], [("Tech", "weekly"), ("Jazz", "monthly")])
        favorites.change("dono", lambda items: items.insert(0, favorites.new("discovery", "Minha", "daily", now=100)))
        items = favorites.sync_curated("dono", SPECS[1:], now=200)  # Tech left playlists.json
        self.assertEqual([f["name"] for f in items], ["Jazz", "Minha"])
        self.assertEqual(items[0]["created"], 100)  # kept, not recreated
        self.assertIsNone(items[0]["updated"])  # becoming a favorite isn't an update

    def test_due_after_one_period(self):
        fav = favorites.new("discovery", "X", "weekly", now=1000)
        self.assertFalse(favorites.is_due(fav, 1000 + 6 * 86400))
        self.assertTrue(favorites.is_due(fav, 1000 + 7 * 86400))
        fav["every"] = "daily"
        self.assertTrue(favorites.is_due(fav, 1000 + 86400))

    def test_recent_finds_newest_first_without_repeats(self):
        song = lambda n: {"uri": f"spotify:track:{n}", "title": f"T{n}", "subtitle": "A", "image": None, "duration_ms": 1}
        favorites.remember("ana", [song(1), song(2)], "P", now=1)
        favorites.remember("ana", [song(1)], "Q", now=2)
        self.assertEqual([(f["uri"], f["playlist"]) for f in favorites.recent("ana")],
                         [("spotify:track:1", "Q"), ("spotify:track:2", "P")])
        with mock.patch.object(favorites, "RECENT_MAX", 1):
            favorites.remember("ana", [song(3)], "P", now=3)
        self.assertEqual([f["uri"] for f in favorites.recent("ana")], ["spotify:track:3"])


if __name__ == "__main__":
    unittest.main()
