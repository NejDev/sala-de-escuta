import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from spotify_assistant import curation, i18n, medals

OWN = [medal for medal in medals.MEDALS if medal.family != "games"]
ROOT = Path(__file__).resolve().parent.parent
CATALOG = Path("docs/superpowers/specs/2026-10-15-achievements-catalog.md")
NAMES = Path("spotify_assistant/medal_names.py")


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

    def test_the_names_module_is_what_the_generator_makes_from_the_catalog(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / CATALOG).parent.mkdir(parents=True)
            shutil.copyfile(ROOT / CATALOG, root / CATALOG)
            (root / NAMES).parent.mkdir()
            subprocess.run([sys.executable, "-I", str(ROOT / "scripts" / "make_medal_names.py"), str(root)],
                           check=True, capture_output=True)
            made = (root / NAMES).read_text(encoding="utf-8")
        self.assertEqual(made, (ROOT / NAMES).read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
