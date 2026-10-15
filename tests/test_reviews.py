import tempfile
import unittest
from pathlib import Path
from unittest import mock

from spotify_assistant import config, reviews

KIND_OF_BLUE = "1weenld61qoidwYuZ1GESA"
ALBUM = {"id": KIND_OF_BLUE, "uri": f"spotify:album:{KIND_OF_BLUE}", "name": "Kind of Blue",
         "artists": ["Miles Davis"], "image": None, "year": "1959"}
NAMES = {"ana": "Ana", "bia": "Bia", "caio": "Caio"}
USERS = list(NAMES)


class LinkTest(unittest.TestCase):
    def test_album_from_links_uris_and_ids(self):
        for text in (f"https://open.spotify.com/album/{KIND_OF_BLUE}?si=abc", f"https://open.spotify.com/intl-pt/album/{KIND_OF_BLUE}",
                     f"spotify:album:{KIND_OF_BLUE}", f"  {KIND_OF_BLUE} "):
            self.assertEqual(reviews.album_id(text), KIND_OF_BLUE, text)
        for text in (f"https://open.spotify.com/track/{KIND_OF_BLUE}", "kind of blue", "", "../../etc"):
            self.assertIsNone(reviews.album_id(text), text)

    def test_ratings_are_half_stars(self):
        self.assertEqual([reviews.rating(value) for value in (0.5, 3, "4.5", None, 0, "")], [0.5, 3.0, 4.5, None, None, None])
        for value in (0.3, 5.5, -1, "lots"):
            with self.assertRaises(ValueError):
                reviews.rating(value)


class RoomTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        patcher = mock.patch.object(config, "DATA_DIR", Path(tmp.name))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_private_reviews_never_reach_anyone_else(self):
        reviews.save("ana", ALBUM, 4.5, "Só eu sei.", public=False, now=100)
        reviews.save("bia", ALBUM, 3, "Bom pra estudar.", public=True, now=200)
        self.assertEqual([r["author"] for r in reviews.room("caio", USERS, NAMES)], ["Bia"])
        seen_by_caio = reviews.of_album(KIND_OF_BLUE, "caio", USERS, NAMES)
        self.assertEqual(([r["author"] for r in seen_by_caio["room"]], seen_by_caio["mine"]), (["Bia"], None))
        self.assertEqual((seen_by_caio["average"], seen_by_caio["count"]), (3.0, 1))  # Ana's private 4.5 doesn't count
        seen_by_ana = reviews.of_album(KIND_OF_BLUE, "ana", USERS, NAMES)
        self.assertEqual(seen_by_ana["mine"]["text"], "Só eu sei.")
        self.assertTrue(seen_by_ana["mine"]["own"])

    def test_editing_keeps_the_first_date_and_deleting_removes_it(self):
        reviews.save("ana", ALBUM, 4, "", public=True, now=100)
        edited = reviews.save("ana", ALBUM, 5, "Melhorou.", public=True, now=300)
        self.assertEqual((edited["at"], edited["updated"], edited["rating"]), (100, 300, 5))
        self.assertEqual(reviews.known_album(KIND_OF_BLUE, USERS)["name"], "Kind of Blue")
        self.assertTrue(reviews.delete("ana", KIND_OF_BLUE))
        self.assertFalse(reviews.delete("ana", KIND_OF_BLUE))
        self.assertEqual(reviews.room("bia", USERS, NAMES), [])


if __name__ == "__main__":
    unittest.main()
