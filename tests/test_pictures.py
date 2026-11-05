import tempfile
import unittest
from pathlib import Path

from blueit.narrate import Segment
from blueit.pictures import PictureError, find_pictures, plan


def segs(*lengths, gap=0.5):
    out, t = [], 0.0
    for n in lengths:
        out.append(Segment(t, t + n, "x"))
        t += n + gap
    return out


class FindPicturesTest(unittest.TestCase):
    def test_a_story_folder_with_its_own_pictures_wins(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            (d / "shared").mkdir(); (d / "story" / "images").mkdir(parents=True)
            for name in ["b.PNG", "a.jpg", "notes.txt"]:
                (d / "shared" / name).write_bytes(b"x")
            self.assertEqual([p.name for p in find_pictures(d / "story", d / "shared")], ["a.jpg", "b.PNG"])
            (d / "story" / "images" / "own.webp").write_bytes(b"x")
            self.assertEqual([p.name for p in find_pictures(d / "story", d / "shared")], ["own.webp"])

    def test_no_pictures_says_where_to_put_them(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaisesRegex(PictureError, "Put .jpg, .png or .webp files in"):
                find_pictures(Path(d) / "story", Path(d) / "images")


class PlanTest(unittest.TestCase):
    pics = [Path("1.jpg"), Path("2.jpg"), Path("3.jpg")]

    def test_pictures_change_only_between_pieces_and_cover_the_whole_narration(self):
        s = segs(3, 3, 3, 3, 3, 3, 3)          # 7 pieces of 3 s with 0.5 s pauses
        shots = plan(self.pics, s, seconds_each=6)
        self.assertEqual(shots[0].start, 0.0)
        self.assertEqual(shots[-1].end, s[-1].end)
        ends = {x.end for x in s}
        for a, b in zip(shots, shots[1:]):
            self.assertEqual(a.end, b.start)
            self.assertIn(a.end, ends, "cuts land where a piece ends")
            self.assertGreaterEqual(a.seconds, 6)

    def test_pictures_repeat_in_order_when_the_story_is_long(self):
        shots = plan(self.pics, segs(*[4] * 20), seconds_each=4)
        self.assertEqual([s.picture.name for s in shots[:5]], ["1.jpg", "2.jpg", "3.jpg", "1.jpg", "2.jpg"])

    def test_a_short_last_bit_joins_the_last_shot_instead_of_flashing_by(self):
        shots = plan(self.pics, segs(8, 1), seconds_each=8)
        self.assertEqual(len(shots), 1)

    def test_shuffle_is_the_same_for_the_same_story(self):
        many = [Path(f"{i}.jpg") for i in range(10)]
        a = plan(many, segs(*[5] * 10), 5, shuffle_seed="abc")
        b = plan(many, segs(*[5] * 10), 5, shuffle_seed="abc")
        c = plan(many, segs(*[5] * 10), 5, shuffle_seed="xyz")
        self.assertEqual(a, b)
        self.assertNotEqual([s.picture for s in a], [s.picture for s in c])

    def test_bad_input(self):
        for args in (([], segs(1)), (self.pics, []), (self.pics, segs(1), 0)):
            with self.assertRaises(PictureError):
                plan(*args)


if __name__ == "__main__":
    unittest.main()
