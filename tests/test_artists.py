import tempfile
import unittest
from pathlib import Path
from unittest import mock

from spotify_assistant import artists, config, i18n, musicbrainz
from spotify_assistant.api import SpotifyError
from spotify_assistant.discovery import Hunt

# Shape of a real MusicBrainz lookup (inc=artist-rels+url-rels), trimmed.
BAND = {
    "id": "band",
    "name": "TWICE",
    "sort-name": "TWICE",
    "type": "Group",
    "relations": [
        {"type": "founder", "direction": "backward", "artist": {"id": "boss", "name": "박진영", "sort-name": "Park, Jin Young"}},
        {"type": "member of band", "direction": "backward", "ended": False,
         "artist": {"id": "m1", "name": "NAYEON", "sort-name": "NAYEON"}},
        {"type": "member of band", "direction": "backward", "ended": True,
         "artist": {"id": "m2", "name": "다현", "sort-name": "DAHYUN"}},
        {"type": "subgroup", "direction": "backward", "artist": {"id": "sub", "name": "MISAMO", "sort-name": "MISAMO"}},
        {"type": "member of band", "direction": "forward", "artist": {"id": "other", "name": "Bigger Band"}},
        {"type": "free streaming", "url": {"resource": "https://open.spotify.com/artist/BAND1"}},
    ],
}


class MusicBrainzTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        for name, value in {"DATA_DIR": Path(tmp.name), "MUSICBRAINZ_CACHE_FILE": Path(tmp.name) / "mb.json"}.items():
            patcher = mock.patch.object(config, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_members_subunits_and_spotify_profile(self):
        info = musicbrainz.parse_artist(BAND)
        self.assertEqual(info["spotify"], "BAND1")
        self.assertEqual([(m["name"], m["role"], m["former"]) for m in info["members"]],
                         [("NAYEON", "member", False), ("DAHYUN", "member", True), ("MISAMO", "subgroup", False)])

    def test_one_entry_per_person_even_with_one_relation_per_instrument(self):
        relation = lambda ended: {"type": "member of band", "direction": "backward", "ended": ended,
                                  "artist": {"id": "mike", "name": "Mike Shinoda", "sort-name": "Shinoda, Mike"}}
        info = musicbrainz.parse_artist({"id": "lp", "name": "Linkin Park", "relations": [relation(False), relation(False), relation(True)]})
        self.assertEqual([(m["name"], m["former"]) for m in info["members"]], [("Mike Shinoda", False)])

    def test_latin_names(self):
        self.assertEqual(musicbrainz.latin_name("もも", "MOMO"), "MOMO")
        self.assertEqual(musicbrainz.latin_name("박진영", "Park, Jin Young"), "Jin Young Park")
        self.assertEqual(musicbrainz.latin_name("Sepultura", "Sepultura"), "Sepultura")

    def test_search_needs_a_confident_exact_match(self):
        found = [{"id": "x", "name": "Twice a Man", "score": 100}, {"id": "y", "name": "TWICE", "score": 95}]
        self.assertEqual(musicbrainz.best_match("twice", found), "y")
        self.assertIsNone(musicbrainz.best_match("twice", [{"id": "y", "name": "TWICE", "score": 60}]))
        alias = [{"id": "z", "name": "방탄소년단", "score": 100, "aliases": [{"name": "BTS"}]}]
        self.assertEqual(musicbrainz.best_match("BTS", alias), "z")

    def test_answers_are_kept_on_disk(self):
        calls = []
        fetch = lambda url: calls.append(url) or BAND
        self.assertEqual(musicbrainz.MusicBrainz(fetch).artist("band")["name"], "TWICE")
        self.assertEqual(musicbrainz.MusicBrainz(fetch).artist("band")["name"], "TWICE")  # a new client reads the file
        self.assertEqual(len(calls), 1)


def album(album_id, name, date, kind="album", artist="TWICE", images=()):
    return {"id": album_id, "uri": f"spotify:album:{album_id}", "name": name, "release_date": date,
            "album_type": kind, "artists": [{"name": artist}], "images": list(images), "total_tracks": 5}


class FakeSpotify:
    def __init__(self, albums, search=None):
        self.albums = albums
        self.pages = []
        self.paused_at = set()
        self.found = search or {}
        self.searched = []

    def artist(self, artist_id):
        return {"name": {"BAND1": "TWICE"}.get(artist_id, artist_id), "images": [{"url": "pic", "width": 300}]}

    def artist_albums_page(self, artist_id, groups, offset=0):
        self.pages.append((artist_id, groups, offset))
        if (artist_id, groups, offset) in self.paused_at:
            raise SpotifyError(429, "paused", retry_after=60, family="artists")
        items = self.albums.get((artist_id, groups), [])
        return items[offset:offset + 10], offset + 10 < len(items)

    def search(self, query, kind):
        self.searched.append(query)
        return self.found.get(query, [])


class FakeMusicBrainz:
    def __init__(self, fail=False):
        self.fail = fail

    def by_spotify(self, spotify_id):
        if self.fail:
            raise musicbrainz.MusicBrainzError("down")
        return "band" if spotify_id == "BAND1" else None

    def find(self, name):
        if self.fail:
            raise musicbrainz.MusicBrainzError("down")
        return "band" if name.lower() == "twice" else None

    def artist(self, mbid):
        if mbid == "band":
            info = musicbrainz.parse_artist(BAND)
            info["members"].append({"mbid": "m3", "name": "MINA", "role": "member", "former": False})
            return info
        return {"m1": {"spotify": "NAYEON1"}, "m2": {"spotify": None}, "sub": {"spotify": "MISAMO1"},
                "m3": {"spotify": None}}[mbid]


class DiscographyTest(unittest.TestCase):
    def setUp(self):
        i18n.use("pt")
        self.addCleanup(i18n.use, i18n.DEFAULT)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        patcher = mock.patch.object(config, "DATA_DIR", Path(tmp.name))
        patcher.start()
        self.addCleanup(patcher.stop)
        artists._cache = None

    def spotify(self):
        return FakeSpotify({
            ("BAND1", "album"): [
                album("a1", "Strategy", "2024-12-06"),
                album("a2", "Strategy (Japanese ver.)", "2024-12-06"),  # same release, another edition
                album("a4", "Hallelujah Hymns", "2022-05-01"),  # religious: never shown
            ],
            ("BAND1", "compilation"): [album("a3", "Hits", "2023-01-01", kind="compilation")],
            ("BAND1", "appears_on"): [album("f1", "Soundtrack", "2021-03-03", artist="Various Artists", kind="compilation")],
            ("NAYEON1", "single"): [album("n1", "NA", "2024-06-14", kind="single", artist="NAYEON")],
            ("NAYEON1", "appears_on"): [album("n2", "Someone's Song", "2023-09-01", kind="single", artist="Someone")],
            ("DAHYUN1", "single"): [album("d1", "Dahyun Solo", "2025-01-01", kind="single", artist="DAHYUN")],
        }, search={
            "twice": [{"id": "BAND1", "name": "TWICE"}, {"id": "x", "name": "Twice a Man"}],
            "DAHYUN": [{"id": "DAHYUN1", "name": "DAHYUN"}],
            "MINA": [{"id": "it", "name": "Mina"}, {"id": "kr", "name": "MINA"}],  # ambiguous: left out
        })

    def test_reads_every_page_once_and_remembers_across_restarts(self):
        sp = self.spotify()
        sp.albums[("BAND1", "appears_on")] = [album(f"f{i}", f"Feat {i}", f"20{20 - i:02d}-01-01", kind="single",
                                                    artist="Someone") for i in range(25)]
        hunt = Hunt("artist", "twice")
        artists.discography(hunt, sp, FakeMusicBrainz(), "twice")
        self.assertEqual([offset for who, group, offset in sp.pages if (who, group) == ("BAND1", "appears_on")], [0, 10, 20])
        self.assertEqual(len([r for r in hunt.releases if r["type"] == "feature"]), 26)  # all 25, plus NAYEON's
        artists._cache = None  # the panel restarted: what was read comes from disk
        again = self.spotify()
        artists.discography(Hunt("artist", "twice"), again, FakeMusicBrainz(), "twice")
        self.assertEqual(again.pages, [])

    def test_a_pause_halfway_resumes_where_it_stopped(self):
        sp = self.spotify()
        sp.albums[("BAND1", "appears_on")] = [album(f"f{i}", f"Feat {i}", "2020-01-01", kind="single",
                                                    artist="Someone") for i in range(25)]
        sp.paused_at = {("BAND1", "appears_on", 10)}
        read = []
        with self.assertRaises(SpotifyError):
            for batch in artists.releases(sp, "BAND1", "appears_on"):
                read += batch
        self.assertEqual(len(read), 10)  # the first page is kept
        sp.paused_at, sp.pages = set(), []
        everything = [a for batch in artists.releases(sp, "BAND1", "appears_on") for a in batch]
        self.assertEqual(sp.pages, [("BAND1", "appears_on", 10), ("BAND1", "appears_on", 20)])
        self.assertEqual(len(everything), 25)

    def test_a_day_later_only_whats_new_is_read(self):
        sp = self.spotify()
        sp.albums[("BAND1", "single")] = [album(f"s{i}", f"Single {i}", "2020-01-01", kind="single") for i in range(25)]
        list(artists.releases(sp, "BAND1", "single"))
        sp.pages = []
        sp.albums[("BAND1", "single")].insert(0, album("new", "Brand New", "2026-10-10", kind="single"))
        with mock.patch.object(artists.time, "time", return_value=artists.time.time() + artists.RECHECK_S + 1):
            everything = [a for batch in artists.releases(sp, "BAND1", "single") for a in batch]
        self.assertEqual(sp.pages, [("BAND1", "single", 0)])  # one page: it already reached known ones
        self.assertEqual([a["id"] for a in everything][-1], "new")
        self.assertEqual(len(everything), 26)

    def test_band_members_solos_and_features_in_one_list(self):
        hunt = Hunt("artist", "twice")
        artists.discography(hunt, self.spotify(), FakeMusicBrainz(), "twice")
        self.assertEqual(hunt.label, "TWICE")
        self.assertEqual([p["name"] for p in hunt.artist["people"]], ["TWICE", "NAYEON", "DAHYUN", "MISAMO"])
        self.assertTrue(hunt.artist["people"][2]["former"])
        rows = [(r["name"], r["type"], [w["name"] for w in r["who"]]) for r in hunt.releases]
        self.assertEqual(rows, [
            ("Dahyun Solo", "single", ["DAHYUN"]),
            ("Strategy", "album", ["TWICE"]),
            ("NA", "single", ["NAYEON"]),
            ("Someone's Song", "feature", ["NAYEON"]),
            ("Hits", "compilation", ["TWICE"]),
            ("Soundtrack", "compilation", ["TWICE"]),
        ])
        self.assertEqual((hunt.progress, hunt.total), (4, 4))
        self.assertEqual(hunt.message, "6 lançamentos de TWICE e de quem faz parte.")

    def test_without_musicbrainz_it_still_finds_the_artist(self):
        sp = self.spotify()
        hunt = Hunt("artist", "twice")
        artists.discography(hunt, sp, FakeMusicBrainz(fail=True), "twice")
        self.assertEqual([p["name"] for p in hunt.artist["people"]], ["TWICE"])
        self.assertEqual(hunt.message, "3 lançamentos de TWICE.")  # the band's own, its compilation and a soundtrack

    def test_a_member_that_cannot_be_looked_up_is_skipped(self):
        sp = self.spotify()

        def paused(query, kind):
            raise SpotifyError(429, "paused", retry_after=60, family="search")

        sp.search = paused  # Spotify search paused: DAHYUN (no MusicBrainz link) can't be found
        hunt = Hunt("artist", "twice")
        artists.discography(hunt, sp, FakeMusicBrainz(), "twice")
        self.assertEqual([p["name"] for p in hunt.artist["people"]], ["TWICE", "NAYEON", "MISAMO"])
        self.assertEqual(hunt.status, "running")  # the discovery itself didn't fail

    def test_a_shared_name_asks_which_one(self):
        sp = self.spotify()
        sp.found["andy"] = [{"id": "A1", "name": "Andy", "genres": ["indie"], "images": []},
                            {"id": "A2", "name": "ANDY", "images": [{"url": "face", "width": 160}]},
                            {"id": "A3", "name": "Andy Bell"}]
        sp.albums[("A1", artists.LATEST_GROUPS)] = [album("o", "Old", "2019-01-01"), album("n", "New", "2025-05-05")]
        hunt = Hunt("artist", "andy")
        artists.discography(hunt, sp, FakeMusicBrainz(), "andy")
        self.assertEqual([(c["id"], c["image"], c["genres"]) for c in hunt.candidates],
                         [("A1", None, ["indie"]), ("A2", "face", [])])  # only the exact names
        self.assertEqual(hunt.candidates[0]["latest"], {"name": "New", "year": "2025"})
        self.assertEqual(hunt.message, "Tem mais de um artista chamado “andy”. Qual é o seu?")
        self.assertEqual(hunt.releases, [])
        # Picking one goes straight to that profile, without asking again.
        sp.albums[("A2", "album")] = [album("s", "Solo", "2024-01-01", artist="ANDY")]
        chosen = Hunt("artist", "andy")
        artists.discography(chosen, sp, FakeMusicBrainz(), "andy", spotify_id="A2")
        self.assertEqual([r["name"] for r in chosen.releases], ["Solo"])

    def test_with_search_paused_it_goes_by_name(self):
        sp = self.spotify()
        searches = []

        def search(query, kind):
            searches.append(query)
            if query == "twice":
                raise SpotifyError(429, "paused", retry_after=60, family="search")
            return sp.found.get(query, [])

        sp.search = search
        hunt = Hunt("artist", "twice")
        artists.discography(hunt, sp, FakeMusicBrainz(), "twice")
        self.assertEqual(hunt.label, "TWICE")
        self.assertIn("NAYEON", [p["name"] for p in hunt.artist["people"]])

    def test_unknown_artist(self):
        hunt = Hunt("artist", "zzz")
        artists.discography(hunt, self.spotify(), FakeMusicBrainz(), "zzz")
        self.assertEqual((hunt.releases, hunt.message), ([], "Não achei “zzz”. Confira o nome do artista ou da banda."))


if __name__ == "__main__":
    unittest.main()
