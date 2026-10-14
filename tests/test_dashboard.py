import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

from spotify_assistant import auth, config, dashboard
from spotify_assistant.config import Settings

CONFIG = {
    "market": "BR",
    "playlists": [
        {"name": "Tech", "description": "Pods.", "refresh": "weekly", "podcasts": {"shows": ["Hipsters"]}},
        {"name": "Jazz", "description": "Noite.", "color": "#D4A84B", "tracks": ["Miles Davis - So What"]},
        {"name": "Mix", "mix": {"from": ["Jazz"], "per_source": 1}},
    ],
}

TRACK = {
    "type": "track",
    "uri": "spotify:track:1",
    "name": "So What",
    "duration_ms": 562000,
    "artists": [{"name": "Miles Davis"}],
    "album": {"images": [{"url": "big", "width": 640}, {"url": "mid", "width": 300}, {"url": "small", "width": 64}]},
}


class FakeSpotify:
    def __init__(self):
        self.added = []

    def me(self):
        return {"id": "paulo", "display_name": "Nej"}

    def my_playlists(self):
        yield {"id": "pl-jazz", "uri": "spotify:playlist:pl-jazz", "images": [{"url": "mosaic", "width": None}],
               "items": {"total": 1}, "owner": {"id": "paulo"}}

    def playlist_items(self, playlist_id):
        return [TRACK]

    def add_items(self, playlist_id, uris):
        self.added.append((playlist_id, uris))

    def search(self, query, kind):
        return [TRACK]


class HelpersTest(unittest.TestCase):
    def test_pick_image_prefers_smallest_that_fits(self):
        images = TRACK["album"]["images"]
        self.assertEqual(dashboard.pick_image(images, 64), "small")
        self.assertEqual(dashboard.pick_image(images, 120), "mid")
        self.assertEqual(dashboard.pick_image([{"url": "mosaic", "width": None}], 300), "mosaic")
        self.assertIsNone(dashboard.pick_image(None, 64))

    def test_item_row_for_track_and_episode(self):
        self.assertEqual(dashboard.item_row(TRACK), {
            "uri": "spotify:track:1", "type": "track", "title": "So What", "duration_ms": 562000,
            "subtitle": "Miles Davis", "image": "small",
        })
        episode = {"type": "episode", "uri": "spotify:episode:9", "name": "#537", "duration_ms": 1,
                   "release_date": "2026-10-13", "images": [], "show": {"name": "Hipsters", "images": [{"url": "s", "width": 64}]}}
        row = dashboard.item_row(episode)
        self.assertEqual((row["subtitle"], row["image"], row["release_date"]), ("Hipsters", "s", "2026-10-13"))


class AddToConfigTest(unittest.TestCase):
    def setUp(self):
        self.config = json.loads(json.dumps(CONFIG))

    def test_appends_track_and_show(self):
        dashboard.add_to_config(self.config, "Jazz", "Bill Evans - Peace Piece")
        dashboard.add_to_config(self.config, "Tech", "Data Hackers")
        self.assertEqual(self.config["playlists"][1]["tracks"][-1], "Bill Evans - Peace Piece")
        self.assertEqual(self.config["playlists"][0]["podcasts"]["shows"], ["Hipsters", "Data Hackers"])

    def test_rejects_duplicates_mixes_and_unknown(self):
        with self.assertRaises(dashboard.UserError) as duplicate:
            dashboard.add_to_config(self.config, "Jazz", "Miles Davis - So What")
        self.assertEqual(duplicate.exception.status, 409)
        with self.assertRaises(dashboard.UserError):
            dashboard.add_to_config(self.config, "Mix", "X - Y")
        with self.assertRaises(dashboard.UserError):
            dashboard.add_to_config(self.config, "Nope", "X - Y")


class ServerTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        data = Path(tmp.name)
        (data / "playlists.json").write_text(json.dumps(CONFIG), encoding="utf-8")
        (data / "state.json").write_text(json.dumps({"playlists": {"Jazz": "pl-jazz"}}), encoding="utf-8")
        token = {"scope": auth.SCOPES, "access_token": "x", "refresh_token": "y", "expires_at": 0}
        (data / "token.json").write_text(json.dumps(token), encoding="utf-8")
        patches = [
            mock.patch.object(config, "PLAYLISTS_FILE", data / "playlists.json"),
            mock.patch.object(config, "STATE_FILE", data / "state.json"),
            mock.patch.object(config, "DATA_DIR", data),
            mock.patch.object(auth, "TOKEN_FILE", data / "token.json"),
            mock.patch.object(dashboard, "read_schedule", return_value=None),
        ]
        for patcher in patches:
            patcher.start()
            self.addCleanup(patcher.stop)
        self.data = data

        self.fake = FakeSpotify()
        app = dashboard.App(Settings("client", "http://127.0.0.1:0/callback"))
        app.spotify = lambda: self.fake
        self.server = dashboard.DashboardServer(("127.0.0.1", 0), app)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"

    def request(self, path, body=None, headers=None):
        data = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(self.base + path, data=data, headers=headers or {})
        if body is not None and "Content-Type" not in (headers or {}):
            request.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(request) as response:
                return response.status, response.read()
        except urllib.error.HTTPError as err:
            return err.code, err.read()

    def test_serves_page_and_blocks_traversal(self):
        status, body = self.request("/")
        self.assertEqual(status, 200)
        self.assertIn(b"Sala de escuta", body)
        self.assertEqual(self.request("/app.js")[0], 200)
        self.assertEqual(self.request("/../dashboard.py")[0], 404)
        self.assertEqual(self.request("/%2e%2e/dashboard.py")[0], 404)

    def test_overview(self):
        status, body = self.request("/api/overview")
        data = json.loads(body)
        self.assertEqual(status, 200)
        self.assertEqual(data["user"], "Nej")
        self.assertTrue(data["player_ready"])
        jazz = data["playlists"][1]
        self.assertEqual((jazz["uri"], jazz["image"], jazz["total"], jazz["color"]),
                         ("spotify:playlist:pl-jazz", "mosaic", 1, "#D4A84B"))
        self.assertEqual(data["playlists"][0]["uri"], None)  # ainda não criada
        self.assertEqual(data["playlists"][2]["sources"], ["Jazz"])

    def test_playlist_detail_with_encoded_name(self):
        status, body = self.request("/api/playlists/Jazz")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["items"][0]["title"], "So What")
        self.assertEqual(self.request("/api/playlists/N%C3%A3o%20existe")[0], 404)

    def test_add_track_updates_spotify_and_config(self):
        status, body = self.request("/api/playlists/Jazz/items", {"uri": "spotify:track:2", "entry": "Bill Evans - Peace Piece"})
        self.assertEqual(status, 200, body)
        self.assertEqual(self.fake.added, [("pl-jazz", ["spotify:track:2"])])
        saved = json.loads((self.data / "playlists.json").read_text(encoding="utf-8"))
        self.assertIn("Bill Evans - Peace Piece", saved["playlists"][1]["tracks"])

    def test_add_show_caches_its_id(self):
        status, _ = self.request("/api/playlists/Tech/items", {"uri": "spotify:show:abc", "entry": "Data Hackers"})
        self.assertEqual(status, 200)
        state = json.loads((self.data / "state.json").read_text(encoding="utf-8"))
        self.assertEqual(state["shows"]["Data Hackers"], "abc")

    def test_rejects_foreign_host_and_non_json_posts(self):
        self.assertEqual(self.request("/api/overview", headers={"Host": "evil.example:80"})[0], 403)
        status, _ = self.request("/api/player", {"action": "pause"}, headers={"Content-Type": "text/plain"})
        self.assertEqual(status, 415)

    def test_unknown_route(self):
        self.assertEqual(self.request("/api/nada")[0], 404)


if __name__ == "__main__":
    unittest.main()
