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
        # Foi o erro ao clicar em "próxima": 200 com texto solto derrubava o painel.
        self.assertIsNone(self.request(b"ok"))


if __name__ == "__main__":
    unittest.main()
