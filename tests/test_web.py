import http.client
import json
import tempfile
import threading
import unittest
from pathlib import Path

from blueit.categories import STORY_TYPES, subreddits_for
from blueit.config import Config
from blueit.library import Library
from blueit.reddit import MissingCredentials
from blueit.web import App, BadRequest, make_server

from .test_reddit import FakeReddit, client
from .test_series import listing, post, story

LONG = " ".join(["the hallway lights flickered once and then the footsteps stopped right outside"] * 200)  # 2,400 words


class Menus(unittest.TestCase):
    def test_every_kind_lists_its_subreddits_and_one_can_be_picked(self):
        for kind, v in STORY_TYPES.items():
            self.assertTrue(v["label"] and v["subreddits"], kind)
            self.assertEqual(subreddits_for(kind), v["subreddits"])
        self.assertEqual(subreddits_for("scary", "r/NOSLEEP"), ["nosleep"])
        with self.assertRaises(ValueError):
            subreddits_for("scary", "ProRevenge")          # a subreddit from another kind
        with self.assertRaises(ValueError):
            subreddits_for("cooking")


class Finding(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.db = Path(self.dir.name) / "library.db"
        self.calls = []

    def tearDown(self):
        self.dir.cleanup()

    def app(self, script):
        def factory():
            r, _ = client(FakeReddit(script))
            self.reddit = r
            return r
        return App(Config(), self.db, Path(self.dir.name) / "listings", reddit_factory=factory)

    def test_finds_stories_in_the_chosen_subreddit_with_the_chosen_settings(self):
        app = self.app([("ok", listing(post("a1", "The night ranger", 500), post("a2", "The long hallway", 600, body=LONG)), {})])
        out = app.find({"kind": "scary", "subreddit": "nosleep", "time": "week", "length": "medium", "minScore": 0, "limit": 10})
        self.assertTrue(out["ok"])
        self.assertEqual([s["id"] for s in out["stories"]], ["a2"], "the 480-word story is too short for medium")
        s = out["stories"][0]
        self.assertEqual((s["subreddit"], s["minutes"], s["status"]), ("nosleep", 16, "new"))
        req = [r for r in self.reddit_requests() if "/top" in r.full_url][0]
        self.assertIn("/r/nosleep/top", req.full_url)
        self.assertIn("t=week", req.full_url)
        self.assertIn("limit=10", req.full_url)

    def reddit_requests(self):
        return self.reddit.opener.requests

    def test_words_turn_it_into_a_search_and_all_places_of_a_kind_are_searched(self):
        script = [("ok", listing(post(f"r{i}", f"Story {i}", 100 + i, sub=sub)), {})
                  for i, sub in enumerate(STORY_TYPES["revenge"]["subreddits"])]
        app = self.app(script)
        out = app.find({"kind": "revenge", "words": "  neighbor   fence ", "minScore": 0})
        self.assertEqual(len(out["stories"]), len(STORY_TYPES["revenge"]["subreddits"]))
        urls = [r.full_url for r in self.reddit_requests() if "/search" in r.full_url]
        self.assertEqual(len(urls), 3)
        self.assertIn("q=neighbor+fence", urls[0])
        self.assertEqual(len(out["log"]), 3)

    def test_found_stories_are_saved_once_to_the_library(self):
        for _ in range(2):
            app = self.app([("ok", listing(post("a1", "The night ranger", 500)), {})])
            app.find({"kind": "scary", "subreddit": "nosleep", "minScore": 0})
        with Library(self.db) as lib:
            self.assertEqual([e.id for e in lib.find()], ["a1"])

    def test_choices_outside_the_menus_are_refused(self):
        app = self.app([])
        for bad in [{"kind": "cooking"}, {"kind": "scary", "time": "decade"}, {"kind": "scary", "length": "huge"},
                    {"kind": "scary", "minScore": "7"}, {"kind": "scary", "limit": "lots"}, {"kind": "scary", "subreddit": "tifu"}]:
            with self.assertRaises(BadRequest, msg=bad):
                app.find(bad)

    def test_missing_reddit_keys_explain_how_to_set_up(self):
        def factory():
            raise MissingCredentials()
        app = App(Config(), self.db, Path(self.dir.name), reddit_factory=factory)
        out = app.find({"kind": "scary"})
        self.assertFalse(out["ok"])
        self.assertIn("reddit.com/prefs/apps", out["error"])

    def test_library_filters_by_status_and_kind_and_marks_stories(self):
        with Library(self.db) as lib:
            lib.add(story("n1", "Cabin", 100))
            lib.add(story("p1", "Fence", 200, sub="ProRevenge"))
        app = self.app([])
        self.assertEqual({s["id"] for s in app.library({})["stories"]}, {"n1", "p1"})
        self.assertEqual([s["id"] for s in app.library({"kind": "revenge"})["stories"]], ["p1"])
        app.mark({"id": "n1", "status": "narrated"})
        self.assertEqual([s["id"] for s in app.library({"status": "narrated"})["stories"]], ["n1"])
        self.assertEqual(app.library({})["counts"], {"new": 1, "narrated": 1})
        with self.assertRaises(BadRequest):
            app.mark({"id": "nope"})


class Server(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        r, _ = client(FakeReddit([("ok", listing(post("a1", "The night ranger", 500)), {})]))
        app = App(Config(), Path(self.dir.name) / "library.db", Path(self.dir.name), reddit_factory=lambda: r)
        self.server = make_server(app, port=0)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.dir.cleanup()

    def request(self, method, path, body=None, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        h = {"Host": f"127.0.0.1:{self.port}", **(headers or {})}
        conn.request(method, path, body=body, headers=h)
        res = conn.getresponse()
        data = res.read()
        conn.close()
        return res.status, res.getheader("Content-Type"), data

    def test_page_is_the_react_app_and_its_assets_are_served(self):
        status, kind, body = self.request("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn("text/html", kind)
        self.assertIn('<script src="/assets/app.js">', body.decode())
        status, kind, body = self.request("GET", "/assets/app.js")
        self.assertEqual((status, kind.split(";")[0]), (200, "text/javascript"))
        self.assertIn(b"/api/options", body)
        for bad in ["/assets/../web.py", "/assets/nope.js"]:
            self.assertEqual(self.request("GET", bad)[0], 404, bad)

    def test_the_old_page_is_used_when_the_app_is_not_built(self):
        from unittest import mock
        import blueit.web as web
        with mock.patch.object(web, "STATIC", Path(self.dir.name) / "no-build"):
            status, _, body = self.request("GET", "/")
        self.assertEqual(status, 200)
        for menu in ["kind", "subreddit", "time", "length", "minScore", "limit"]:
            self.assertIn(f'<select id="{menu}"', body.decode())

    def test_options_and_a_search_over_http(self):
        status, _, body = self.request("GET", "/api/options")
        opts = json.loads(body)
        self.assertEqual(status, 200)
        self.assertEqual([k["id"] for k in opts["kinds"]], list(STORY_TYPES))
        status, _, body = self.request("POST", "/api/find", json.dumps({"kind": "scary", "subreddit": "nosleep", "minScore": 0}),
                                       {"Content-Type": "application/json"})
        self.assertEqual(status, 200)
        self.assertEqual([s["id"] for s in json.loads(body)["stories"]], ["a1"])

    def test_requests_for_other_hosts_and_non_json_posts_are_refused(self):
        self.assertEqual(self.request("GET", "/api/options", headers={"Host": "evil.example"})[0], 403)
        self.assertEqual(self.request("POST", "/api/find", "kind=scary", {"Content-Type": "application/x-www-form-urlencoded"})[0], 415)
        self.assertEqual(self.request("POST", "/api/find", json.dumps({"kind": "cooking"}), {"Content-Type": "application/json"})[0], 400)
        self.assertEqual(self.request("GET", "/nope")[0], 404)


if __name__ == "__main__":
    unittest.main()


@unittest.skipUnless(__import__("shutil").which("ffmpeg"), "FFmpeg isn't installed")
class MakeVideo(unittest.TestCase):
    def test_make_video_narrates_and_makes_the_videos_in_the_background_one_at_a_time(self):
        import subprocess
        from blueit.narrate import SilentVoice
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            (d / "images").mkdir()
            subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=maroon:s=320x240", "-frames:v", "1",
                            str(d / "images" / "a.png")], check=True)
            cfg = Config(output=d / "out", images=d / "images", video_size="240x426")
            with Library(d / "library.db") as lib:
                lib.add(story("w1", "The Visitor", 500, body="Someone knocked twice. " * 20))
            app = App(cfg, d / "library.db", d, voice_factory=SilentVoice)
            self.assertEqual(app.status(), {"state": "idle"})
            with self.assertRaises(BadRequest):
                app.make({"id": "nope"})
            job = app.make({"id": "w1"}, wait=True)
            self.assertEqual(job["state"], "done", job)
            self.assertGreaterEqual(job["parts"], 1)
            self.assertTrue((d / "out" / "w1-the-visitor" / "full.mp4").exists())
            self.assertEqual(app.library({"status": "narrated"})["counts"]["narrated"], 1)
            app.job = {"state": "running", "title": "Another"}
            with self.assertRaisesRegex(BadRequest, "Already making"):
                app.make({"id": "w1"})

    def test_a_failure_is_shown_not_raised(self):
        from blueit.narrate import SilentVoice
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            cfg = Config(output=d / "out", images=d / "no-pictures")
            with Library(d / "library.db") as lib:
                lib.add(story("w2", "No Pictures", 500, body="Quiet night. " * 20))
            job = App(cfg, d / "library.db", d, voice_factory=SilentVoice).make({"id": "w2"}, wait=True)
            self.assertEqual(job["state"], "error")
            self.assertIn("No pictures found", job["error"])


class Ranges(unittest.TestCase):
    """Range requests let the video player seek without downloading the whole file first."""

    def test_byte_ranges(self):
        from blueit.web import byte_range
        self.assertEqual(byte_range("bytes=0-99", 1000), (0, 99))
        self.assertEqual(byte_range("bytes=500-", 1000), (500, 999))
        self.assertEqual(byte_range("bytes=-100", 1000), (900, 999))
        self.assertEqual(byte_range("bytes=900-5000", 1000), (900, 999))
        for bad in (None, "", "items=0-1", "bytes=5-2", "bytes=abc-", "bytes=0-1,5-9", "bytes=2000-"):
            self.assertIsNone(byte_range(bad, 1000), bad)


class ReactApi(unittest.TestCase):
    """The endpoints the React interface uses: one story in full, its files, the setup checks and settings."""

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        d = Path(self.dir.name)
        self.cfg = Config(output=d / "out", images=d / "images")
        with Library(d / "library.db") as lib:
            lib.add(story("s1", "The Visitor", 500, body="Someone knocked twice. " * 20))
        self.app = App(self.cfg, d / "library.db", d)

    def tearDown(self):
        self.dir.cleanup()

    def test_story_shows_the_text_and_lists_made_files(self):
        data = self.app.story({"id": "s1"})
        self.assertEqual(data["story"]["title"], "The Visitor")
        self.assertIn("knocked twice", data["story"]["body"])
        self.assertEqual((data["files"], data["full"], data["parts"]), ([], None, []))
        folder = self.cfg.output / data["folder"]
        folder.mkdir(parents=True)
        for name in ("full.mp4", "part-01.mp4", "part-02.mp4", "captions.srt", "notes.exe"):
            (folder / name).write_bytes(b"x")
        data = self.app.story({"id": "s1"})
        self.assertEqual(data["full"], "full.mp4")
        self.assertEqual(data["parts"], ["part-01.mp4", "part-02.mp4"])
        self.assertNotIn("notes.exe", data["files"])
        with self.assertRaises(BadRequest):
            self.app.story({"id": "missing"})

    def test_media_paths_stay_inside_a_story_folder(self):
        folder = self.app.story({"id": "s1"})["folder"]
        (self.cfg.output / folder).mkdir(parents=True)
        (self.cfg.output / folder / "full.mp4").write_bytes(b"x")
        self.assertTrue(self.app.media_path(folder, "full.mp4").is_file())
        for bad in [("..", "library.db"), (folder, "../../library.db"), (folder, "nope.mp4"), (folder, "script.py")]:
            with self.assertRaises(BadRequest, msg=bad):
                self.app.media_path(*bad)

    def test_doctor_and_settings_come_back_as_json(self):
        checks = self.app.doctor()
        self.assertIn("ok", checks)
        self.assertTrue(all({"name", "ok", "detail"} <= set(c) for c in checks["checks"]))
        self.assertEqual(self.app.settings()["settings"]["output"], str(self.cfg.output))
