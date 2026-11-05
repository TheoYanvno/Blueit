import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from blueit.captions import captions, write_srt
from blueit.narrate import Segment, SilentVoice, narrate
from blueit.parts import cut_points, make_parts, part_name
from blueit.pictures import plan
from blueit.video import VideoError, duration, make_video

HAVE_FFMPEG = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))


def segs(*lengths, gap=0.5):
    out, t = [], 0.0
    for n in lengths:
        out.append(Segment(t, t + n, "x"))
        t += n + gap
    return out


class CutPointsTest(unittest.TestCase):
    def test_parts_end_between_sentences_and_stay_within_the_limit(self):
        s = segs(*[9.5] * 14)                       # 10 s per piece with the pause, about 140 s in all
        parts = cut_points(s, 60)
        self.assertEqual(parts[0][0], 0.0)
        self.assertEqual(parts[-1][1], s[-1].end)
        ends = {x.end for x in s}
        for (a, b), (c, d) in zip(parts, parts[1:]):
            self.assertEqual(b, c)
            self.assertIn(b, ends)
            self.assertLessEqual(b - a, 60)
        self.assertEqual(len(parts), 3)

    def test_a_short_story_is_one_part(self):
        self.assertEqual(cut_points(segs(10, 10), 60), [(0.0, 20.5)])

    def test_a_piece_longer_than_the_limit_gets_a_part_of_its_own(self):
        parts = cut_points(segs(5, 80, 5), 60)
        self.assertEqual(parts[0], (0.0, 5.0))
        self.assertEqual(parts[1], (5.0, 85.5))

    def test_a_long_last_piece_does_not_leave_an_empty_part(self):
        parts = cut_points(segs(3, 25, 22), 20)
        self.assertTrue(all(b > a for a, b in parts))
        self.assertEqual(parts[-1][1], segs(3, 25, 22)[-1].end)

    def test_names_and_bad_input(self):
        self.assertEqual(part_name(3), "part-03.mp4")
        self.assertEqual(cut_points([], 60), [])
        with self.assertRaises(VideoError):
            cut_points(segs(1), 0)
        with tempfile.TemporaryDirectory() as d, self.assertRaisesRegex(VideoError, "no full.mp4"):
            make_parts(Path(d), segs(1), exe="ffmpeg")


@unittest.skipUnless(HAVE_FFMPEG, "FFmpeg isn't installed")
class RealPartsTest(unittest.TestCase):
    def test_cuts_a_real_video_into_parts_and_replaces_old_ones(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            pic = d / "p.png"
            subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=gray:s=320x240", "-frames:v", "1", str(pic)],
                           check=True)
            folder = d / "story"
            text = " ".join(f"Sentence number {i} is here." for i in range(12))
            n = narrate(text, SilentVoice(wpm=240), folder, max_chars=30)
            write_srt(captions(n.segments), folder / "captions.srt")
            make_video(folder, plan([pic], n.segments, 2), size="240x426")
            (folder / "part-09.mp4").write_bytes(b"old")
            parts = make_parts(folder, n.segments, clip_seconds=4)
            self.assertEqual([p.name for p in parts], [part_name(i) for i in range(1, len(parts) + 1)])
            if len(parts) < 9:
                self.assertFalse((folder / "part-09.mp4").exists(), "old parts are removed")
            self.assertGreater(len(parts), 1)
            total = sum(duration(p) for p in parts)
            self.assertAlmostEqual(total, duration(folder / "full.mp4"), delta=0.6)
            for p in parts:
                self.assertLessEqual(duration(p), 4.6)


if __name__ == "__main__":
    unittest.main()
