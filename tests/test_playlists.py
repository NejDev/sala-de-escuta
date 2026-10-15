import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

from spotify_assistant import config
from spotify_assistant.playlists import run


class FakeSpotify:
    """In-memory catalog that mimics the Web API's responses."""

    def __init__(self, owned=None):
        self.playlists = dict(owned or {})  # id -> {"name", "uris"}
        self.created = []
        self.descriptions = {}

    def search(self, query, kind):
        if kind == "show":
            return [{"id": "show-hipsters", "name": "Hipsters Ponto Tech", "languages": ["pt"]}] if "Hipsters" in query else []
        if query.startswith("artist:"):
            artist = query.removeprefix("artist:")
            return [self._track(f"{artist} song {i}", artist) for i in range(4)]
        title, artist = query.rsplit(" ", 1) if " " in query else (query, "")
        return [self._track(title, artist)]

    @staticmethod
    def _track(name, artist):
        return {"name": name, "artists": [{"name": artist}], "album": {"name": "A"}, "uri": f"spotify:track:{name}"}

    def show_episodes(self, show_id):
        return [
            {"name": "ep2", "release_date": "2026-10-13", "release_date_precision": "day", "uri": "spotify:episode:2"},
            {"name": "ep1", "release_date": "2026-10-06", "release_date_precision": "day", "uri": "spotify:episode:1"},
            {"name": "ep0", "release_date": "2026-08-01", "release_date_precision": "day", "uri": "spotify:episode:0"},
        ]

    def me(self):
        return {"id": "paulo"}

    def my_playlists(self):
        for pid, playlist in self.playlists.items():
            yield {"id": pid, "name": playlist["name"], "owner": {"id": "paulo"}}

    def create_playlist(self, name, description, public):
        pid = f"pl-{len(self.playlists)}"
        self.playlists[pid] = {"name": name, "uris": []}
        self.created.append(name)
        return {"id": pid}

    def replace_items(self, playlist_id, uris):
        self.playlists[playlist_id]["uris"] = list(uris)

    def update_details(self, playlist_id, **fields):
        self.descriptions[playlist_id] = fields["description"]


CONFIG = {
    "playlists": [
        {"name": "Tech", "description": "Pods.", "refresh": "weekly",
         "podcasts": {"max_age_days": 10, "max_per_show": 2, "shows": ["Hipsters Ponto Tech", "Inexistente"]}},
        {"name": "Jazz", "tracks": ["Miles - SoWhat", "Chet - Almost"]},
        {"name": "Lofi", "shuffle": True, "artists": {"per_artist": 2, "names": ["Nujabes"]}},
        {"name": "Mix", "mix": {"from": ["Jazz", "Lofi"], "per_source": 1}},
    ]
}


class RunTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        data = Path(tmp.name)
        for name, value in {"DATA_DIR": data, "STATE_FILE": data / "state.json"}.items():
            patcher = mock.patch.object(config, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def by_name(self, sp):
        return {p["name"]: p["uris"] for p in sp.playlists.values()}

    def test_setup_creates_everything(self):
        sp, state = FakeSpotify(), {}
        run(sp, CONFIG, state, today=date(2026, 10, 14))

        playlists = self.by_name(sp)
        self.assertEqual(sorted(sp.created), ["Jazz", "Lofi", "Mix", "Tech"])
        self.assertEqual(playlists["Tech"], ["spotify:episode:2", "spotify:episode:1"])
        self.assertEqual(playlists["Jazz"], ["spotify:track:SoWhat", "spotify:track:Almost"])
        self.assertEqual(len(playlists["Lofi"]), 2)
        self.assertEqual(len(playlists["Mix"]), 2)
        self.assertIn("14/10/2026", next(iter(sp.descriptions.values())))
        self.assertEqual(state["shows"], {"Hipsters Ponto Tech": "show-hipsters"})

    def test_weekly_only_touches_podcasts_and_reuses_playlist(self):
        sp = FakeSpotify(owned={"existing": {"name": "Tech", "uris": ["old"]}})
        run(sp, CONFIG, {}, weekly=True, today=date(2026, 10, 14))

        self.assertEqual(sp.created, [])
        self.assertEqual(sp.playlists["existing"]["uris"], ["spotify:episode:2", "spotify:episode:1"])

    def test_recreates_playlist_deleted_in_app(self):
        sp = FakeSpotify()
        run(sp, CONFIG, {"playlists": {"Jazz": "deleted-id"}}, only=["Jazz"])
        self.assertEqual(sp.created, ["Jazz"])

    def test_dry_run_writes_nothing(self):
        sp = FakeSpotify()
        run(sp, CONFIG, {}, dry_run=True, today=date(2026, 10, 14))
        self.assertEqual(sp.playlists, {})

    def test_empty_week_keeps_current_content(self):
        sp = FakeSpotify(owned={"existing": {"name": "Tech", "uris": ["old"]}})
        run(sp, CONFIG, {}, weekly=True, today=date(2027, 1, 1))
        self.assertEqual(sp.playlists["existing"]["uris"], ["old"])

    def test_unknown_mix_source_is_reported(self):
        bad = {"playlists": [{"name": "Mix", "mix": {"from": ["Nope"]}}]}
        with self.assertRaises(SystemExit):
            run(FakeSpotify(), bad, {})


if __name__ == "__main__":
    unittest.main()


class FirstRunTest(unittest.TestCase):
    def test_curation_starts_from_the_example(self):
        import tempfile
        from pathlib import Path
        from unittest import mock

        from spotify_assistant import config

        with tempfile.TemporaryDirectory() as tmp:
            mine, example = Path(tmp) / "playlists.json", Path(tmp) / "playlists.example.json"
            example.write_text('{"market": "BR", "playlists": []}', encoding="utf-8")
            with mock.patch.object(config, "PLAYLISTS_FILE", mine), mock.patch.object(config, "PLAYLISTS_EXAMPLE_FILE", example):
                self.assertEqual(config.load_playlists(), {"market": "BR", "playlists": []})
            self.assertTrue(mine.exists())
