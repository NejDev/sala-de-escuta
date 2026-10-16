import random
import re
import threading
import time
from datetime import date, timedelta
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from spotify_assistant import config, discovery, i18n, lastfm
from spotify_assistant.api import SpotifyError
from spotify_assistant.tempo import Analysis

_tmp = tempfile.TemporaryDirectory()


def setUpModule():
    # The memory of matched tracks is global: point it at a temporary file and reset it for each test.
    patcher = mock.patch.object(config, "MATCH_CACHE_FILE", Path(_tmp.name) / "matches.json")
    patcher.start()
    unittest.addModuleCleanup(patcher.stop)
    unittest.addModuleCleanup(_tmp.cleanup)


class FreshMatches(unittest.TestCase):
    def setUp(self):
        discovery.matches = discovery.MatchCache()
        i18n.use("pt")  # messages are checked in Portuguese; EnglishMessagesTest covers English
        self.addCleanup(i18n.use, i18n.DEFAULT)


def dz_track(track_id, bpm, energy=0.8, title=None, artist="Artista", rank=1000, preview=True):
    return {
        "id": track_id,
        "title": title or f"Faixa {track_id}",
        "artist": {"name": artist},
        "isrc": f"ISRC{track_id}",
        "rank": rank,
        "readable": True,
        # The fake meter reads BPM and energy straight from the "preview".
        "preview": f"{bpm}:{energy}" if preview else "",
    }


def fake_measure(data: bytes) -> Analysis:
    bpm, energy = data.decode().split(":")
    return Analysis(float(bpm), 0.9, float(energy))


class FakeDeezer:
    def __init__(self, playlists=None, tracks=None, artists=None, related=None, tops=None,
                 fans=None, albums=None, album_songs=None, songs=None):
        self.songs = songs or {}  # track searches: query -> results
        self.playlists = playlists or {}
        self.tracks = tracks or {}
        self.artists = artists or {}
        self._related = related or {}
        self.tops = tops or {}
        self.fans = fans or {}
        self.albums = albums or {}
        self.album_songs = album_songs or {}

    def artist(self, artist_id):
        return {"id": artist_id, "nb_fan": self.fans.get(artist_id, 0)}

    def artist_albums(self, artist_id, limit=25):
        return self.albums.get(artist_id, [])

    def album_tracks(self, album_id):
        return self.album_songs.get(album_id, [])

    def search_playlists(self, query, limit=8):
        return self.playlists.get(query, [])

    def search_tracks(self, query, limit=50):
        return self.songs.get(query, [])

    def playlist_tracks(self, playlist_id, limit=100):
        return self.tracks[playlist_id]

    def preview(self, url):
        return url.encode()

    def search_artist(self, name):
        return self.artists.get(name)

    def related(self, artist_id, limit=20):
        return self._related.get(artist_id, [])

    def top_tracks(self, artist_id, limit=5):
        return self.tops.get(artist_id, [])

    def track(self, track_id):
        return dz_track(track_id, 100)


class FakeSpotify:
    """Every Deezer track exists on Spotify under the same number."""

    def __init__(self, missing=()):
        self.missing = set(missing)

    def search(self, query, kind, offset=0):
        if query.startswith("isrc:ISRC"):
            track_id = query.removeprefix("isrc:ISRC")
            if track_id in self.missing:
                return []
            return [{"uri": f"spotify:track:{track_id}", "name": f"Faixa {track_id}",
                     "artists": [{"name": "Artista"}], "album": {"images": []}, "duration_ms": 1000}]
        return []


class MemoryCache:
    def __init__(self):
        self.data = {}

    def get(self, key):
        return (key in self.data), self.data.get(key)

    def put(self, key, analysis):
        self.data[key] = analysis


SPEC = {"name": "Treino pesado", "bpm": [125, 150], "energy": [0.65, 1.0], "sources": ["treino", "gym"]}


class RulesTest(unittest.TestCase):
    def test_fit_bpm_accepts_half_and_double_tempo(self):
        self.assertEqual(discovery.fit_bpm(128, 125, 150), 128)
        self.assertEqual(discovery.fit_bpm(70, 125, 150), 140)
        self.assertEqual(discovery.fit_bpm(260, 125, 150), 130)
        self.assertIsNone(discovery.fit_bpm(100, 125, 150))

    def test_fits_requires_energy_in_range(self):
        self.assertEqual(discovery.fits(Analysis(130, 0.5, 0.9), SPEC), 130)
        self.assertIsNone(discovery.fits(Analysis(130, 0.5, 0.3), SPEC))
        self.assertIsNone(discovery.fits(None, SPEC))

    def test_junk_filter(self):
        self.assertTrue(discovery.is_junk(dz_track(1, 60, title="Deep Sleep Binaural Beats")))
        self.assertTrue(discovery.is_junk(dz_track(2, 60, title="Cura 432 Hz")))
        self.assertTrue(discovery.is_junk(dz_track(4, 170, title="California Gurls - Workout Remix 170 Bpm")))
        self.assertFalse(discovery.is_junk(dz_track(3, 60, title="Hertz e Amor")))

    def test_next_hop_goes_to_lesser_known(self):
        options = [{"id": i, "nb_fan": fans} for i, fans in enumerate([50, 900, 5000, 80000, 120000, 3000000])]
        picks = {discovery.next_hop(options, {2}, random.Random(seed))["id"] for seed in range(30)}
        # 50 fans is left out (minimum) and 5000 was already visited: the bottom third of the rest remains.
        self.assertEqual(picks, {1})
        self.assertIsNone(discovery.next_hop([{"id": 9, "nb_fan": 10}], set(), random.Random()))

    def test_lesser_known_is_bottom_half_by_rank(self):
        tracks = [{"rank": rank} for rank in (900, 100, 500, 300)]
        self.assertEqual([t["rank"] for t in discovery.lesser_known(tracks)], [100, 300])


class ReligiousFilterTest(unittest.TestCase):
    def test_words_from_any_denomination(self):
        for text in ("Louvor e Adoração", "Gospel Hits", "Hare Krishna Mantra", "Ponto de Umbanda",
                     "Ave Maria", "Nasheed", "Jesus Cristo", "Hinos da Harpa Cristã", "Gregorian Chant"):
            self.assertTrue(discovery.is_religious(text), text)

    def test_secular_lookalikes_pass(self):
        for text in ("Chantaje", "Godsmack", "Reza Sadeghi", "Santana", "Paradise City"):
            self.assertFalse(discovery.is_religious(text), text)

    def test_track_checks_title_artist_and_album(self):
        self.assertTrue(discovery.religious_track({"title": "Vitória", "artist": {"name": "Ministério Zoe"}}))
        self.assertTrue(discovery.religious_track({"name": "X", "artists": [{"name": "Y"}], "album": {"name": "Hinos Avulsos"}}))

    def test_playlist_full_of_hints_is_dropped(self):
        # No title says "gospel", but several tracks talk about the Lord, glory, miracles...
        tracks = [dz_track(i, 80, title=title) for i, title in enumerate(
            ["Senhor do Céu", "Glória", "Milagres", "Ressuscita-me", "Sonhos", "Estrada", "Mar"])]
        self.assertTrue(discovery.religious_collection("Esperança", tracks))
        self.assertFalse(discovery.religious_collection("Esperança", [dz_track(1, 80, title="Mar")] * 7))

    def test_devotional_genres_are_not_in_the_roulette(self):
        self.assertFalse({"qawwali", "gnawa", "carnatic"} & set(discovery.WORLD_GENRES))

    def test_little_known_genres_stay_away_from_the_suggestions(self):
        app = (Path(discovery.__file__).parent / "static" / "app.js").read_text(encoding="utf-8")
        listed = re.search(r"const GENRE_SUGGESTIONS = \[(.*?)\];", app, re.S).group(1)
        listed += re.search(r"const SUBGENRES = \{(.*?)\};", app, re.S).group(1)  # shown as chips too
        suggested = {name.lower() for name in re.findall(r'"([^"]+)"', listed)}
        self.assertEqual(suggested & set(discovery.WORLD_GENRES), set())


class BlockedArtistsTest(FreshMatches):
    def test_blocked_track_matches_any_credited_artist(self):
        blocked = discovery.blocked_set(["Stryper", "  "])
        self.assertEqual(blocked, {"stryper"})
        self.assertTrue(discovery.blocked_track({"artist": {"name": "STRYPER"}}, blocked))
        self.assertTrue(discovery.blocked_track({"artists": [{"name": "Outro"}, {"name": "Stryper"}]}, blocked))
        self.assertFalse(discovery.blocked_track({"artist": {"name": "Strypes"}}, blocked))
        self.assertFalse(discovery.blocked_track({"artist": {"name": "Stryper"}}, set()))

    def test_sense_skips_blocked_artists(self):
        deezer = FakeDeezer(
            playlists={"treino": [{"id": "p", "nb_tracks": 20}]},
            tracks={"p": [dz_track(1, 130, artist="Stryper"), dz_track(2, 132), dz_track(3, 140)]},
        )
        spec = {"name": "Treino", "bpm": [125, 150], "energy": [0.6, 1.0], "sources": ["treino"]}
        hunt = discovery.Hunt("sense", "Treino")
        discovery.sense(hunt, spec, FakeSpotify(), deezer, random.Random(1), MemoryCache(), fake_measure,
                        blocked={"stryper"})
        self.assertEqual(sorted(f.uri for f in hunt.finds), ["spotify:track:2", "spotify:track:3"])

    def test_rabbit_hole_never_walks_into_a_blocked_artist(self):
        options = [{"id": 1, "name": "Stryper", "nb_fan": 900}, {"id": 2, "name": "Petra", "nb_fan": 950}]
        picks = {discovery.next_hop(options, set(), random.Random(s), {"stryper"})["id"] for s in range(20)}
        self.assertEqual(picks, {2})


class FeelingTextTest(unittest.TestCase):
    def test_dictionary_recognizes_word_forms(self):
        for text in ("ÓDIO", "tô com muita raiva", "odeio segunda", "furioso"):
            spec = discovery.spec_from_text(text)
            self.assertEqual(spec["bpm"], [125, 185], text)
            self.assertEqual(spec["sources"][0], text)  # the phrase is the first search
        self.assertEqual(discovery.spec_from_text("coração partido")["color"], "#9C7AA8")
        self.assertEqual(discovery.spec_from_text("chorando no banho")["bpm"], [55, 100])

    def test_short_stems_need_the_whole_word(self):
        self.assertEqual(discovery.spec_from_text("paz")["bpm"], [50, 88])
        self.assertIsNone(discovery.spec_from_text("pazuzu")["bpm"])

    def test_unknown_text_learns_the_rhythm(self):
        spec = discovery.spec_from_text("domingo de manhã")
        self.assertIsNone(spec["bpm"])
        self.assertEqual(spec["name"], "Domingo de manhã")
        self.assertEqual(spec["sources"][0], "domingo de manhã")

    def test_consensus_finds_the_shared_pulse(self):
        analyses = [Analysis(bpm, 0.5, energy) for bpm, energy in
                    [(92, 0.6), (184, 0.62), (90, 0.58), (95, 0.65), (46, 0.6), (150, 0.2), (91, 0.61)]]
        center = discovery.consensus(analyses)
        self.assertAlmostEqual(center[0], 92, delta=2)  # 184 and 46 halve/double to ~92
        self.assertIsNotNone(discovery.consensus_distance(Analysis(186, 0.5, 0.6), center))
        self.assertIsNone(discovery.consensus_distance(Analysis(150, 0.5, 0.2), center))
        self.assertIsNone(discovery.consensus(analyses[:3]))  # too few previews


class SenseTest(FreshMatches):
    def deezer(self):
        return FakeDeezer(
            playlists={
                "treino": [{"id": "p1", "nb_tracks": 50}],
                "gym": [{"id": "p2", "nb_tracks": 50}, {"id": "tiny", "nb_tracks": 3}],
            },
            tracks={
                "p1": [dz_track(1, 128), dz_track(2, 90), dz_track(3, 70), dz_track(4, 140, energy=0.3),
                       dz_track(5, 130, title="Binaural gym"), dz_track(6, 132, preview=False)],
                "p2": [dz_track(1, 128), dz_track(7, 145), dz_track(8, 135)],
            },
        )

    def test_gather_candidates_filters_and_dedupes(self):
        ids = sorted(t["id"] for t in discovery.gather_candidates(self.deezer(), SPEC["sources"], random.Random(1)))
        self.assertEqual(ids, [1, 2, 3, 4, 7, 8])

    def test_keeps_only_tracks_in_rhythm(self):
        hunt = discovery.Hunt("sense", "Treino pesado")
        discovery.sense(hunt, SPEC, FakeSpotify(missing={"8"}), self.deezer(), random.Random(2), MemoryCache(), fake_measure)
        found = {find.uri: find.bpm for find in hunt.finds}
        # 2 (90) is out; 3 (70) becomes 140; 4 lacks energy; 8 isn't on Spotify.
        self.assertEqual(found, {"spotify:track:1": 128, "spotify:track:3": 140, "spotify:track:7": 145})
        self.assertEqual(hunt.progress, 6)
        self.assertIn("3 músicas", hunt.message)

    def test_unknown_feeling_keeps_tracks_near_the_shared_rhythm(self):
        deezer = FakeDeezer(
            playlists={"domingo": [{"id": "d", "nb_tracks": 20}]},
            tracks={"d": [dz_track(i, bpm, energy) for i, (bpm, energy) in enumerate(
                [(96, 0.5), (98, 0.52), (192, 0.5), (95, 0.48), (100, 0.55), (97, 0.5), (160, 0.95), (60, 0.1)], start=1)]},
        )
        spec = {"name": "Domingo", "bpm": None, "energy": None, "sources": ["domingo"]}
        hunt = discovery.Hunt("sense", "Domingo")
        discovery.sense(hunt, spec, FakeSpotify(), deezer, random.Random(4), MemoryCache(), fake_measure)
        kept = {find.uri.rsplit(":", 1)[1] for find in hunt.finds}
        self.assertEqual(kept, {"1", "2", "3", "4", "5", "6"})  # 160/0.95 and 60/0.1 break the pattern
        self.assertIn("perto de", hunt.message)

    def test_cached_measurements_skip_download(self):
        cache = MemoryCache()
        cache.put("1", Analysis(130, 1, 0.9))
        deezer = self.deezer()
        deezer.preview = mock.Mock(side_effect=lambda url: url.encode())
        hunt = discovery.Hunt("sense", "Treino pesado")
        discovery.sense(hunt, SPEC, FakeSpotify(), deezer, random.Random(3), cache, fake_measure)
        downloaded = {call.args[0] for call in deezer.preview.call_args_list}
        self.assertNotIn("128:0.8", downloaded)  # track 1's preview, already measured
        self.assertEqual(deezer.preview.call_count, 5)  # 6 candidates, 1 already measured


class RabbitTest(FreshMatches):
    def test_walks_away_and_keeps_the_path(self):
        deezer = FakeDeezer(
            artists={"Chet Baker": {"id": 1, "name": "Chet Baker", "nb_fan": 500000}},
            related={
                1: [{"id": 2, "name": "Sonny Clark", "nb_fan": 3800}],
                2: [{"id": 3, "name": "Tina Brooks", "nb_fan": 644}],
            },
            tops={
                2: [{"id": 21, "title": "Cool Struttin'"}, {"id": 22, "title": "Blue Minor"}],
                3: [
                    {"id": 31, "title": "Eu e a Brisa"},
                    {"id": 30, "title": "Eu e a Brisa (Ao Vivo)"},  # same song: skipped
                    {"id": 32, "title": "Rapaz de Bem"},
                    {"id": 33, "title": "Céu e Mar"},
                ],
            },
        )
        hunt = discovery.Hunt("rabbit", "Toca do coelho")
        discovery.rabbit_hole(hunt, FakeSpotify(), deezer, random.Random(), ["Chet Baker"], walks=1)
        chain = hunt.chains[0]
        self.assertEqual([a["name"] for a in chain["path"]], ["Chet Baker", "Sonny Clark", "Tina Brooks"])
        # One from midway (Sonny Clark) and two from the end (Tina Brooks); the starting artist is left out.
        self.assertEqual([f.uri for f in chain["finds"]], ["spotify:track:21", "spotify:track:31", "spotify:track:32"])
        self.assertIn("Pulo 1 de 2", chain["finds"][0].reason)
        self.assertIn("Fim da toca", chain["finds"][-1].reason)

    def test_unknown_seed_reports_nothing_found(self):
        hunt = discovery.Hunt("rabbit", "Toca do coelho")
        discovery.rabbit_hole(hunt, FakeSpotify(), FakeDeezer(), random.Random(), ["Ninguém"], walks=2)
        self.assertEqual(hunt.finds, [])
        self.assertIn("não levou", hunt.message)


class SpotifyLimitsTest(FreshMatches):
    def test_found_tracks_are_searched_only_once(self):
        sp = FakeSpotify()
        sp.search = mock.Mock(wraps=sp.search)
        track = dz_track(9, 120)
        first = discovery.to_spotify(sp, track)
        second = discovery.to_spotify(sp, track)
        self.assertEqual(first, second)
        self.assertEqual(first["uri"], "spotify:track:9")
        self.assertEqual(sp.search.call_count, 1)

    def test_roulette_stops_when_spotify_pauses(self):
        sp = FakeSpotify()
        sp.search = mock.Mock(side_effect=SpotifyError(429, "pausado", retry_after=3600, family="search"))
        hunt = discovery.Hunt("roulette", "Roleta")
        with self.assertRaises(SpotifyError):
            discovery.roulette(hunt, sp, FakeDeezer(), random.Random(1))
        self.assertEqual(sp.search.call_count, 1)  # doesn't keep retrying


def song(track_id, title, artist_id, artist_name):
    return {"id": track_id, "title": title, "isrc": f"ISRC{track_id}", "readable": True,
            "artist": {"id": artist_id, "name": artist_name}}


class FiltersTest(FreshMatches):
    def setUp(self):
        super().setUp()
        discovery.fan_counts = discovery.FanCounts()

    def test_fan_range(self):
        self.assertTrue(discovery.ANY_SIZE.ok(None))
        self.assertFalse(discovery.FanRange(1000).ok(999))
        self.assertTrue(discovery.FanRange(1000, 5000).ok(5000))
        self.assertFalse(discovery.FanRange(1000, 5000).ok(5001))

    def test_rabbit_hole_stays_inside_the_size(self):
        options = [{"id": i, "name": f"A{i}", "nb_fan": fans} for i, fans in enumerate([150, 2000, 40000, 900000])]
        size = discovery.FanRange(1000, 50000)
        picks = {discovery.next_hop(options, set(), random.Random(s), size=size)["id"] for s in range(30)}
        self.assertEqual(picks, {1})  # 2000 is the least-known third within 1k..50k
        self.assertIsNone(discovery.next_hop(options, set(), random.Random(), size=discovery.FanRange(10_000_000)))

    def test_roulette_genre_pick_respects_size(self):
        deezer = FakeDeezer(
            playlists={"k-pop": [{"id": "p", "nb_tracks": 30, "title": "K-pop"}]},
            tracks={"p": [dz_track(1, 120, artist="Grande"), dz_track(2, 120, artist="Pequena")]},
            fans={},
        )
        deezer.tracks["p"][0]["artist"]["id"] = 10
        deezer.tracks["p"][1]["artist"]["id"] = 20
        deezer.fans = {10: 5_000_000, 20: 3_000}
        find = discovery.world_genre_pick(FakeSpotify(), deezer, random.Random(1), genre="k-pop",
                                          size=discovery.FanRange(1000, 100_000))
        self.assertEqual((find.uri, find.fans, find.tag), ("spotify:track:2", 3_000, "K-pop"))

    def every_genre_deezer(self):
        """A playlist for each little-known genre, each with its own track and a 300-fan artist."""
        genres = discovery.WORLD_GENRES
        return FakeDeezer(
            playlists={genre: [{"id": genre, "nb_tracks": 30, "title": genre}] for genre in genres},
            tracks={genre: [{**song(number, genre, number, f"Artista {number}"), "preview": "120:0.8"}]
                    for number, genre in enumerate(genres)},
            fans={number: 300 for number in range(len(genres))},
        )

    def spin(self, **options):
        sp = FakeSpotify()
        sp.search = mock.Mock(wraps=sp.search)
        hunt = discovery.Hunt("roulette", "Roleta")
        discovery.roulette(hunt, sp, self.every_genre_deezer(), random.Random(3), count=4, **options)
        searched = [call.args[0] for call in sp.search.call_args_list]
        return hunt, searched

    def test_little_known_roulette_mixes_genres_from_playlists_only(self):
        hunt, searched = self.spin(rare=True)
        self.assertEqual(len(hunt.finds), 4)
        self.assertEqual(len({find.tag for find in hunt.finds}), 4)  # one genre per card
        self.assertTrue(all(query.startswith("isrc:") for query in searched))  # no barely-played albums

    def test_tight_cap_skips_barely_played_albums(self):
        # Each album attempt costs a Spotify search and rarely fits a small cap: a spin would become a burst.
        _, searched = self.spin(size=discovery.FanRange(0, 500))
        self.assertTrue(all(query.startswith("isrc:") for query in searched))
        _, searched = self.spin(size=discovery.FanRange(0, 10_000))
        self.assertTrue(any(query.startswith("tag:hipster") for query in searched))

    def test_tight_listener_cap_skips_barely_played_albums(self):
        _, searched = self.spin(listeners=discovery.ListenerCap(500, FakeLastFm()))
        self.assertTrue(all(query.startswith("isrc:") for query in searched))


class NewsTest(FreshMatches):
    def setUp(self):
        super().setUp()
        discovery.fan_counts = discovery.FanCounts()

    def deezer(self):
        today = date.today()
        recent = (today - timedelta(days=3)).isoformat()
        self.newest = today - timedelta(days=1)
        newest = self.newest.isoformat()
        old = (today - timedelta(days=200)).isoformat()
        lineup = [song(1, "x", 10, "Banda Média"), song(2, "x", 20, "Gigante"), song(3, "x", 30, "Pequena")]
        return FakeDeezer(
            playlists={"k-pop": [{"id": "p", "nb_tracks": 30, "title": "K-pop"}]},
            tracks={"p": lineup},
            fans={10: 50_000, 20: 9_000_000, 30: 40},
            albums={
                10: [
                    {"id": 100, "title": "Novo Single", "release_date": newest, "record_type": "single"},
                    {"id": 101, "title": "Novo Single (Clean)", "release_date": newest, "record_type": "single"},
                    {"id": 102, "title": "Trilha", "release_date": recent, "record_type": "album"},
                    {"id": 103, "title": "Antigo", "release_date": old, "record_type": "album"},
                ],
                20: [{"id": 200, "title": "Hit", "release_date": newest, "record_type": "single"}],
                30: [{"id": 300, "title": "Demo", "release_date": newest, "record_type": "single"}],
            },
            album_songs={
                100: [song(1001, "Novo Single", 10, "Banda Média")],
                101: [song(1011, "Novo Single (Clean)", 10, "Banda Média")],
                # A soundtrack with several artists: the pick has to be the band's own song.
                102: [song(1021, "Tema de Outro", 99, "Outro"), song(1022, "Nossa Faixa", 10, "Banda Média")],
                103: [song(1031, "Velha", 10, "Banda Média")],
                200: [song(2001, "Hit", 20, "Gigante")],
                300: [song(3001, "Demo", 30, "Pequena")],
            },
        )

    def test_recent_releases_in_size_newest_first(self):
        hunt = discovery.Hunt("news", "Novidades: K-pop")
        discovery.news(hunt, FakeSpotify(), self.deezer(), "k-pop", discovery.FanRange(1000, 1_000_000), days=30)
        self.assertEqual([f.uri for f in hunt.finds], ["spotify:track:1001", "spotify:track:1022"])
        self.assertEqual(hunt.finds[0].fans, 50_000)
        self.assertEqual(hunt.finds[0].reason, f"Single de Banda Média (50.000 fãs), saiu em {self.newest:%d/%m/%Y}.")
        self.assertIn("2 lançamentos", hunt.message)

    def test_without_size_everyone_counts(self):
        hunt = discovery.Hunt("news", "Novidades: K-pop")
        discovery.news(hunt, FakeSpotify(), self.deezer(), "k-pop", days=7)
        self.assertEqual({f.uri for f in hunt.finds}, {"spotify:track:1001", "spotify:track:1022",
                                                       "spotify:track:2001", "spotify:track:3001"})

    def test_today_only_counts_releases_from_today(self):
        hunt = discovery.Hunt("news", "Novidades: K-pop")
        discovery.news(hunt, FakeSpotify(), self.deezer(), "k-pop", days=0)  # the newest one came out yesterday
        self.assertEqual(hunt.finds, [])
        self.assertEqual(hunt.message, "Nenhum lançamento de k-pop nesse tamanho hoje. Aumente o período ou o tamanho.")

    def test_explains_when_nothing_fits(self):
        hunt = discovery.Hunt("news", "Novidades: K-pop")
        discovery.news(hunt, FakeSpotify(), self.deezer(), "k-pop", discovery.FanRange(100_000_000), days=30)
        self.assertEqual(hunt.finds, [])
        self.assertIn("Nenhum lançamento", hunt.message)

    def test_only_playlists_named_after_the_genre_count(self):
        # Searching "new Lo-fi" brought a hardcore playlist that never says lo-fi (a real case: Cro-Mags).
        deezer = FakeDeezer(
            playlists={
                "new Lo-fi": [{"id": "gta", "nb_tracks": 19, "title": "GTA Liberty City Hardcore"}],
                "Lo-fi": [{"id": "chill", "nb_tracks": 90, "title": "chill lofi"},
                          {"id": "study", "nb_tracks": 50, "title": "Lo Fi - New Playlist"}],
            },
            tracks={"gta": [song(1, "x", 10, "Cro-Mags")], "chill": [song(2, "x", 20, "Blue Wednesday")],
                    "study": [song(3, "x", 30, "Arlos")]},
        )
        self.assertEqual({a["name"] for a in discovery.genre_artists(deezer, "Lo-fi")}, {"Blue Wednesday", "Arlos"})

    def test_a_genre_counts_however_the_title_spells_it(self):
        named = [("chill lofi", "Lo-fi"), ("Lo Fi - New Playlist", "Lo-fi"), ("R&B Hits", "R&B"),
                 ("Pagodes 2026 - Lançamentos", "Pagode"), ("Pagodelícia", "Pagode"), ("Eletrônica 2026", "Eletrônica")]
        for title, genre in named:
            self.assertTrue(discovery.named_after(title, genre), title)
        others = [("GTA Liberty City Hardcore", "Lo-fi"), ("Hip Hop 2000", "Rap"), ("Memórias", "Emo"),
                  ("Lighthouse Family", "House"), ("Popular Brasil", "Pop"), ("Joia Rara", "joik"),
                  ("Read : Music to Sit with a Library Full of Books.", "library music"),
                  # The end of one word and the start of the next never make a genre.
                  ("Music For Romantic Dinner", "Forró"), ("Fun Kids Songs", "Funk"), ("Meta Lounge", "Metal"),
                  ("Sou Livre", "Soul")]
        for title, genre in others:
            self.assertFalse(discovery.named_after(title, genre), title)

    def test_a_longer_last_word_still_names_the_genre(self):
        for title, genre in [("Turkish Psychedelic Music", "turkish psych"), ("Midwest Emo Revival", "midwest emo")]:
            self.assertTrue(discovery.named_after(title, genre), title)

    def test_roulette_prefers_playlists_named_after_the_genre(self):
        # Searching "joik" brought "Joia Rara" (a real case): its songs aren't joik.
        deezer = FakeDeezer(playlists={"joik": [{"id": "joia", "nb_tracks": 30, "title": "Joia Rara"},
                                                {"id": "sami", "nb_tracks": 30, "title": "Joik - Sámi songs"}]},
                            tracks={"joia": [dz_track(1, 120)], "sami": [dz_track(2, 120)]})
        for seed in range(8):
            find = discovery.world_genre_pick(FakeSpotify(), deezer, random.Random(seed), genre="joik")
            self.assertEqual(find.uri, "spotify:track:2")

    def test_roulette_takes_what_the_search_found_when_no_title_names_the_genre(self):
        # The search knows genres by tag too: "rap nacional" brings "Essenciais do Rap Brasileiro".
        deezer = FakeDeezer(playlists={"rap nacional": [{"id": "br", "nb_tracks": 45,
                                                         "title": "Essenciais do Rap Brasileiro"}]},
                            tracks={"br": [dz_track(3, 90)]})
        find = discovery.world_genre_pick(FakeSpotify(), deezer, random.Random(1), genre="rap nacional")
        self.assertEqual(find.uri, "spotify:track:3")


def sized_track(track_id, bpm, artist_id):
    track = dz_track(track_id, bpm, artist=f"Artista {artist_id}")
    track["artist"]["id"] = artist_id
    return track


class SenseSizeTest(FreshMatches):
    def setUp(self):
        super().setUp()
        discovery.fan_counts = discovery.FanCounts()

    def test_within_size_keeps_order_and_stops_when_full(self):
        deezer = FakeDeezer(fans={1: 50, 2: 5_000, 3: 80_000})
        tracks = [sized_track(10, 120, 1), sized_track(11, 120, 2), sized_track(12, 120, 3), sized_track(13, 120, 2)]
        size = discovery.FanRange(1_000, 100_000)
        kept = discovery.within_size(deezer, tracks, size, want=2)
        self.assertEqual([t["id"] for t in kept], [11, 12])
        self.assertEqual(discovery.within_size(deezer, tracks, discovery.ANY_SIZE, want=3), tracks[:3])

    def test_sense_only_listens_to_artists_of_the_chosen_size(self):
        deezer = FakeDeezer(
            playlists={"treino": [{"id": "p", "nb_tracks": 50}]},
            tracks={"p": [sized_track(1, 128, 1), sized_track(2, 130, 2), sized_track(3, 140, 3)]},
            fans={1: 200, 2: 20_000, 3: 9_000_000},
        )
        spec = {**SPEC, "sources": ["treino"]}
        hunt = discovery.Hunt("sense", "Treino pesado")
        discovery.sense(hunt, spec, FakeSpotify(), deezer, random.Random(1), MemoryCache(), fake_measure,
                        size=discovery.FanRange(1_000, 1_000_000))
        self.assertEqual([(f.uri, f.fans) for f in hunt.finds], [("spotify:track:2", 20_000)])
        self.assertEqual(hunt.progress, 1)  # only the right-sized artist's preview was heard

    def test_says_when_no_artist_fits(self):
        deezer = FakeDeezer(
            playlists={"treino": [{"id": "p", "nb_tracks": 50}]},
            tracks={"p": [sized_track(1, 128, 1)]},
            fans={1: 200},
        )
        hunt = discovery.Hunt("sense", "Treino pesado")
        discovery.sense(hunt, {**SPEC, "sources": ["treino"]}, FakeSpotify(), deezer, random.Random(1), MemoryCache(),
                        fake_measure, size=discovery.FanRange(1_000))
        self.assertEqual(hunt.finds, [])
        self.assertIn("Nenhum artista desse tamanho", hunt.message)


class EnglishMessagesTest(FreshMatches):
    def setUp(self):
        super().setUp()
        i18n.use("en")

    def test_free_text_and_progress_in_english(self):
        spec = discovery.spec_from_text("missing you")
        self.assertEqual(spec["description"], "Songs for missing you.")
        self.assertEqual(spec["bpm"], [60, 115])  # the nostalgia entry
        self.assertEqual(discovery.spec_from_text("anger")["color"], "#D8453B")
        hunt = discovery.Hunt("rabbit", "Rabbit hole")
        discovery.rabbit_hole(hunt, FakeSpotify(), FakeDeezer(), random.Random(1), ["Nobody"], walks=1)
        self.assertEqual(hunt.message, "The hole led nowhere this time. Try again, with another artist or another size.")


class TempoCacheTest(unittest.TestCase):
    def test_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp)
            with mock.patch.object(config, "DATA_DIR", data), \
                    mock.patch.object(config, "TEMPO_CACHE_FILE", data / "tempo.json"):
                cache = discovery.TempoCache()
                cache.put("1", Analysis(128.0, 0.5, 0.7))
                cache.put("2", None)
                cache.save()
                again = discovery.TempoCache()
                self.assertEqual(again.get("1"), (True, Analysis(128.0, 0.5, 0.7)))
                self.assertEqual(again.get("2"), (True, None))
                self.assertEqual(again.get("3"), (False, None))


class FakeLastFm:
    """Listeners by title; titles it doesn't know have no record. Remembers who was asked about."""

    def __init__(self, listeners=None, error=None):
        self.listeners = listeners or {}
        self.error = error
        self.asked = []
        self.fresh = []  # how old a cached count could be, per lookup (None: the cache's default)

    def __call__(self, artist, title, fresh_s=None):
        self.asked.append((artist, title))
        self.fresh.append(fresh_s)
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

    def test_a_blank_artist_name_cant_be_checked(self):
        # A real case: a 13th Floor Elevators classic credited to "\xa0, \xa0" found a stray entry with 22 listeners.
        fake = FakeLastFm({"You're Gonna Miss Me": 22})
        cap = discovery.ListenerCap(1000, fake)
        for blank in ("\xa0, \xa0", "", " - "):
            self.assertEqual(cap.check(blank, "You're Gonna Miss Me"), (False, None))
        self.assertEqual(fake.asked, [])
        self.assertTrue(cap.check("13th Floor Elevators", "Sumida")[0])

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

    def test_features_are_looked_up_under_their_own_artist(self):
        # Deezer's top tracks include songs where the hop artist is only featured: the star's hit.
        deezer = FakeDeezer(
            artists={"Chet Baker": {"id": 1, "name": "Chet Baker", "nb_fan": 500000}},
            related={1: [{"id": 2, "name": "Pequena", "nb_fan": 3800}]},
            tops={2: [{"id": 21, "title": "Hit", "artist": {"name": "Estrela"}}, {"id": 22, "title": "Lado B"}]},
        )
        fake = FakeLastFm({"Hit": 2_000_000})
        hunt = discovery.Hunt("rabbit", "Toca do coelho")
        discovery.rabbit_hole(hunt, FakeSpotify(), deezer, random.Random(), ["Chet Baker"], walks=1,
                              listeners=discovery.ListenerCap(100, fake))
        self.assertIn(("Estrela", "Hit"), fake.asked)
        self.assertEqual([f.uri for f in hunt.finds], ["spotify:track:22"])

    def test_soundtrack_fallback_is_looked_up_under_its_own_artist(self):
        today = date.today().isoformat()
        deezer = FakeDeezer(
            playlists={"k-pop": [{"id": "p", "nb_tracks": 30, "title": "K-pop"}]},
            tracks={"p": [song(1, "x", 10, "Banda")]},
            # A soundtrack where the band has no track of its own: the pick falls back to someone else's.
            albums={10: [{"id": 100, "title": "Trilha", "release_date": today, "record_type": "album"}]},
            album_songs={100: [song(1001, "Tema", 99, "Estrela")]},
        )
        fake = FakeLastFm({"Tema": 900_000})
        hunt = discovery.Hunt("news", "Novidades: K-pop")
        discovery.news(hunt, FakeSpotify(), deezer, "k-pop", days=7, listeners=discovery.ListenerCap(100, fake))
        self.assertEqual(fake.asked, [("Estrela", "Tema")])
        self.assertEqual(hunt.finds, [])

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

    def test_new_releases_ask_for_fresh_counts(self):
        # A release's listeners grow fastest in its first days: a month-old count would let it through a cap.
        today = date.today().isoformat()
        deezer = FakeDeezer(
            playlists={"k-pop": [{"id": "p", "nb_tracks": 30, "title": "K-pop"}]},
            tracks={"p": [song(1, "x", 10, "Banda")]},
            albums={10: [{"id": 100, "title": "Hit", "release_date": today, "record_type": "single"}]},
            album_songs={100: [song(1001, "Hit", 10, "Banda")]},
        )
        fake = FakeLastFm()
        discovery.news(discovery.Hunt("news", "Novidades"), FakeSpotify(), deezer, "k-pop", days=7,
                       listeners=discovery.ListenerCap(100, fake))
        self.assertEqual(fake.fresh, [discovery.NEWS_LISTENERS_FRESH_S])
        roulette = FakeLastFm()
        discovery.ListenerCap(100, roulette).check("Banda", "Hit")
        self.assertEqual(roulette.fresh, [None])  # everywhere else, the cache's month

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

    def test_within_listeners_reports_every_check(self):
        # With a small cap most songs are turned down: the message still moves, or the panel looks frozen.
        hunt = discovery.Hunt("sense", "Treino")
        fake = FakeLastFm({f"Faixa {n}": 900 for n in range(5)})
        discovery.within_listeners([dz_track(n, 120) for n in range(5)], discovery.ListenerCap(100, fake), want=2,
                                   hunt=hunt)
        self.assertEqual(hunt.message, "Conferindo ouvintes no Last.fm: 5 conferidas, 0 dentro do limite.")

    def test_within_listeners_asks_several_at_once(self):
        active, peak, lock = [0], [0], threading.Lock()

        def slow(artist, title):
            with lock:
                active[0] += 1
                peak[0] = max(peak[0], active[0])
            time.sleep(0.05)
            with lock:
                active[0] -= 1
            return lastfm.Listeners(None, None)

        kept = discovery.within_listeners([dz_track(n, 120) for n in range(6)], discovery.ListenerCap(100, slow), want=6)
        self.assertEqual([track["id"] for track in kept], list(range(6)))  # the order is kept
        self.assertGreater(peak[0], 1)

    def test_lastfm_failures_stop_the_roulette(self):
        deezer = FakeDeezer(
            playlists={"fado": [{"id": "p", "nb_tracks": 30, "title": "Fado"}]},
            tracks={"p": [dz_track(1, 120)]},
        )
        hunt = discovery.Hunt("roulette", "Roleta")
        with self.assertRaises(lastfm.LastFmError):
            discovery.roulette(hunt, FakeSpotify(), deezer, random.Random(1), genre="fado",
                               listeners=discovery.ListenerCap(100, FakeLastFm(error="down")))


class SongSpotify(FakeSpotify):
    """Finds songs by their text: every song it has is a candidate, and the matching keeps the right one."""

    def __init__(self, songs, missing=()):
        super().__init__()
        self.songs = songs  # (artist, title) pairs
        self.missing_titles = set(missing)
        self.text_searches = []

    def search(self, query, kind, offset=0):
        if query.startswith("isrc:"):
            return super().search(query, kind, offset)
        self.text_searches.append(query)
        return [{"uri": f"spotify:track:{title}", "name": title, "artists": [{"name": artist}],
                 "album": {"images": []}, "duration_ms": 1000}
                for artist, title in self.songs if title not in self.missing_titles]


def similar_from(graph):
    """Last.fm's similar tracks by title, closest first; a title it doesn't know has no record."""
    def similar(artist, title):
        if title not in graph:
            return None
        return [lastfm.Similar(by, name, 1 - index / 100, plays) for index, (by, name, plays) in enumerate(graph[title])]
    return similar


EVERLONG = {"artist": "Foo Fighters", "title": "Everlong"}
TRAIL = {
    "Everlong": [("Foo Fighters", "My Hero", 100), ("Weezer", "Say It Ain't So", 50)],
    "Say It Ain't So": [("Weezer", "Buddy Holly", 70), ("Pixies", "Where Is My Mind?", 30)],
    "Where Is My Mind?": [("Foo Fighters", "Big Me", 5), ("Built to Spill", "Car", 10)],
    "Car": [],
}
TRAIL_SONGS = [("Foo Fighters", "My Hero"), ("Foo Fighters", "Big Me"), ("Weezer", "Say It Ain't So"),
               ("Weezer", "Buddy Holly"), ("Pixies", "Where Is My Mind?"), ("Built to Spill", "Car")]


def t_pt(key, **values):
    i18n.use("pt")
    return i18n.t(key, **values)


class SongHoleTest(FreshMatches):
    def setUp(self):
        super().setUp()
        discovery.fan_counts = discovery.FanCounts()

    def hole(self, seed=EVERLONG, graph=TRAIL, sp=None, dz=None, walks=1, **options):
        hunt = discovery.Hunt("rabbit", "Toca do coelho")
        similar = similar_from(graph) if graph is not None else None
        discovery.song_hole(hunt, sp or SongSpotify(TRAIL_SONGS), dz or FakeDeezer(), similar, random.Random(1), seed,
                            walks=walks, **options)
        return hunt

    def test_hops_from_song_to_song_never_back_to_an_artist_on_the_way(self):
        hunt = self.hole()
        self.assertEqual([f.title for f in hunt.finds], ["Say It Ain't So", "Where Is My Mind?", "Car"])
        chain = hunt.chains[0]
        self.assertEqual([step["name"] for step in chain["path"]],
                         ["Everlong (Foo Fighters)", "Say It Ain't So (Weezer)", "Where Is My Mind? (Pixies)",
                          "Car (Built to Spill)"])
        self.assertEqual([f.reason for f in hunt.finds],
                         ["Passo 1 de 3 a partir de “Everlong”.", "Passo 2 de 3 a partir de “Everlong”.",
                          "Fim da trilha: 3 músicas depois de “Everlong”."])
        self.assertEqual(hunt.label, "Toca do coelho: Everlong")

    def test_leans_toward_the_less_played(self):
        graph = {"Everlong": [(f"Banda {n}", f"Música {n}", plays) for n, plays in
                              enumerate([5000, 4000, 10, 3000, 2000, 1000])]}
        songs = [(f"Banda {n}", f"Música {n}") for n in range(6)]
        firsts = set()
        for seed in range(12):
            hunt = discovery.Hunt("rabbit", "Toca do coelho")
            discovery.song_hole(hunt, SongSpotify(songs), FakeDeezer(), similar_from(graph), random.Random(seed),
                                EVERLONG, walks=1)
            firsts.add(hunt.finds[0].title)
        self.assertEqual(firsts, {"Música 2", "Música 5"})  # the least played third

    def test_trips_dont_repeat_songs(self):
        hunt = self.hole(walks=3)
        uris = [f.uri for f in hunt.finds]
        self.assertEqual(len(uris), len(set(uris)))
        self.assertEqual(hunt.progress, 3)

    def test_blocked_and_religious_songs_are_skipped(self):
        graph = {"Everlong": [("Weezer", "Say It Ain't So", 5), ("Hillsong", "Louvor a Deus", 1),
                              ("Pixies", "Where Is My Mind?", 9)]}
        songs = [("Weezer", "Say It Ain't So"), ("Hillsong", "Louvor a Deus"), ("Pixies", "Where Is My Mind?")]
        hunt = self.hole(graph=graph, sp=SongSpotify(songs), blocked=discovery.blocked_set(["Weezer"]))
        self.assertEqual([f.title for f in hunt.finds], ["Where Is My Mind?"])

    def test_listener_cap_and_size_apply_to_each_step(self):
        graph = {"Everlong": [("Weezer", "Say It Ain't So", 5), ("Pixies", "Where Is My Mind?", 9),
                              ("Built to Spill", "Car", 20)]}
        cap = discovery.ListenerCap(100, FakeLastFm({"Say It Ain't So": 90000, "Where Is My Mind?": 40, "Car": 30}))
        dz = FakeDeezer(artists={"Pixies": {"id": 2, "name": "Pixies", "nb_fan": 2_000_000},
                                 "Built to Spill": {"id": 3, "name": "Built to Spill", "nb_fan": 90_000}})
        hunt = self.hole(graph=graph, dz=dz, listeners=cap, size=discovery.FanRange(0, 100_000))
        self.assertEqual([(f.title, f.fans, f.lastfm["listeners"]) for f in hunt.finds], [("Car", 90_000, 30)])

    def test_a_one_step_trail_says_so_in_the_singular(self):
        hunt = self.hole(graph={"Everlong": [("Weezer", "Say It Ain't So", 5)]})
        self.assertEqual(hunt.finds[0].reason, "Fim da trilha: 1 música depois de “Everlong”.")

    def test_last_fm_failing_midway_keeps_the_songs_found(self):
        def similar(artist, title):
            if title == "Where Is My Mind?":
                raise lastfm.LastFmError("limit")
            return similar_from(TRAIL)(artist, title)
        hunt = discovery.Hunt("rabbit", "Toca do coelho")
        discovery.song_hole(hunt, SongSpotify(TRAIL_SONGS), FakeDeezer(), similar, random.Random(1), EVERLONG, walks=3)
        self.assertEqual([f.title for f in hunt.finds], ["Say It Ain't So", "Where Is My Mind?"])
        self.assertEqual(hunt.finds[-1].reason, "Fim da trilha: 2 músicas depois de “Everlong”.")

    def test_last_fm_refusing_before_any_song_says_why(self):
        cap = discovery.ListenerCap(100, FakeLastFm(error="key"))
        with self.assertRaises(lastfm.LastFmError) as caught:
            self.hole(listeners=cap)
        self.assertEqual(caught.exception.kind, "key")

    def test_spotify_lookups_per_step_are_capped(self):
        graph = {"Everlong": [(f"Banda {n}", f"Música {n}", n) for n in range(9)]}
        songs = [(f"Banda {n}", f"Música {n}") for n in range(9)]
        sp = SongSpotify(songs, missing={f"Música {n}" for n in range(9)})
        hunt = self.hole(graph=graph, sp=sp)
        self.assertEqual(len(sp.text_searches), discovery.SONG_HOP_TRIES)
        self.assertEqual(hunt.finds, [])
        self.assertEqual(hunt.message, t_pt("rabbit.none"))

    def test_a_typed_song_is_looked_up_in_the_catalog_first(self):
        dz = FakeDeezer(songs={"everlong foo": [{"id": 9, "title": "Everlong", "title_short": "Everlong",
                                                 "artist": {"name": "Foo Fighters"}}]})
        sp = SongSpotify(TRAIL_SONGS)
        hunt = self.hole(seed="everlong foo", dz=dz, sp=sp)
        self.assertEqual(hunt.label, "Toca do coelho: Everlong")
        self.assertEqual(len(hunt.finds), 3)
        self.assertNotIn("everlong foo", sp.text_searches)

    def test_then_on_spotify(self):
        class TypedSpotify(SongSpotify):
            def search(self, query, kind, offset=0):
                if query == "everlong":
                    return [{"uri": "spotify:track:ev", "name": "Everlong", "artists": [{"name": "Foo Fighters"}]}]
                return super().search(query, kind, offset)
        hunt = self.hole(seed="everlong", sp=TypedSpotify(TRAIL_SONGS))
        self.assertEqual(hunt.label, "Toca do coelho: Everlong")
        self.assertEqual(len(hunt.finds), 3)

    def test_a_song_nobody_finds(self):
        hunt = self.hole(seed="zzzz", sp=SongSpotify([]))
        self.assertEqual((hunt.finds, hunt.message), ([], t_pt("rabbit.song_unknown")))

    def test_a_song_last_fm_doesnt_know_goes_through_its_artist(self):
        dz = FakeDeezer(
            artists={"Foo Fighters": {"id": 1, "name": "Foo Fighters", "nb_fan": 5_000_000}},
            related={1: [{"id": 2, "name": "Pequena", "nb_fan": 3800}]},
            tops={2: [{"id": 21, "title": "Faixa 21"}, {"id": 22, "title": "Faixa 22"}]},
        )
        for graph in ({}, None):  # no record of the song; no Last.fm key at all
            with self.subTest(graph=graph):
                discovery.matches = discovery.MatchCache()
                hunt = self.hole(graph=graph, dz=dz, sp=FakeSpotify())
                self.assertEqual([f.uri for f in hunt.finds], ["spotify:track:21", "spotify:track:22"])
                self.assertTrue(hunt.message.startswith(
                    "Nenhuma música parecida com “Everlong” por aqui: a toca seguiu pelo artista, Foo Fighters."),
                    hunt.message)

if __name__ == "__main__":
    unittest.main()
