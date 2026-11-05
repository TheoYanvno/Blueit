import tempfile
import unittest
from pathlib import Path

from blueit.captions import Caption, captions, shift, timestamp, to_srt, wrap, write_srt
from blueit.narrate import Segment


class CaptionsTest(unittest.TestCase):
    def test_wrap_breaks_between_words(self):
        self.assertEqual(wrap("the old house at the end of the road", 14), ["the old house", "at the end of", "the road"])
        self.assertEqual(wrap("supercalifragilistic ok", 10), ["supercalifragilistic", "ok"])

    def test_a_long_piece_becomes_several_two_line_captions_sharing_its_time_by_words(self):
        seg = Segment(10.0, 20.0, "one two three four five six seven eight nine ten")
        caps = captions([seg], max_chars=10, max_lines=2)
        self.assertEqual([c.lines for c in caps], [("one two", "three four"), ("five six", "seven"),
                                                    ("eight nine", "ten")])
        self.assertEqual(caps[0].start, 10.0)
        self.assertEqual(caps[-1].end, 20.0)
        self.assertEqual(caps[0].end, 14.0)          # 4 of 10 words
        for a, b in zip(caps, caps[1:]):
            self.assertEqual(a.end, b.start)

    def test_srt_format(self):
        srt = to_srt([Caption(0, 1.5, ("Hello",)), Caption(3661.25, 3662, ("Two", "lines"))])
        self.assertEqual(srt, "1\n00:00:00,000 --> 00:00:01,500\nHello\n\n2\n01:01:01,250 --> 01:01:02,000\nTwo\nlines\n\n")
        self.assertEqual(timestamp(59.9996), "00:01:00,000")
        with tempfile.TemporaryDirectory() as d:
            p = write_srt([Caption(0, 1, ("Hi",))], Path(d) / "c.srt")
            self.assertTrue(p.read_text(encoding="utf-8").startswith("1\n"))

    def test_shift_keeps_only_a_parts_captions_and_starts_them_at_zero(self):
        caps = [Caption(0, 5, ("a",)), Caption(5, 12, ("b",)), Caption(12, 20, ("c",))]
        self.assertEqual(shift(caps, 10, 15), [Caption(0, 2, ("b",)), Caption(2, 5, ("c",))])


if __name__ == "__main__":
    unittest.main()
