import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from blueit.captions import captions, write_srt
from blueit.narrate import SilentVoice, narrate
from blueit.pictures import Shot, plan
from blueit.video import VideoError, build_command, concat_list, duration, make_video, parse_size, video_filter

HAVE_FFMPEG = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))


class CommandTest(unittest.TestCase):
    def test_sizes(self):
        self.assertEqual(parse_size("1080x1920"), (1080, 1920))
        self.assertEqual(parse_size(" 1920 × 1080 "), (1920, 1080))
        for bad in ("big", "1081x1920", "10x10"):
            with self.assertRaises(VideoError):
                parse_size(bad)

    def test_concat_list_quotes_paths_and_repeats_the_last_picture(self):
        shots = [Shot(Path("/p/a.jpg"), 0, 8.5), Shot(Path("/p/it's.png"), 8.5, 12)]
        text = concat_list(shots)
        self.assertIn("file '/p/a.jpg'\nduration 8.500\n", text)
        self.assertIn("file '/p/it'\\''s.png'\nduration 3.500\n", text)
        self.assertTrue(text.endswith("file '/p/it'\\''s.png'\n"))

    def test_filter_fills_the_frame_without_stretching_and_adds_captions(self):
        vf = video_filter((1080, 1920), "captions.srt")
        self.assertIn("force_original_aspect_ratio=increase,crop=1080:1920", vf)
        self.assertIn("subtitles=captions.srt:force_style=", vf)
        self.assertNotIn("subtitles", video_filter((1080, 1920), None))
        cmd = build_command("ffmpeg", (1080, 1920), None)
        self.assertEqual(cmd[-1], "full.mp4")
        self.assertIn("-shortest", cmd)

    def test_missing_narration_or_failing_ffmpeg_explain_themselves(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaisesRegex(VideoError, "no narration yet"):
                make_video(Path(d), [], exe="ffmpeg")
            SilentVoice().say("hello there", Path(d) / "narration.wav")
            fail = lambda cmd, **kw: SimpleNamespace(returncode=1, stderr="Invalid data found")
            with self.assertRaisesRegex(VideoError, "Invalid data"):
                make_video(Path(d), [Shot(Path(d) / "a.png", 0, 1)], captions=False, runner=fail, exe="ffmpeg")


@unittest.skipUnless(HAVE_FFMPEG, "FFmpeg isn't installed")
class RealVideoTest(unittest.TestCase):
    def test_a_real_video_with_pictures_narration_and_captions(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            pics = []
            for i, color in enumerate(["red", "navy"]):
                p = d / f"{i}.png"
                subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", f"color=c={color}:s=640x480", "-frames:v", "1",
                                str(p)], check=True)
                pics.append(p)
            folder = d / "story"
            n = narrate("The door opened slowly. Nobody was there.\n\nThen the lights went out.", SilentVoice(wpm=300),
                        folder, max_chars=30)
            write_srt(captions(n.segments), folder / "captions.srt")
            shots = plan(pics, n.segments, seconds_each=1)
            out = make_video(folder, shots, size="360x640")
            self.assertTrue(out.exists())
            self.assertAlmostEqual(duration(out), n.seconds, delta=0.5)
            probe = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height",
                                    "-of", "csv=p=0", str(out)], capture_output=True, text=True).stdout.strip()
            self.assertEqual(probe, "360,640")


if __name__ == "__main__":
    unittest.main()
