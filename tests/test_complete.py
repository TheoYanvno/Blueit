import json
import unittest
from pathlib import Path

from blueit.complete import check, series_part
from blueit.story import Story

FIX = Path(__file__).parent / "fixtures" / "listing.json"


def post(**kw):
    base = dict(id="x", subreddit="nosleep", title="A story", author="someone",
                selftext=" ".join(["word"] * 800), permalink="/r/nosleep/comments/x/a/", created_utc=0)
    base.update(kw)
    return Story.from_reddit(base)


class SeriesPart(unittest.TestCase):
    def test_numbers(self):
        self.assertEqual(series_part("The well (Part 3)"), (3, None))
        self.assertEqual(series_part("The well pt. 2"), (2, None))
        self.assertEqual(series_part("The well [Part IV]"), (4, None))
        self.assertEqual(series_part("The well (2/5)"), (2, 5))
        self.assertEqual(series_part("The party at the well"), (None, None))


class Check(unittest.TestCase):
    def test_standalone_story_is_finished(self):
        self.assertTrue(check(post()).ok)

    def test_middle_part_is_not(self):
        v = check(post(title="The well (Part 2)"))
        self.assertFalse(v.ok)
        self.assertEqual(v.part, 2)

    def test_final_part_is_finished(self):
        for title in ("The well (Part 5, Final)", "The well (5/5)", "The well: the conclusion"):
            self.assertTrue(check(post(title=title)).ok, title)
        self.assertTrue(check(post(title="The well (Part 5)", link_flair_text="Series (Finished)")).ok)

    def test_last_in_a_title_is_not_a_series_ending(self):
        v = check(post(title="The last time I went camping alone"))
        self.assertTrue(v.ok)
        self.assertFalse(v.final)
        self.assertTrue(check(post(title="Lake Marrow (Final)")).final)

    def test_more_coming_at_the_end(self):
        body = " ".join(["word"] * 800) + " Update soon, stay tuned!"
        self.assertFalse(check(post(selftext=body)).ok)

    def test_more_coming_in_the_middle_is_fine(self):
        body = "He wrote to be continued on the wall. " + " ".join(["word"] * 800)
        self.assertTrue(check(post(selftext=body)).ok)

    def test_removed_short_long_and_nsfw(self):
        self.assertFalse(check(post(selftext="[removed]")).ok)
        self.assertFalse(check(post(selftext="too short")).ok)
        self.assertFalse(check(post(selftext="w " * 20000)).ok)
        self.assertFalse(check(post(over_18=True)).ok)
        self.assertTrue(check(post(over_18=True), allow_nsfw=True).ok)

    def test_unfinished_flair(self):
        self.assertFalse(check(post(link_flair_text="Series")).ok)

    def test_fixture_listing(self):
        children = json.loads(FIX.read_text())["data"]["children"]
        results = {c["data"]["id"]: check(Story.from_reddit(c["data"])).ok for c in children}
        self.assertEqual(results, {"a1": True, "a2": False, "a3": True, "a4": False, "a5": False})


if __name__ == "__main__":
    unittest.main()
