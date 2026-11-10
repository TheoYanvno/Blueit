import json
import tempfile
import unittest
import urllib.parse
from pathlib import Path
from unittest import mock

from blueit import youtube
from blueit.youtube import Client, YouTubeError, access_token, auth_url, exchange_code, upload, video_details


class FakeGoogle:
    """Answers token and upload requests like Google does, and records what was sent."""

    def __init__(self, keep_per_chunk=None):
        self.calls = []
        self.received = b""
        self.keep_per_chunk = keep_per_chunk     # how many bytes to "keep" from each chunk (None: all)

    def __call__(self, req, timeout=120):
        self.calls.append(req)
        url = req.full_url
        if url == youtube.TOKEN_URL:
            fields = dict(urllib.parse.parse_qsl(req.data.decode()))
            if fields.get("code") == "bad" or fields.get("refresh_token") == "revoked":
                return 400, {}, json.dumps({"error": "invalid_grant", "error_description": "Bad Request"}).encode()
            body = {"access_token": f"tok-{len(self.calls)}", "expires_in": 3600}
            if fields["grant_type"] == "authorization_code":
                body["refresh_token"] = "refresh-1"
            return 200, {}, json.dumps(body).encode()
        if url == youtube.UPLOAD_URL:
            return 200, {"Location": "https://upload.example/session-1"}, b""
        if url == "https://upload.example/session-1":
            chunk = req.data if self.keep_per_chunk is None else req.data[: self.keep_per_chunk]
            self.received += chunk
            total = int(req.headers["Content-range"].split("/")[1])
            if len(self.received) >= total:
                return 200, {}, json.dumps({"id": "vid123"}).encode()
            return 308, {"Range": f"bytes=0-{len(self.received) - 1}"}, b""
        return 404, {}, b"{}"


class YouTubeTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.d = Path(self.dir.name)
        self.client = Client("id-1", "secret-1")

    def tearDown(self):
        self.dir.cleanup()

    def test_client_file_is_read_and_missing_one_explains_what_to_do(self):
        p = self.d / "youtube_client.json"
        with self.assertRaisesRegex(YouTubeError, "Desktop OAuth client"):
            Client.load(p)
        p.write_text(json.dumps({"installed": {"client_id": "abc", "client_secret": "xyz"}}))
        self.assertEqual(Client.load(p), Client("abc", "xyz"))
        p.write_text("not json")
        with self.assertRaises(YouTubeError):
            Client.load(p)

    def test_sign_in_link_asks_only_for_uploads(self):
        url, state = auth_url(self.client, "http://127.0.0.1:8642/oauth/youtube")
        q = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(url).query))
        self.assertEqual(q["scope"], youtube.SCOPE)
        self.assertEqual(q["state"], state)
        self.assertEqual(q["access_type"], "offline")

    def test_code_exchange_saves_a_token_that_is_refreshed_when_old(self):
        fake, token_path, clock = FakeGoogle(), self.d / "youtube_token.json", [1000.0]
        exchange_code(self.client, "good", "http://127.0.0.1/cb", token_path, http=fake, now=lambda: clock[0])
        first = access_token(self.client, token_path, http=fake, now=lambda: clock[0])
        self.assertEqual(first, "tok-1")
        self.assertEqual(len(fake.calls), 1)                      # still fresh: no new request
        clock[0] += 4000
        second = access_token(self.client, token_path, http=fake, now=lambda: clock[0])
        self.assertNotEqual(second, first)
        self.assertEqual(json.loads(token_path.read_text())["refresh_token"], "refresh-1")

    def test_errors_are_clear(self):
        fake = FakeGoogle()
        with self.assertRaisesRegex(YouTubeError, "Bad Request"):
            exchange_code(self.client, "bad", "http://127.0.0.1/cb", self.d / "t.json", http=fake)
        with self.assertRaisesRegex(YouTubeError, "Not connected"):
            access_token(self.client, self.d / "none.json", http=fake)

    def test_video_details_cut_long_titles_and_tag_shorts(self):
        d = video_details("A" * 150, "writer", "nosleep", "https://reddit.com/x", upright=True, part="Part 2")
        self.assertLessEqual(len(d["snippet"]["title"]), 100)
        self.assertTrue(d["snippet"]["title"].endswith("(Part 2) #Shorts"))
        self.assertIn("u/writer", d["snippet"]["description"])
        self.assertEqual(d["status"]["privacyStatus"], "private")
        full = video_details("The <Visitor>", "w", "nosleep", "u", upright=True)
        self.assertEqual(full["snippet"]["title"], "The Visitor")
        with self.assertRaises(YouTubeError):
            video_details("t", "a", "s", "u", upright=False, privacy="everyone")

    def test_resumable_upload_sends_every_byte_and_resumes_where_youtube_says(self):
        video = self.d / "full.mp4"
        video.write_bytes(bytes(range(256)) * 100)                # 25,600 bytes
        with mock.patch.object(youtube, "CHUNK", 10_000):
            fake = FakeGoogle(keep_per_chunk=6_000)               # YouTube keeps only part of each chunk
            seen = []
            vid = upload(video, {"snippet": {}}, "tok", http=fake, progress=lambda a, b: seen.append(a))
        self.assertEqual(vid, "vid123")
        self.assertEqual(fake.received, video.read_bytes())
        self.assertEqual(seen[-1], 25_600)
        self.assertEqual(fake.calls[0].headers["Authorization"], "Bearer tok")

    def test_a_refused_upload_says_why(self):
        def refuse(req, timeout=120):
            return 403, {}, json.dumps({"error": {"message": "quota exceeded"}}).encode()
        video = self.d / "full.mp4"
        video.write_bytes(b"x")
        with self.assertRaisesRegex(YouTubeError, "quota exceeded"):
            upload(video, {}, "tok", http=refuse)


if __name__ == "__main__":
    unittest.main()
