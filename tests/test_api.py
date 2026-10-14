import io
import unittest
from unittest import mock

from spotify_assistant import api


def fake_response(body: bytes):
    response = mock.MagicMock()
    response.__enter__.return_value = io.BytesIO(body)
    return response


class HttpRequestTest(unittest.TestCase):
    def request(self, body: bytes):
        with mock.patch.object(api.urllib.request, "urlopen", return_value=fake_response(body)):
            return api.http_request("POST", "https://api.spotify.com/v1/me/player/next")

    def test_json_body_is_parsed(self):
        self.assertEqual(self.request(b'{"snapshot_id": "x"}'), {"snapshot_id": "x"})

    def test_empty_body_is_none(self):
        self.assertIsNone(self.request(b""))
        self.assertIsNone(self.request(b"  \n"))

    def test_non_json_success_body_is_not_an_error(self):
        # This was the bug when clicking "next": a 200 with plain text crashed the panel.
        self.assertIsNone(self.request(b"ok"))


class RateGateTest(unittest.TestCase):
    def setUp(self):
        import tempfile
        from pathlib import Path

        from spotify_assistant import config

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        for name, value in {"DATA_DIR": Path(tmp.name), "SPOTIFY_PAUSES_FILE": Path(tmp.name) / "pausas.json"}.items():
            patcher = mock.patch.object(config, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = mock.patch.object(api, "gate", api._Gate())
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_endpoint_family(self):
        self.assertEqual(api.endpoint_family("https://api.spotify.com/v1/search?q=x"), "search")
        self.assertEqual(api.endpoint_family("/me/player/next"), "me/player")
        self.assertEqual(api.endpoint_family("/albums/1/tracks"), "albums")

    def test_long_429_pauses_only_that_family_without_touching_the_network(self):
        sp = api.Spotify(lambda: "token", "BR")
        too_many = api.SpotifyError(429, "limite", retry_after=70000, family="search")
        with mock.patch.object(api, "http_request", side_effect=too_many) as request:
            with self.assertRaises(api.SpotifyError):
                sp.search("x", "track")
            with self.assertRaises(api.SpotifyError) as again:
                sp.search("y", "track")
            self.assertEqual(request.call_count, 1)  # the second one never even left the PC
            self.assertEqual(again.exception.status, 429)
            self.assertGreater(again.exception.retry_after, 69000)
        with mock.patch.object(api, "http_request", return_value={"id": "me"}):
            self.assertEqual(sp.me(), {"id": "me"})  # everything else keeps working


if __name__ == "__main__":
    unittest.main()
