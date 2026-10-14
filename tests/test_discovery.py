import random
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from spotify_assistant import config, discovery
from spotify_assistant.tempo import Analysis


def dz_track(track_id, bpm, energy=0.8, title=None, artist="Artista", rank=1000, preview=True):
    return {
        "id": track_id,
        "title": title or f"Faixa {track_id}",
        "artist": {"name": artist},
        "isrc": f"ISRC{track_id}",
        "rank": rank,
        "readable": True,
        # O medidor falso lê BPM e energia direto da "prévia".
        "preview": f"{bpm}:{energy}" if preview else "",
    }


def fake_measure(data: bytes) -> Analysis:
    bpm, energy = data.decode().split(":")
    return Analysis(float(bpm), 0.9, float(energy))


class FakeDeezer:
    def __init__(self, playlists=None, tracks=None, artists=None, related=None, tops=None):
        self.playlists = playlists or {}
        self.tracks = tracks or {}
        self.artists = artists or {}
        self._related = related or {}
        self.tops = tops or {}

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
    """Toda faixa do Deezer existe no Spotify com o mesmo número."""

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
        self.assertFalse(discovery.is_junk(dz_track(3, 60, title="Hertz e Amor")))

    def test_next_hop_goes_to_lesser_known(self):
        options = [{"id": i, "nb_fan": fans} for i, fans in enumerate([50, 900, 5000, 80000, 120000, 3000000])]
        picks = {discovery.next_hop(options, {2}, random.Random(seed))["id"] for seed in range(30)}
        # 50 fãs fica de fora (mínimo) e 5000 já foi visitado: sobra o terço de baixo dos restantes.
        self.assertEqual(picks, {1})
        self.assertIsNone(discovery.next_hop([{"id": 9, "nb_fan": 10}], set(), random.Random()))

    def test_lesser_known_is_bottom_half_by_rank(self):
        tracks = [{"rank": rank} for rank in (900, 100, 500, 300)]
        self.assertEqual([t["rank"] for t in discovery.lesser_known(tracks)], [100, 300])


class SenseTest(unittest.TestCase):
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
        # 2 (90) fora; 3 (70) vira 140; 4 sem energia; 8 não existe no Spotify.
        self.assertEqual(found, {"spotify:track:1": 128, "spotify:track:3": 140, "spotify:track:7": 145})
        self.assertEqual(hunt.progress, 6)
        self.assertIn("3 músicas", hunt.message)

    def test_cached_measurements_skip_download(self):
        cache = MemoryCache()
        cache.put("1", Analysis(130, 1, 0.9))
        deezer = self.deezer()
        deezer.preview = mock.Mock(side_effect=lambda url: url.encode())
        hunt = discovery.Hunt("sense", "Treino pesado")
        discovery.sense(hunt, SPEC, FakeSpotify(), deezer, random.Random(3), cache, fake_measure)
        downloaded = {call.args[0] for call in deezer.preview.call_args_list}
        self.assertNotIn("128:0.8", downloaded)  # prévia da faixa 1, já medida
        self.assertEqual(deezer.preview.call_count, 5)  # 6 candidatas, 1 já medida


class RabbitTest(unittest.TestCase):
    def test_walks_away_and_keeps_the_path(self):
        deezer = FakeDeezer(
            artists={"Chet Baker": {"id": 1, "name": "Chet Baker", "nb_fan": 500000}},
            related={
                1: [{"id": 2, "name": "Sonny Clark", "nb_fan": 3800}],
                2: [{"id": 3, "name": "Tina Brooks", "nb_fan": 644}],
            },
            tops={3: [
                {"id": 31, "title": "Eu e a Brisa"},
                {"id": 30, "title": "Eu e a Brisa (Ao Vivo)"},  # mesma música: pula
                {"id": 32, "title": "Rapaz de Bem"},
                {"id": 33, "title": "Céu e Mar"},
            ]},
        )
        hunt = discovery.Hunt("rabbit", "Toca do coelho")
        discovery.rabbit_hole(hunt, FakeSpotify(), deezer, random.Random(), ["Chet Baker"], walks=1)
        chain = hunt.chains[0]
        self.assertEqual([a["name"] for a in chain["path"]], ["Chet Baker", "Sonny Clark", "Tina Brooks"])
        self.assertEqual([f.uri for f in chain["finds"]], ["spotify:track:31", "spotify:track:32"])

    def test_unknown_seed_reports_nothing_found(self):
        hunt = discovery.Hunt("rabbit", "Toca do coelho")
        discovery.rabbit_hole(hunt, FakeSpotify(), FakeDeezer(), random.Random(), ["Ninguém"], walks=2)
        self.assertEqual(hunt.finds, [])
        self.assertIn("não levou", hunt.message)


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
