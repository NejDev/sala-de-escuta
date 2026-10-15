import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from unittest import mock

from spotify_assistant import auth, config, dashboard, favorites, i18n
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
        self.created = []
        self.replaced = []

    def me(self):
        return {"id": "paulo", "display_name": "Nej"}

    def my_playlists(self):
        yield {"id": "pl-jazz", "name": "Jazz", "uri": "spotify:playlist:pl-jazz",
               "images": [{"url": "mosaic", "width": None}], "items": {"total": 1}, "owner": {"id": "paulo"}}
        yield {"id": "anamix", "name": "Mix da Ana", "uri": "spotify:playlist:anamix", "images": [],
               "items": {"total": 3}, "owner": {"id": "ana"}, "description": "S&#x27;ó as boas"}
        yield {"id": "seguida", "name": "Top Brasil", "uri": "spotify:playlist:seguida", "images": [],
               "items": {"total": 50}, "owner": {"id": "spotify"}}
        for number, (name, _) in enumerate(self.created, start=1):
            yield {"id": f"new{number}", "name": name, "uri": f"spotify:playlist:new{number}", "images": [],
                   "items": {"total": 0}, "owner": {"id": "paulo"}}

    def playlist_items(self, playlist_id):
        return [TRACK]

    def add_items(self, playlist_id, uris):
        self.added.append((playlist_id, uris))

    def set_repeat(self, mode):
        self.repeat = mode

    def save_to_library(self, uris):
        self.library = getattr(self, "library", set()) | set(uris)

    def remove_from_library(self, uris):
        self.library = getattr(self, "library", set()) - set(uris)

    def create_playlist(self, name, description, public):
        self.created.append((name, description))
        number = len(self.created)
        return {"id": f"new{number}", "uri": f"spotify:playlist:new{number}"}

    def replace_items(self, playlist_id, uris):
        self.replaced.append((playlist_id, uris))

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
    def setUp(self):
        i18n.use("pt")
        self.addCleanup(i18n.use, i18n.DEFAULT)

    def test_in_english_too(self):
        from spotify_assistant.api import SpotifyError

        i18n.use("en")
        message = dashboard.spotify_message(SpotifyError(429, "x", retry_after=3600, family="search"))
        self.assertRegex(message, r"paused this app's searches.* around \d{1,2}:\d\d [AP]M (today|tomorrow)\.")

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
    """A real server with two people: the owner (paulo) and a friend (ana)."""

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
            (folder / "profile.json").write_text(json.dumps({"name": user_id.title()}), encoding="utf-8")
        (data / "owner.txt").write_text("paulo", encoding="utf-8")
        patches = [
            mock.patch.object(config, "PLAYLISTS_FILE", data / "playlists.json"),
            mock.patch.object(config, "DATA_DIR", data),
            # Unaffected by real Spotify pauses recorded on this machine.
            mock.patch.object(dashboard.gate, "remaining", return_value=0),
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
            # The panel's text is checked in Portuguese; test_language_choice covers English.
            headers.setdefault("Cookie", f"sala={self.cookies[as_user]}; lang=pt")
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
        self.assertEqual(data["playlists"][0]["uri"], None)  # not created yet
        self.assertEqual(data["playlists"][2]["sources"], ["Jazz"])
        # The owner's curated playlists are favorites: the podcasts weekly, the rest monthly.
        self.assertEqual([p["favorite"]["every"] for p in data["playlists"]], ["weekly", "monthly", "monthly"])
        friend = json.loads(self.request("/api/overview", as_user="ana")[1])
        self.assertEqual(friend["me"], {"id": "ana", "name": "Ana", "is_owner": False})

    def test_bar_has_only_favorites(self):
        # A friend without favorites: nothing from the owner's shelf, and her ordinary playlists stay off the bar.
        friend = json.loads(self.request("/api/overview", as_user="ana")[1])
        self.assertEqual(friend["playlists"], [])
        owner = json.loads(self.request("/api/overview")[1])
        self.assertEqual([p["name"] for p in owner["playlists"]], ["Tech", "Jazz", "Mix"])

    def discovery_for(self, user_id):
        from spotify_assistant.discovery import Find, Hunt

        hunt = Hunt("roulette", "Roleta", status="done", color=None, finds=[
            Find("spotify:track:7", "Shy Moon", "Caetano Veloso", "art", 1000, artists=["Caetano Veloso"]),
            Find("spotify:track:8", "Pullopantti", "Slim Mill", None, 2000, artists=["Slim Mill"]),
        ])
        hunt.recipe = {"kind": "roulette", "genre": "zamrock", "min_fans": None, "max_fans": None}
        self.server.app.profile(user_id).hunt = hunt
        return hunt

    def make_favorite(self, user_id="ana", name="Roleta da Ana", every="weekly"):
        self.discovery_for(user_id)
        body = {"name": name, "uris": ["spotify:track:7", "spotify:track:8"], "every": every}
        return self.post("/api/playlists/new", body, as_user=user_id)

    def test_a_playlist_from_a_discovery_can_update_itself(self):
        status, data = self.make_favorite()
        self.assertEqual(status, 200, data)
        self.assertTrue(data["favorite"])
        self.assertIn("se atualiza toda semana", data["message"])
        fav = favorites.load("ana")[0]
        self.assertEqual((fav["kind"], fav["playlist_id"], fav["every"], fav["color"]),
                         ("discovery", "new1", "weekly", "#F2C14E"))
        self.assertEqual(fav["recipe"]["genre"], "zamrock")
        bar = json.loads(self.request("/api/overview", as_user="ana")[1])["playlists"]
        self.assertEqual([(p["key"], p["kind"], p["name"]) for p in bar], [(f"fav:{fav['id']}", "favorite", "Roleta da Ana")])
        self.assertEqual(self.request(f"/api/playlists/fav%3A{fav['id']}", as_user="ana")[0], 200)
        # The songs saved show up among the recent finds on the home screen.
        recent = json.loads(self.request("/api/recent", as_user="ana")[1])["finds"]
        self.assertEqual([(f["uri"], f["playlist"]) for f in recent][:1], [("spotify:track:7", "Roleta da Ana")])

    def test_updating_by_itself_needs_a_whole_discovery(self):
        body = {"name": "Solta", "uris": ["spotify:track:7"], "every": "weekly"}
        self.assertEqual(self.post("/api/playlists/new", body, as_user="ana")[0], 400)  # no discovery on screen
        self.discovery_for("ana")
        self.assertEqual(self.post("/api/playlists/new", {**body, "every": "hourly"}, as_user="ana")[0], 400)
        self.assertEqual(self.post("/api/playlists/new", {**body, "uris": ["spotify:track:99"]}, as_user="ana")[0], 400)
        self.assertEqual(favorites.load("ana"), [])

    def test_favorites_have_a_limit(self):
        with mock.patch.object(favorites, "MAX_FAVORITES", 1):
            self.assertEqual(self.make_favorite(name="Uma")[0], 200)
            status, data = self.make_favorite(name="Outra")
        self.assertEqual(status, 409, data)

    def test_frequency_and_removal(self):
        self.make_favorite()
        fav_id = favorites.load("ana")[0]["id"]
        status, data = self.post(f"/api/favorites/{fav_id}", {"every": "daily"}, as_user="ana")
        self.assertEqual((status, data["every"]), (200, "daily"))
        self.assertEqual(self.post(f"/api/favorites/{fav_id}", {"every": "hourly"}, as_user="ana")[0], 400)
        self.assertEqual(self.post(f"/api/favorites/{fav_id}", {"every": "daily"})[0], 404)  # not the owner's
        self.assertEqual(self.post(f"/api/favorites/{fav_id}/remove", {}, as_user="ana")[0], 200)
        self.assertEqual(favorites.load("ana"), [])
        curated = json.loads(self.request("/api/overview")[1])["playlists"][0]["favorite"]["id"]
        self.assertEqual(self.post(f"/api/favorites/{curated}/remove", {})[0], 409)

    def test_scheduler_rebuilds_the_most_overdue_favorite_with_its_recipe(self):
        from spotify_assistant.discovery import Find, Hunt

        self.make_favorite()
        favorites.change("ana", lambda items: items[0].update(last_run=1))  # long overdue
        asked = []

        def fake_hunt_task(app, user, sp, recipe, rng):
            asked.append((user.id, recipe["genre"]))
            hunt = Hunt("roulette", "Roleta")
            return hunt, lambda: hunt.finds.append(Find("spotify:track:9", "Nova", "X", None, 1))

        self.fake.replaced.clear()
        app = self.server.app
        with mock.patch.object(dashboard.App, "_hunt_task", fake_hunt_task):
            with mock.patch.object(dashboard.gate, "remaining", return_value=3600):
                self.assertIsNone(app.run_due())  # Spotify pause: waits
            fav_id = app.run_due()
            self.assertIsNone(app.run_due())  # nothing else is due
        self.assertEqual(asked, [("ana", "zamrock")])
        self.assertEqual(self.fake.replaced, [("new1", ["spotify:track:9"])])
        fav = favorites.load("ana")[0]
        self.assertEqual((fav["id"], fav["status"]), (fav_id, "ok"))
        self.assertGreater(fav["last_run"], 0)

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

    def test_friend_uses_own_playlist_and_cannot_touch_the_owner_shelf(self):
        status, body = self.request("/api/playlists/id%3Aanamix", as_user="ana")
        self.assertEqual(status, 200, body)
        status, body = self.request("/api/playlists/id%3Aanamix/items", {"uri": "spotify:track:2", "entry": "X - Y"}, as_user="ana")
        self.assertEqual(status, 200, body)
        self.assertEqual(self.fake.added, [("anamix", ["spotify:track:2"])])
        # The owner's curated shelf doesn't exist for her: she can't view, edit, or build it.
        self.assertEqual(self.request("/api/playlists/Jazz", as_user="ana")[0], 404)
        self.assertEqual(self.request("/api/playlists/Jazz/items", {"uri": "spotify:track:2", "entry": "X - Y"}, as_user="ana")[0], 404)
        self.assertEqual(self.request("/api/jobs", {"playlist": "Jazz"}, as_user="ana")[0], 404)
        saved = json.loads((self.data / "playlists.json").read_text(encoding="utf-8"))
        self.assertNotIn("X - Y", saved["playlists"][1]["tracks"])
        self.assertEqual(self.request("/api/playlists/id%3A..%2Fx", as_user="ana")[0], 404)

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
        self.assertEqual([f.uri for f in ana.hunt.finds], ["spotify:track:2"])  # gone right away
        self.assertIn("stryper", ana.blocked)
        self.assertEqual(json.loads(self.request("/api/blocked")[1])["artists"], [])  # the owner is unaffected

        status, body = self.request("/api/blocked", {"artist": "stryper", "blocked": False}, as_user="ana")
        self.assertEqual(json.loads(body)["artists"], [])
        self.assertNotIn("stryper", ana.blocked)

    def test_logout_ends_the_session(self):
        status, _ = self.request("/api/logout", {}, as_user="ana")
        self.assertEqual(status, 200)
        self.assertEqual(self.request("/api/overview", as_user="ana")[0], 401)
        self.assertEqual(self.request("/api/overview")[0], 200)  # the owner stays logged in

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

    def test_discovery_filters_are_validated(self):
        def start(body):
            return self.request("/api/hunts", body)[0]

        # Doesn't run the real search (patching threading.Thread would take down the test server itself).
        with mock.patch.object(dashboard.App, "_run_hunt", staticmethod(lambda *args: None)):
            self.assertEqual(start({"kind": "news", "genre": ""}), 400)
            self.assertEqual(start({"kind": "news", "genre": "k-pop", "days": 3}), 400)
            self.assertEqual(start({"kind": "roulette", "min_fans": 5000, "max_fans": 1000}), 400)
            self.assertEqual(start({"kind": "roulette", "min_fans": "muito"}), 400)
            self.assertEqual(start({"kind": "news", "genre": "gospel"}), 400)
            self.assertEqual(start({"kind": "news", "genre": "k-pop", "days": 30, "min_fans": 1000}), 200)
            self.assertEqual(start({"kind": "roulette", "genre": "k-pop", "max_fans": 100000}), 200)
        hunt = self.server.app.profile("paulo").hunt
        self.assertEqual(hunt.label, "Roleta: k-pop")

    def test_discoveries_refuse_right_away_while_search_is_paused(self):
        with mock.patch.object(dashboard.gate, "remaining", return_value=3600):
            status, body = self.request("/api/hunts", {"kind": "roulette"})
        self.assertEqual(status, 429)
        self.assertIn("pausou as buscas", json.loads(body)["error"])

    def test_unknown_route(self):
        self.assertEqual(self.request("/api/nada")[0], 404)

    def post(self, path, body, as_user="paulo"):
        status, raw = self.request(path, body, as_user=as_user)
        return status, json.loads(raw)

    def test_heart_saves_to_the_spotify_library(self):
        status, data = self.post("/api/player", {"action": "like", "uri": "spotify:track:1", "value": True})
        self.assertEqual((status, data["message"]), (200, "Salva nas suas Músicas Curtidas."))
        self.assertEqual(self.fake.library, {"spotify:track:1"})
        status, data = self.post("/api/player", {"action": "like", "uri": "spotify:episode:9", "value": True})
        self.assertEqual(data["message"], "Salvo nos seus episódios.")
        self.post("/api/player", {"action": "like", "uri": "spotify:track:1", "value": False})
        self.assertEqual(self.fake.library, {"spotify:episode:9"})
        self.assertEqual(self.post("/api/player", {"action": "like", "uri": "spotify:album:2", "value": True})[0], 400)

    def test_player_keeps_working_without_the_library_permission(self):
        token = {"scope": auth.PLAYER_SCOPES + " playlist-read-private", "access_token": "x", "refresh_token": "y",
                 "expires_at": 4_000_000_000}
        (self.data / "users" / "ana" / "token.json").write_text(json.dumps(token), encoding="utf-8")
        self.assertTrue(json.loads(self.request("/api/overview", as_user="ana")[1])["player_ready"])
        self.assertEqual(self.post("/api/player", {"action": "repeat", "value": "off"}, as_user="ana")[0], 200)
        status, data = self.post("/api/player", {"action": "like", "uri": "spotify:track:1", "value": True}, as_user="ana")
        self.assertEqual((status, data.get("scope")), (403, True))

    def test_repeat_takes_only_spotify_modes(self):
        self.assertEqual(self.request("/api/player", {"action": "repeat", "value": "track"})[0], 200)
        self.assertEqual(self.fake.repeat, "track")
        self.assertEqual(self.request("/api/player", {"action": "repeat", "value": "always"})[0], 400)

    def test_my_playlists_are_only_the_ones_you_own(self):
        status, raw = self.request("/api/my-playlists", as_user="ana")
        data = json.loads(raw)
        self.assertEqual(status, 200)
        self.assertEqual([p["id"] for p in data["playlists"]], ["anamix"])
        self.assertEqual(data["finds"], "Achados da Sala")

    def test_create_playlist_from_a_selection(self):
        uris = ["spotify:track:1", "spotify:track:2", "spotify:track:1", "spotify:episode:9"]
        status, data = self.post("/api/playlists/new", {"name": "  Minha   seleção ", "uris": uris})
        self.assertEqual(status, 200)
        self.assertEqual(self.fake.created[0][0], "Minha seleção")
        self.assertEqual(self.fake.replaced, [("new1", ["spotify:track:1", "spotify:track:2"])])
        self.assertEqual(data["message"], "Playlist Minha seleção criada com 2 músicas.")

    def test_same_name_asks_before_replacing(self):
        body = {"name": "Mix da Ana", "uris": ["spotify:track:5"]}
        status, data = self.post("/api/playlists/new", body, as_user="ana")
        self.assertEqual((status, data.get("exists")), (409, True))
        self.assertEqual(self.fake.replaced, [])
        status, data = self.post("/api/playlists/new", {**body, "replace": True}, as_user="ana")
        self.assertEqual(status, 200)
        self.assertEqual(self.fake.replaced, [("anamix", ["spotify:track:5"])])
        self.assertEqual(self.fake.created, [])

    def test_curated_names_stay_with_the_curation(self):
        status, _ = self.post("/api/playlists/new", {"name": "Jazz", "uris": ["spotify:track:5"]})
        self.assertEqual(status, 409)
        self.assertEqual(self.fake.created, [])

    def test_bad_selections_are_refused(self):
        self.assertEqual(self.post("/api/playlists/new", {"name": "x", "uris": ["javascript:alert(1)"]})[0], 400)
        self.assertEqual(self.post("/api/playlists/new", {"name": " ", "uris": ["spotify:track:1"]})[0], 400)
        self.assertEqual(self.post("/api/playlists/add", {"playlist": "pl-jazz", "uris": []})[0], 400)

    def test_add_skips_songs_already_there(self):
        status, data = self.post("/api/playlists/add", {"playlist": "pl-jazz", "uris": ["spotify:track:1", "spotify:track:2"]})
        self.assertEqual(status, 200)
        self.assertEqual(self.fake.added, [("pl-jazz", ["spotify:track:2"])])
        self.assertEqual(data["message"], "1 música adicionada a Jazz. 1 já estava lá.")

    def test_only_your_own_playlists_take_songs(self):
        body = {"playlist": "anamix", "uris": ["spotify:track:2"]}
        self.assertEqual(self.post("/api/playlists/add", body)[0], 403)
        self.assertEqual(self.post("/api/playlists/add", {**body, "playlist": "seguida"}, as_user="ana")[0], 403)
        self.assertEqual(self.post("/api/playlists/add", {**body, "playlist": "../x"})[0], 403)
        self.assertEqual(self.fake.added, [])

    def test_finds_playlist_is_created_once(self):
        body = {"playlist": "finds", "uris": ["spotify:track:2"]}
        self.assertEqual(self.post("/api/playlists/add", body)[0], 200)
        self.assertEqual(self.post("/api/playlists/add", body)[0], 200)
        self.assertEqual([name for name, _ in self.fake.created], ["Achados da Sala"])
        state = json.loads((self.data / "users" / "paulo" / "state.json").read_text(encoding="utf-8"))
        self.assertEqual(state["playlists"]["_finds"], "new1")

    def test_sensations_come_in_the_chosen_language(self):
        status, raw = self.request("/api/sensations", headers={"Cookie": "lang=en"}, as_user=None)
        names = {s["id"]: s["name"] for s in json.loads(raw)["sensations"]}
        self.assertEqual(names["deep-focus"], "Deep focus")
        status, raw = self.request("/api/sensations")
        names = {s["id"]: s["name"] for s in json.loads(raw)["sensations"]}
        self.assertEqual(names["deep-focus"], "Foco profundo")


    def test_language_choice(self):
        """The lang cookie wins; without it, the browser's Accept-Language; otherwise English."""

        session = f"sala={self.cookies['paulo']}"

        def error(headers):
            return json.loads(self.request("/api/nada", headers=headers, as_user=None)[1])["error"]

        self.assertEqual(error({"Cookie": f"{session}; lang=pt"}), "Endereço não encontrado.")
        self.assertEqual(error({"Cookie": f"{session}; lang=en", "Accept-Language": "pt-BR"}), "Address not found.")
        self.assertEqual(error({"Cookie": session, "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8"}),
                         "Endereço não encontrado.")
        self.assertEqual(error({"Cookie": session, "Accept-Language": "fr-FR"}), "Address not found.")
        self.assertEqual(error({"Accept-Language": "pt-BR"}), "Entre com o seu Spotify para continuar.")


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
        self.assertTrue((owner / "token.json").exists() and (owner / "blocked.json").exists())
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
