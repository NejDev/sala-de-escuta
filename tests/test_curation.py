import unittest
from datetime import date

from spotify_assistant import curation
from spotify_assistant.config import parse_env


def track(name, *artists, album="Album", uri=None):
    return {
        "name": name,
        "artists": [{"name": artist} for artist in artists],
        "album": {"name": album},
        "uri": uri or f"spotify:track:{name}",
    }


def episode(name, released, precision="day", playable=True):
    return {
        "name": name,
        "release_date": released,
        "release_date_precision": precision,
        "is_playable": playable,
        "uri": f"spotify:episode:{name}",
    }


class TitleOverlapTest(unittest.TestCase):
    def test_spotify_classical_naming_matches(self):
        self.assertEqual(curation.title_overlap("Prelude in E Minor, Op. 28 No. 4", "24 Préludes, Op. 28: No. 4 in E Minor"), 1.0)
        self.assertEqual(curation.title_overlap("Für Elise", 'Bagatelle No. 25 in A Minor, WoO 59 "Für Elise"'), 1.0)

    def test_numbers_must_match_exactly(self):
        self.assertLess(curation.title_overlap("Gymnopédie No. 1", "Gymnopédie No. 18"), 1.0)


class ArtistMatchTest(unittest.TestCase):
    def test_matches_whole_words_inside_group_name(self):
        self.assertTrue(curation.artist_matches("Bill Evans", [{"name": "Bill Evans Trio"}]))

    def test_does_not_match_inside_other_words(self):
        self.assertFalse(curation.artist_matches("Aso", [{"name": "Picasso"}]))


class PickTrackTest(unittest.TestCase):
    def test_skips_karaoke_and_lofi_versions(self):
        candidates = [
            track("Clair de lune (Karaoke Version)", "Claude Debussy"),
            track("Clair de lune", "Claude Debussy", album="Lofi Classics"),
            track("Suite bergamasque, L. 75: III. Clair de lune", "Claude Debussy", "Alexis Weissenberg"),
        ]
        picked = curation.pick_track(candidates, "Claude Debussy", "Clair de lune")
        self.assertEqual(picked["name"], "Suite bergamasque, L. 75: III. Clair de lune")

    def test_requires_the_artist(self):
        candidates = [track("So What", "Some Cover Band")]
        self.assertIsNone(curation.pick_track(candidates, "Miles Davis", "So What"))

    def test_prefers_exact_title(self):
        candidates = [track("So What Else", "Miles Davis"), track("So What - Remastered", "Miles Davis")]
        self.assertEqual(curation.pick_track(candidates, "Miles Davis", "So What")["name"], "So What - Remastered")


class PickArtistTracksTest(unittest.TestCase):
    def test_dedupes_versions_and_limits(self):
        candidates = [
            track("Feather", "Nujabes"),
            track("Feather (Remastered)", "Nujabes"),
            track("Aruarian Dance", "Nujabes"),
            track("Other", "Someone Else"),
            track("Luv(sic.)", "Nujabes", "Shing02"),
        ]
        picked = curation.pick_artist_tracks(candidates, "Nujabes", 2)
        self.assertEqual([t["name"] for t in picked], ["Feather", "Aruarian Dance"])


class PickShowTest(unittest.TestCase):
    def test_word_order_does_not_matter_but_language_does(self):
        candidates = [
            {"name": "Canaltech Podcast", "languages": ["en"]},
            {"name": "Podcast Canaltech", "languages": ["pt"]},
        ]
        self.assertEqual(curation.pick_show(candidates, "Canaltech Podcast")["name"], "Podcast Canaltech")

    def test_all_words_required(self):
        self.assertIsNone(curation.pick_show([{"name": "Bom dia", "languages": ["pt"]}], "Bom dia Tech"))


class RecentEpisodesTest(unittest.TestCase):
    def test_keeps_newest_playable_within_window(self):
        episodes = [
            episode("old", "2026-09-01"),
            episode("new", "2026-10-13"),
            episode("blocked", "2026-10-12", playable=False),
            episode("mid", "2026-10-08"),
            episode("newer", "2026-10-14"),
            episode("month-only", "2026-10", precision="month"),
        ]
        picked = curation.recent_episodes(episodes, date(2026, 10, 14), max_age_days=10, max_per_show=2)
        self.assertEqual([e["name"] for e in picked], ["newer", "new"])


class HelpersTest(unittest.TestCase):
    def test_interleave(self):
        self.assertEqual(curation.interleave([[1, 2], [3], [4, 5, 6]]), [1, 3, 4, 2, 5, 6])

    def test_parse_track_spec_splits_on_first_separator(self):
        self.assertEqual(curation.parse_track_spec("Artist - Title - Live"), ("Artist", "Title - Live"))

    def test_parse_track_spec_rejects_bad_format(self):
        with self.assertRaises(SystemExit):
            curation.parse_track_spec("Just a title")

    def test_parse_env(self):
        text = "# comment\nSPOTIFY_CLIENT_ID=abc\nQUOTED=\"x y\"\n\nBROKEN LINE\n"
        self.assertEqual(parse_env(text), {"SPOTIFY_CLIENT_ID": "abc", "QUOTED": "x y"})


if __name__ == "__main__":
    unittest.main()
