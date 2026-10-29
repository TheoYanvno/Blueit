import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from blueit.cli import cmd_fetch
from blueit.config import Config
from blueit.series import find_and_join, join, order_parts, series_name
from blueit.story import Story

from .test_reddit import FakeReddit, client

WORDS = " ".join(["the night shift at the station was quiet until the radio crackled"] * 40)  # 480 words


def post(id, title, created, author="writer_one", sub="nosleep", body=WORDS, **extra):
    d = {"id": id, "title": title, "author": author, "subreddit": sub, "selftext": body,
         "created_utc": created, "score": 900, "permalink": f"/r/{sub}/comments/{id}/x/"}
    d.update(extra)
    return d


def story(*a, **k):
    return Story.from_reddit(post(*a, **k))


def listing(*posts):
    return {"kind": "Listing", "data": {"children": [{"kind": "t3", "data": p} for p in posts]}}


class SeriesName(unittest.TestCase):
    def test_strips_part_numbers_and_final_markers(self):
        for title in ["The Well, Part 1", "The Well - Part 2", "The Well (Part 3)", "The Well, Part 4 (Final)",
                      "The well [Pt. 2]", "THE WELL: part II", "The Well (2/4)"]:
            self.assertEqual(series_name(title), "the well", title)
        self.assertNotEqual(series_name("The Well, Part 1"), series_name("The Wall, Part 1"))


class Joining(unittest.TestCase):
    def setUp(self):
        self.p1 = story("p1", "The Well, Part 1", 100)
        self.p2 = story("p2", "The Well, Part 2", 200, body=WORDS + " Part 3 coming soon.")
        self.p3 = story("p3", "The Well, Part 3 (Final)", 300)

    def test_joins_parts_in_order_with_every_link(self):
        result = join(self.p3, [self.p3, self.p2, self.p1])
        self.assertTrue(result.ok, result.reason)
        s = result.story
        self.assertEqual(s.title, "The Well")
        self.assertEqual([p.id for p in result.parts], ["p1", "p2", "p3"])
        self.assertEqual(len(s.parts), 3)
        self.assertTrue(s.body.startswith("Part 1.\n\n"))
        self.assertLess(s.body.index("Part 2."), s.body.index("Part 3."))
        self.assertEqual(s.created_utc, 100, "the joined story is dated by its first part")

    def test_earlier_parts_may_say_more_is_coming(self):
        self.assertTrue(join(self.p3, [self.p1, self.p2]).ok)

    def test_missing_part_is_reported(self):
        result = join(self.p3, [self.p1])
        self.assertFalse(result.ok)
        self.assertEqual(result.reason, "missing part 2")

    def test_only_same_author_subreddit_and_series_count(self):
        other_author = story("x1", "The Well, Part 2", 150, author="copycat")
        other_sub = story("x2", "The Well, Part 2", 150, sub="shortscarystories")
        other_series = story("x3", "The Wall, Part 2", 150)
        later = story("x4", "The Well, Part 2", 999)  # posted after the final part
        result = join(self.p3, [self.p1, other_author, other_sub, other_series, later])
        self.assertEqual(result.reason, "missing part 2")

    def test_a_reposted_part_keeps_the_first_post(self):
        repost = story("p2b", "The Well, Part 2 (reposted)", 250)
        ids = [p.id for p in order_parts(self.p3, [self.p1, repost, self.p2])]
        self.assertEqual(ids, ["p1", "p2", "p3"])

    def test_a_removed_part_stops_the_join(self):
        removed = story("p2", "The Well, Part 2", 200, body="[removed]")
        result = join(self.p3, [self.p1, removed])
        self.assertFalse(result.ok)
        self.assertIn("removed", result.reason)

    def test_parts_written_as_1_of_3(self):
        a, b, c = story("a", "Night Bus (1/3)", 1), story("b", "Night Bus (2/3)", 2), story("c", "Night Bus (3/3)", 3)
        result = join(c, [a, b])
        self.assertTrue(result.ok, result.reason)
        self.assertEqual(result.story.title, "Night Bus")

    def test_not_a_final_part(self):
        self.assertFalse(join(self.p2, [self.p1]).ok)

    def test_too_long_when_joined(self):
        self.assertIn("too long", join(self.p3, [self.p1, self.p2], max_words=1000).reason)


class ThroughTheApi(unittest.TestCase):
    def test_finds_earlier_parts_in_the_authors_posts(self):
        history = listing(post("p3", "The Well, Part 3 (Final)", 300), post("p2", "The Well, Part 2", 200),
                          post("zz", "Something else entirely", 150), post("p1", "The Well, Part 1", 100))
        fake = FakeReddit([("ok", history, {})])
        r, _ = client(fake)
        result = find_and_join(r, story("p3", "The Well, Part 3 (Final)", 300))
        self.assertTrue(result.ok, result.reason)
        url = fake.requests[-1].full_url
        self.assertIn("/user/writer_one/submitted?", url)
        self.assertIn("sort=new", url)
        self.assertIn("limit=100", url)

    def test_deleted_author_is_explained(self):
        r, _ = client(FakeReddit())
        result = find_and_join(r, story("p3", "The Well, Part 3 (Final)", 300, author="[deleted]"))
        self.assertFalse(result.ok)
        self.assertIn("deleted", result.reason)

    def test_fetch_saves_joined_series(self):
        top = listing(post("p3", "The Well, Part 3 (Final)", 300))
        history = listing(post("p3", "The Well, Part 3 (Final)", 300), post("p2", "The Well, Part 2", 200),
                          post("p1", "The Well, Part 1", 100))
        r, _ = client(FakeReddit([("ok", top, {}), ("ok", history, {})]))
        with tempfile.TemporaryDirectory() as d:
            args = SimpleNamespace(out=d, env="/nonexistent", library=str(Path(d) / "library.db"))
            self.assertEqual(cmd_fetch(args, Config(subreddits=["nosleep"], min_score=100), reddit=r), 0)
            saved = json.loads((Path(d) / "nosleep.series.json").read_text())
        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0]["title"], "The Well")
        self.assertEqual(len(saved[0]["parts"]), 3)


if __name__ == "__main__":
    unittest.main()
