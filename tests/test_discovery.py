import random
from datetime import date, timedelta
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from spotify_assistant import config, discovery, i18n
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
                 fans=None, albums=None, album_songs=None):
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


if __name__ == "__main__":
    unittest.main()
