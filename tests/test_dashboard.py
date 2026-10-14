import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.parse
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


class PauseMessageTest(unittest.TestCase):
    def test_says_what_is_paused_and_when_it_comes_back(self):
        from spotify_assistant.api import SpotifyError

        message = dashboard.spotify_message(SpotifyError(429, "x", retry_after=3600, family="search"))
        self.assertIn("pausou as buscas", message)
        self.assertRegex(message, r"Voltam por volta de \d\d:\d\d (hoje|amanhã)\.")
        self.assertIn("esse tipo de pedido", dashboard.spotify_message(SpotifyError(429, "x", family="albums")))


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
    """Servidor de verdade com duas pessoas: o dono (paulo) e um amigo (ana)."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        data = Path(tmp.name)
        (data / "playlists.json").write_text(json.dumps(CONFIG), encoding="utf-8")
        token = {"scope": auth.SCOPES, "access_token": "x", "refresh_token": "y", "expires_at": 4_000_000_000}
        for user_id, state in (("paulo", {"playlists": {"Jazz": "pl-jazz"}}), ("ana", {"playlists": {"Jazz": "pl-ana"}})):
            folder = data / "users" / user_id
            folder.mkdir(parents=True)
            (folder / "token.json").write_text(json.dumps(token), encoding="utf-8")
            (folder / "state.json").write_text(json.dumps(state), encoding="utf-8")
            (folder / "perfil.json").write_text(json.dumps({"name": user_id.title()}), encoding="utf-8")
        (data / "owner.txt").write_text("paulo", encoding="utf-8")
        patches = [
            mock.patch.object(config, "PLAYLISTS_FILE", data / "playlists.json"),
            mock.patch.object(config, "DATA_DIR", data),
            mock.patch.object(dashboard, "read_schedule", return_value=None),
        ]
        for patcher in patches:
            patcher.start()
            self.addCleanup(patcher.stop)
        self.data = data

        self.fake = FakeSpotify()
        app = dashboard.App(Settings("client", "http://127.0.0.1:0/callback", "https://sala.example"))
        app.spotify = lambda user: self.fake
        self.server = dashboard.DashboardServer(("127.0.0.1", 0), app)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.cookies = {name: app.sessions.create(name) for name in ("paulo", "ana")}

    def request(self, path, body=None, headers=None, as_user="paulo"):
        data = json.dumps(body).encode() if body is not None else None
        headers = dict(headers or {})
        if as_user:
            headers.setdefault("Cookie", f"sala={self.cookies[as_user]}")
        request = urllib.request.Request(self.base + path, data=data, headers=headers)
        if body is not None and "Content-Type" not in headers:
            request.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(request) as response:
                return response.status, response.read()
        except urllib.error.HTTPError as err:
            return err.code, err.read()

    def test_serves_page_and_blocks_traversal(self):
        status, body = self.request("/", as_user=None)
        self.assertEqual(status, 200)
        self.assertIn(b"Sala de escuta", body)
        self.assertEqual(self.request("/app.js", as_user=None)[0], 200)
        self.assertEqual(self.request("/../dashboard.py")[0], 404)
        self.assertEqual(self.request("/%2e%2e/dashboard.py")[0], 404)

    def test_api_requires_login(self):
        status, body = self.request("/api/overview", as_user=None)
        self.assertEqual(status, 401)
        self.assertTrue(json.loads(body)["login"])
        status, _ = self.request("/api/overview", headers={"Cookie": "sala=inventado"}, as_user=None)
        self.assertEqual(status, 401)

    def test_overview_knows_who_is_asking(self):
        status, body = self.request("/api/overview")
        data = json.loads(body)
        self.assertEqual(status, 200)
        self.assertEqual(data["me"], {"id": "paulo", "name": "Paulo", "is_owner": True})
        self.assertTrue(data["player_ready"])
        jazz = data["playlists"][1]
        self.assertEqual((jazz["uri"], jazz["image"], jazz["total"], jazz["color"]),
                         ("spotify:playlist:pl-jazz", "mosaic", 1, "#D4A84B"))
        self.assertEqual(data["playlists"][0]["uri"], None)  # ainda não criada
        self.assertEqual(data["playlists"][2]["sources"], ["Jazz"])
        friend = json.loads(self.request("/api/overview", as_user="ana")[1])
        self.assertEqual(friend["me"], {"id": "ana", "name": "Ana", "is_owner": False})

    def test_playlist_detail_with_encoded_name(self):
        status, body = self.request("/api/playlists/Jazz")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["items"][0]["title"], "So What")
        self.assertEqual(self.request("/api/playlists/N%C3%A3o%20existe")[0], 404)

    def test_owner_adds_track_to_spotify_and_base_selection(self):
        status, body = self.request("/api/playlists/Jazz/items", {"uri": "spotify:track:2", "entry": "Bill Evans - Peace Piece"})
        self.assertEqual(status, 200, body)
        self.assertEqual(self.fake.added, [("pl-jazz", ["spotify:track:2"])])
        saved = json.loads((self.data / "playlists.json").read_text(encoding="utf-8"))
        self.assertIn("Bill Evans - Peace Piece", saved["playlists"][1]["tracks"])

    def test_friend_adds_only_to_own_copy(self):
        status, body = self.request("/api/playlists/Jazz/items", {"uri": "spotify:track:2", "entry": "X - Y"}, as_user="ana")
        self.assertEqual(status, 200, body)
        self.assertEqual(self.fake.added, [("pl-ana", ["spotify:track:2"])])
        saved = json.loads((self.data / "playlists.json").read_text(encoding="utf-8"))
        self.assertNotIn("X - Y", saved["playlists"][1]["tracks"])
        status, _ = self.request("/api/playlists/Tech/items", {"uri": "spotify:show:abc", "entry": "Data Hackers"}, as_user="ana")
        self.assertEqual(status, 403)

    def test_owner_adds_show_and_caches_its_id(self):
        status, _ = self.request("/api/playlists/Tech/items", {"uri": "spotify:show:abc", "entry": "Data Hackers"})
        self.assertEqual(status, 200)
        state = json.loads((self.data / "users" / "paulo" / "state.json").read_text(encoding="utf-8"))
        self.assertEqual(state["shows"]["Data Hackers"], "abc")

    def test_rejects_foreign_host_and_non_json_posts(self):
        self.assertEqual(self.request("/api/overview", headers={"Host": "evil.example:80"})[0], 403)
        status, _ = self.request("/api/player", {"action": "pause"}, headers={"Content-Type": "text/plain"})
        self.assertEqual(status, 415)

    def test_public_address_is_accepted_and_logs_in_through_it(self):
        status, _ = self.request("/api/overview", headers={"Host": "sala.example"})
        self.assertEqual(status, 200)
        app = self.server.app
        self.assertEqual(app.login_url("https://sala.example/callback").count("redirect_uri=https%3A%2F%2Fsala.example%2Fcallback"), 1)

    def test_tunnel_that_rewrites_host_still_counts_as_public(self):
        import http.client

        conn = http.client.HTTPConnection("127.0.0.1", self.server.server_address[1])
        conn.request("GET", "/login", headers={"X-Forwarded-Host": "sala.example"})
        response = conn.getresponse()
        self.assertEqual(response.status, 302)
        self.assertIn("redirect_uri=https%3A%2F%2Fsala.example%2Fcallback", response.getheader("Location"))
        conn.close()
        conn = http.client.HTTPConnection("127.0.0.1", self.server.server_address[1])
        conn.request("GET", "/login", headers={"X-Forwarded-Host": "evil.example"})
        self.assertEqual(conn.getresponse().status, 403)
        conn.close()

    def test_blocked_lists_are_per_person(self):
        from spotify_assistant.discovery import Find, Hunt

        ana = self.server.app.profile("ana")
        ana.hunt = Hunt("roulette", "Roleta", status="done", finds=[
            Find("spotify:track:1", "To Hell with the Devil", "Stryper", None, 1, artists=["Stryper"]),
            Find("spotify:track:2", "Shy Moon", "Caetano Veloso", None, 1, artists=["Caetano Veloso"]),
        ])
        status, body = self.request("/api/blocked", {"artist": "Stryper", "blocked": True}, as_user="ana")
        self.assertEqual(status, 200, body)
        self.assertEqual(json.loads(body)["artists"], ["Stryper"])
        self.assertEqual([f.uri for f in ana.hunt.finds], ["spotify:track:2"])  # some na hora
        self.assertIn("stryper", ana.blocked)
        self.assertEqual(json.loads(self.request("/api/blocked")[1])["artists"], [])  # o dono não foi afetado

        status, body = self.request("/api/blocked", {"artist": "stryper", "blocked": False}, as_user="ana")
        self.assertEqual(json.loads(body)["artists"], [])
        self.assertNotIn("stryper", ana.blocked)

    def test_logout_ends_the_session(self):
        status, _ = self.request("/api/logout", {}, as_user="ana")
        self.assertEqual(status, 200)
        self.assertEqual(self.request("/api/overview", as_user="ana")[0], 401)
        self.assertEqual(self.request("/api/overview")[0], 200)  # o dono continua dentro

    def test_uninvited_account_gets_an_explanation(self):
        app = self.server.app
        url = app.login_url("http://127.0.0.1:0/callback")
        state = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)["state"][0]
        with mock.patch.object(dashboard, "exchange_code", return_value={"access_token": "t"}), \
                mock.patch.object(dashboard.accounts, "register", side_effect=dashboard.accounts.NotInvited()):
            status, body = self.request(f"/callback?code=c&state={state}", as_user=None)
        self.assertEqual(status, 403)
        self.assertIn("User Management".encode(), body)
        self.assertIn(b"Paulo", body)

    def test_unknown_route(self):
        self.assertEqual(self.request("/api/nada")[0], 404)


class AccountsTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.data = Path(tmp.name)
        patches = [
            mock.patch.object(config, "DATA_DIR", self.data),
            mock.patch.object(config, "TOKEN_FILE", self.data / "token.json"),
            mock.patch.object(config, "STATE_FILE", self.data / "state.json"),
            mock.patch.object(config, "BLOCKED_FILE", self.data / "bloqueados.json"),
        ]
        for patcher in patches:
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_single_user_data_becomes_the_owner_profile(self):
        from spotify_assistant import accounts

        token = {"access_token": "x", "refresh_token": "y", "expires_at": 4_000_000_000, "scope": ""}
        (self.data / "token.json").write_text(json.dumps(token), encoding="utf-8")
        (self.data / "state.json").write_text(json.dumps({"playlists": {"Jazz": "pl"}}), encoding="utf-8")
        (self.data / "bloqueados.json").write_text(json.dumps({"artistas": ["X"]}), encoding="utf-8")
        with mock.patch.object(accounts.Spotify, "me", return_value={"id": "paulo", "display_name": "Nej"}):
            accounts.migrate_legacy(Settings("client", "http://127.0.0.1:0/callback"))
        owner = self.data / "users" / "paulo"
        self.assertEqual(config.owner_id(), "paulo")
        self.assertEqual(json.loads((owner / "state.json").read_text(encoding="utf-8")), {"playlists": {"Jazz": "pl"}})
        self.assertTrue((owner / "token.json").exists() and (owner / "bloqueados.json").exists())
        self.assertFalse((self.data / "token.json").exists())
        self.assertEqual(accounts.display_name("paulo"), "Nej")

    def test_sessions_survive_a_restart(self):
        from spotify_assistant import accounts

        token = accounts.Sessions().create("ana")
        self.assertEqual(accounts.Sessions().user(token), "ana")
        accounts.Sessions().end(token)
        self.assertIsNone(accounts.Sessions().user(token))

    def test_user_ids_cannot_escape_the_data_folder(self):
        for bad in ("../x", "a/b", "..", ".git", ""):
            with self.assertRaises(ValueError):
                config.user_paths(bad)


if __name__ == "__main__":
    unittest.main()
