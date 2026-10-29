import contextlib
import io
import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from blueit.cli import cmd_fetch, main
from blueit.config import Config
from blueit.library import Library

from .test_reddit import FakeReddit, client
from .test_series import listing, post, story

WHEN = datetime(2026, 10, 29, 12, 0, tzinfo=timezone.utc)


class Saving(unittest.TestCase):
    def setUp(self):
        self.lib = Library(":memory:")

    def tearDown(self):
        self.lib.close()

    def test_a_story_is_stored_once_by_its_id(self):
        s = story("x1", "The Lighthouse", 100)
        self.assertTrue(self.lib.add(s, WHEN))
        self.assertFalse(self.lib.add(s, WHEN))
        self.assertEqual(len(self.lib.find()), 1)
        e = self.lib.get("x1")
        self.assertEqual((e.title, e.author, e.subreddit, e.status), ("The Lighthouse", "writer_one", "nosleep", "new"))
        self.assertEqual(e.words, s.words)
        self.assertEqual(e.added_at, "2026-10-29T12:00:00+00:00")

    def test_fetching_again_refreshes_the_story_but_keeps_its_status(self):
        s = story("x1", "The Lighthouse", 100)
        self.lib.add(s, WHEN)
        self.lib.mark_narrated("x1", WHEN)
        self.lib.add(replace(s, score=5000, title="The Lighthouse (edited)"))
        e = self.lib.get("x1")
        self.assertEqual((e.score, e.title, e.status), (5000, "The Lighthouse (edited)", "narrated"))
        self.assertEqual(e.added_at, "2026-10-29T12:00:00+00:00", "the first time it was added")

    def test_a_joined_series_keeps_every_part_link(self):
        s = replace(story("p3", "The Well", 300), parts=("https://www.reddit.com/a", "https://www.reddit.com/b"))
        self.lib.add(s)
        self.assertEqual(self.lib.get("p3").parts, ("https://www.reddit.com/a", "https://www.reddit.com/b"))

    def test_marking_narrated_and_back(self):
        self.lib.add(story("x1", "The Lighthouse", 100))
        self.assertTrue(self.lib.mark_narrated("x1", WHEN))
        self.assertEqual(self.lib.get("x1").narrated_at, "2026-10-29T12:00:00+00:00")
        self.assertEqual(self.lib.counts(), {"new": 0, "narrated": 1})
        self.assertTrue(self.lib.mark("x1", "new"))
        self.assertIsNone(self.lib.get("x1").narrated_at)
        self.assertFalse(self.lib.mark_narrated("nope"))
        with self.assertRaises(ValueError):
            self.lib.mark("x1", "posted")

    def test_saved_to_a_file_and_read_back(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "sub" / "library.db"
            with Library(path) as lib:
                lib.add(story("x1", "The Lighthouse", 100))
            with Library(path) as lib:
                self.assertEqual(lib.get("x1").title, "The Lighthouse")


class Finding(unittest.TestCase):
    def setUp(self):
        self.lib = Library(":memory:")
        self.lib.add(story("n1", "The cabin by the lake", 100, body="We rented a CABIN for the weekend. " * 60, score=500))
        self.lib.add(story("n2", "Night shift", 200, score=900))
        self.lib.add(story("l1", "The man at the cabin door", 300, sub="LetsNotMeet", body="He knocked at 3am. " * 100, score=300))
        self.lib.add(story("g1", "100% sure it was me", 400, sub="Glitch_in_the_Matrix", body="My double_walked by. " * 100, score=120))
        self.lib.mark_narrated("n2")

    def tearDown(self):
        self.lib.close()

    def ids(self, **kw):
        return [e.id for e in self.lib.find(**kw)]

    def test_everything_highest_score_first(self):
        self.assertEqual(self.ids(), ["n2", "n1", "l1", "g1"])

    def test_by_subreddit_in_any_capitalization(self):
        self.assertEqual(self.ids(subreddit="NoSleep"), ["n2", "n1"])
        self.assertEqual(self.ids(subreddit="r/LetsNotMeet"), ["l1"])

    def test_every_word_must_appear_in_the_title_or_text(self):
        self.assertEqual(sorted(self.ids(words=["cabin"])), ["l1", "n1"])
        self.assertEqual(self.ids(words=["cabin", "weekend"]), ["n1"])
        self.assertEqual(self.ids(words=["cabin", "spaceship"]), [])

    def test_percent_and_underscore_are_plain_characters(self):
        self.assertEqual(self.ids(words=["100%"]), ["g1"])
        self.assertEqual(self.ids(words=["double_walked"]), ["g1"])
        self.assertEqual(self.ids(words=["%"]), ["g1"])

    def test_by_status_and_combined(self):
        self.assertEqual(self.ids(status="narrated"), ["n2"])
        self.assertEqual(self.ids(status="new", subreddit="nosleep"), ["n1"])
        with self.assertRaises(ValueError):
            self.lib.find(status="done")

    def test_limit(self):
        self.assertEqual(len(self.lib.find(limit=2)), 2)


class FetchSavesToTheLibrary(unittest.TestCase):
    def test_finished_stories_and_joined_series_go_in_once(self):
        top = listing(post("s1", "The night ranger", 500),
                      post("p3", "The Well, Part 3 (Final)", 300),
                      post("u1", "Under the ice (Part 1)", 600, body=WORDS_TBC))
        history = listing(post("p3", "The Well, Part 3 (Final)", 300), post("p2", "The Well, Part 2", 200),
                          post("p1", "The Well, Part 1", 100))
        with tempfile.TemporaryDirectory() as d:
            args = SimpleNamespace(out=d, env="/nonexistent", library=str(Path(d) / "library.db"))
            cfg = Config(subreddits=["nosleep"], min_score=100)
            r, _ = client(FakeReddit([("ok", top, {}), ("ok", history, {})]))
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                self.assertEqual(cmd_fetch(args, cfg, reddit=r), 0)
            self.assertIn("2 new in the library", out.getvalue())
            with Library(args.library) as lib:
                self.assertEqual(sorted(e.id for e in lib.find()), ["p3", "s1"], "the unfinished story isn't kept")
                well = lib.get("p3")
                self.assertEqual(well.title, "The Well")
                self.assertEqual(len(well.parts), 3)
            # The same posts again: nothing new
            r, _ = client(FakeReddit([("ok", top, {}), ("ok", history, {})]))
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                cmd_fetch(args, cfg, reddit=r)
            self.assertIn("0 new in the library", out.getvalue())
            self.assertIn("Library: 2 waiting, 0 narrated", out.getvalue())

    def test_a_final_part_that_cannot_be_joined_is_not_kept(self):
        top = listing(post("p3", "The Well, Part 3 (Final)", 300))
        history = listing(post("p3", "The Well, Part 3 (Final)", 300), post("p1", "The Well, Part 1", 100))  # part 2 missing
        with tempfile.TemporaryDirectory() as d:
            args = SimpleNamespace(out=d, env="/nonexistent", library=str(Path(d) / "library.db"))
            r, _ = client(FakeReddit([("ok", top, {}), ("ok", history, {})]))
            with contextlib.redirect_stdout(io.StringIO()):
                cmd_fetch(args, Config(subreddits=["nosleep"], min_score=100), reddit=r)
            with Library(args.library) as lib:
                self.assertEqual(lib.find(), [])


WORDS_TBC = " ".join(["the ice cracked under my boots and something moved below"] * 45) + " To be continued."


class Commands(unittest.TestCase):
    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(["--config", "/nonexistent.toml", *argv])
        return code, out.getvalue(), err.getvalue()

    def test_find_and_mark(self):
        with tempfile.TemporaryDirectory() as d:
            db = str(Path(d) / "library.db")
            with Library(db) as lib:
                lib.add(story("n1", "The cabin by the lake", 100, body="We rented a cabin. " * 120))
                lib.add(story("l1", "The man at the door", 300, sub="LetsNotMeet"))
            code, out, _ = self.run_cli("find", "cabin", "--library", db)
            self.assertEqual(code, 0)
            self.assertIn("n1  [new]  r/nosleep  'The cabin by the lake'", out)
            self.assertIn("1 story found.", out)
            self.assertEqual(self.run_cli("mark", "n1", "--library", db)[1].strip(), "n1 marked narrated.")
            code, out, _ = self.run_cli("find", "--status", "narrated", "-r", "nosleep", "--library", db)
            self.assertIn("n1  [narrated]", out)
            code, _, err = self.run_cli("mark", "zz", "--library", db)
            self.assertEqual(code, 1)
            self.assertIn("No story with id 'zz'", err)

    def test_find_before_any_fetch_explains_what_to_do(self):
        with tempfile.TemporaryDirectory() as d:
            code, _, err = self.run_cli("find", "--library", str(Path(d) / "library.db"))
        self.assertEqual(code, 1)
        self.assertIn("Run `blueit fetch` first", err)


if __name__ == "__main__":
    unittest.main()
