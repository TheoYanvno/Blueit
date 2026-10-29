import io
import json
import tempfile
import unittest
import urllib.error
from email.message import Message
from pathlib import Path
from types import SimpleNamespace

from blueit.cli import cmd_fetch
from blueit.config import Config
from blueit.reddit import Credentials, MissingCredentials, Reddit, RedditError, load_env

FIX = Path(__file__).parent / "fixtures" / "listing.json"
LISTING = json.loads(FIX.read_text())


class FakeResponse(io.BytesIO):
    def __init__(self, body: dict, headers: dict | None = None):
        super().__init__(json.dumps(body).encode())
        self.headers = Message()
        for k, v in (headers or {}).items():
            self.headers[k] = str(v)


def http_error(url, code, headers=None):
    h = Message()
    for k, v in (headers or {}).items():
        h[k] = str(v)
    return urllib.error.HTTPError(url, code, "error", h, io.BytesIO(b"{}"))


class FakeReddit:
    """Plays Reddit's part: hands out a token, then answers listing requests from a script."""

    def __init__(self, script=None, token_life=3600):
        self.script = list(script or [])
        self.requests = []
        self.token_life = token_life
        self.tokens = 0

    def __call__(self, req, timeout):
        self.requests.append(req)
        if req.full_url.endswith("/api/v1/access_token"):
            self.tokens += 1
            return FakeResponse({"access_token": f"tok{self.tokens}", "expires_in": self.token_life})
        step = self.script.pop(0) if self.script else ("ok", LISTING, {})
        kind, payload, headers = step
        if kind == "error":
            raise http_error(req.full_url, payload, headers)
        return FakeResponse(payload, headers)


def client(fake, **kw):
    clock = kw.pop("clock", None) or (lambda: 1000.0)
    slept = []
    r = Reddit(Credentials("id", "secret", "anthony"), opener=fake, sleep=slept.append, clock=clock, **kw)
    return r, slept


class Credentials_(unittest.TestCase):
    def test_missing_credentials_explain_how_to_set_up(self):
        with self.assertRaises(MissingCredentials) as e:
            Credentials.from_env({})
        self.assertIn("reddit.com/prefs/apps", str(e.exception))

    def test_env_file_is_read_and_real_environment_wins(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / ".env"
            p.write_text("# comment\nREDDIT_CLIENT_ID=from-file\nREDDIT_CLIENT_SECRET='s3cret'\n")
            env = load_env(p, {"REDDIT_CLIENT_ID": "from-env"})
        self.assertEqual(env["REDDIT_CLIENT_ID"], "from-env")
        self.assertEqual(env["REDDIT_CLIENT_SECRET"], "s3cret")

    def test_user_agent_names_the_app_and_its_owner(self):
        self.assertRegex(Credentials("a", "b", "anthony").user_agent, r"^python:blueit:\d+\.\d+\.\d+ \(by /u/anthony\)$")


class Requests(unittest.TestCase):
    def test_signs_in_once_and_sends_the_token_and_user_agent(self):
        fake = FakeReddit()
        r, _ = client(fake)
        r.top("nosleep")
        r.top("LetsNotMeet")
        self.assertEqual(fake.tokens, 1, "the token is reused while it's valid")
        token_req, api_req = fake.requests[0], fake.requests[1]
        self.assertTrue(token_req.get_header("Authorization").startswith("Basic "))
        self.assertEqual(token_req.data, b"grant_type=client_credentials")
        self.assertEqual(api_req.get_header("Authorization"), "bearer tok1")
        self.assertIn("blueit", api_req.get_header("User-agent"))
        self.assertTrue(api_req.full_url.startswith("https://oauth.reddit.com/r/nosleep/top?"))

    def test_search_stays_in_the_subreddit(self):
        fake = FakeReddit()
        r, _ = client(fake)
        r.search("nosleep", "cabin in the woods", time_filter="year", limit=500)
        url = fake.requests[-1].full_url
        for part in ("/r/nosleep/search?", "q=cabin+in+the+woods", "restrict_sr=1", "t=year", "limit=100"):
            self.assertIn(part, url)

    def test_token_is_refreshed_when_it_expires(self):
        now = [1000.0]
        fake = FakeReddit(token_life=120)
        r, _ = client(fake, clock=lambda: now[0])
        r.top("nosleep")
        now[0] += 100      # within a minute of expiring
        r.top("nosleep")
        self.assertEqual(fake.tokens, 2)

    def test_retries_with_backoff_on_429_and_server_errors(self):
        fake = FakeReddit([("error", 429, {"Retry-After": 7}), ("error", 503, {}), ("ok", LISTING, {})])
        r, slept = client(fake)
        self.assertEqual(len(r.top("nosleep")["data"]["children"]), 5)
        self.assertEqual(slept, [7.0, 2.0], "Retry-After when Reddit sends it, otherwise doubling waits")

    def test_gives_up_with_a_clear_error(self):
        fake = FakeReddit([("error", 503, {})] * 5)
        r, _ = client(fake, retries=2)
        with self.assertRaises(RedditError):
            r.top("nosleep")
        fake = FakeReddit([("error", 404, {})])
        r, slept = client(fake)
        with self.assertRaises(RedditError):
            r.top("nosuchsub")
        self.assertEqual(slept, [], "a 404 isn't retried")

    def test_waits_when_the_rate_limit_runs_out(self):
        fake = FakeReddit([("ok", LISTING, {"X-Ratelimit-Remaining": 0, "X-Ratelimit-Reset": 42}), ("ok", LISTING, {})])
        r, slept = client(fake)
        r.top("nosleep")
        r.top("nosleep")
        self.assertEqual(slept, [42.0])

    def test_signs_in_again_after_a_401(self):
        fake = FakeReddit([("error", 401, {}), ("ok", LISTING, {})])
        r, _ = client(fake)
        r.top("nosleep")
        self.assertEqual(fake.tokens, 2)
        self.assertEqual(fake.requests[-1].get_header("Authorization"), "bearer tok2")


class Stories(unittest.TestCase):
    def test_returns_text_posts_above_the_minimum_score(self):
        r, _ = client(FakeReddit())
        stories = r.stories("nosleep", min_score=500)
        self.assertEqual([s.id for s in stories], ["a1", "a2", "a3"])

    def test_fetch_saves_listings_that_check_can_read(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = Config(subreddits=["nosleep", "LetsNotMeet"], min_score=100)
            r, _ = client(FakeReddit())
            args = SimpleNamespace(out=d, env="/nonexistent", library=str(Path(d) / "library.db"))
            self.assertEqual(cmd_fetch(args, cfg, reddit=r), 0)
            saved = json.loads((Path(d) / "nosleep.json").read_text())
            self.assertEqual(len(saved["data"]["children"]), 4, "a4 (score 50) is below the minimum")
            self.assertTrue((Path(d) / "LetsNotMeet.json").exists())

    def test_fetch_without_credentials_fails_politely(self):
        with tempfile.TemporaryDirectory() as d:
            args = SimpleNamespace(out=d, env=str(Path(d) / "missing.env"))
            import contextlib
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                code = cmd_fetch(args, Config())
        self.assertEqual(code, 2)
        self.assertIn("prefs/apps", err.getvalue())


if __name__ == "__main__":
    unittest.main()
