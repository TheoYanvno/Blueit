import shutil
import subprocess
import tempfile
import unittest
import wave
from pathlib import Path

from blueit.moods import KINDS, counts, ensure_folders, find_sound, kind_for_subreddit, story_kind, SOUND_TYPES
from blueit.pictures import PictureError, any_pictures, find_pictures
from blueit.video import build_command


def touch(p: Path) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"x")
    return p


class Moods(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.story = self.root / "output" / "the-cabin"
        self.story.mkdir(parents=True)
        (self.story / "credit.txt").write_text('"The cabin" by u/x\nr/nosleep: https://reddit.com/x\n', encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def test_a_story_knows_its_kind_from_its_subreddit(self):
        self.assertEqual(kind_for_subreddit("r/NoSleep"), "scary")
        self.assertEqual(kind_for_subreddit("tifu"), "funny")
        self.assertEqual(kind_for_subreddit("AskReddit"), "")
        self.assertEqual(story_kind(self.story), "scary")
        self.assertEqual(story_kind(self.root), "")

    def test_folders_are_made_for_every_kind(self):
        made = ensure_folders(self.root / "images", self.root / "music")
        self.assertEqual(len(made), 2 * len(KINDS))
        self.assertTrue((self.root / "music" / "paranormal").is_dir())
        self.assertEqual(ensure_folders(self.root / "images"), [])          # already there

    def test_pictures_come_from_the_story_then_its_kind_then_the_shared_folder(self):
        images = self.root / "images"
        touch(images / "any.jpg")
        self.assertEqual([p.name for p in find_pictures(self.story, images, "scary")], ["any.jpg"])
        touch(images / "scary" / "b.png"); touch(images / "scary" / "a.jpg"); touch(images / "funny" / "f.jpg")
        self.assertEqual([p.name for p in find_pictures(self.story, images, "scary")], ["a.jpg", "b.png"])
        touch(self.story / "images" / "own.jpg")
        self.assertEqual([p.name for p in find_pictures(self.story, images, "scary")], ["own.jpg"])
        self.assertEqual(counts(images, {".jpg", ".png"})["scary"], 2)

    def test_no_pictures_says_where_to_put_them(self):
        images = self.root / "images"
        ensure_folders(images)
        self.assertFalse(any_pictures(images))
        with self.assertRaisesRegex(PictureError, "scary"):
            find_pictures(self.story, images, "scary")
        touch(images / "work" / "w.jpg")
        self.assertTrue(any_pictures(images))

    def test_a_background_sound_matches_the_kind_and_stays_the_same(self):
        music = self.root / "music"
        self.assertIsNone(find_sound(self.story, music, "scary"))
        touch(music / "funny" / "kazoo.mp3")
        self.assertIsNone(find_sound(self.story, music, "scary"))           # never another kind's sound
        touch(music / "scary" / "wind.mp3"); touch(music / "scary" / "drone.ogg"); touch(music / "scary" / "notes.txt")
        pick = find_sound(self.story, music, "scary")
        self.assertIn(pick.name, {"wind.mp3", "drone.ogg"})
        self.assertEqual(find_sound(self.story, music, "scary"), pick)
        self.assertNotIn(".txt", SOUND_TYPES)

    def test_the_sound_loops_quietly_under_the_voice_and_fades(self):
        cmd = build_command("ffmpeg", (1080, 1920), None, sound=Path("wind.mp3"), sound_volume=0.12, length=60)
        graph = cmd[cmd.index("-filter_complex") + 1]
        self.assertIn("-stream_loop", cmd)
        self.assertIn("volume=0.12", graph)
        self.assertIn("afade=t=out:st=57.00:d=3", graph)
        self.assertIn("amix=inputs=2:duration=first", graph)
        self.assertNotIn("-vf", cmd)
        plain = build_command("ffmpeg", (1080, 1920), None, sound=Path("wind.mp3"), sound_volume=0)
        self.assertIn("-vf", plain)
        self.assertNotIn("-filter_complex", plain)

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg isn't installed")
    def test_ffmpeg_makes_a_video_with_the_background_mixed_in(self):
        from blueit.pictures import Shot
        from blueit.video import make_video
        d = self.story
        for name, hz in (("narration.wav", 440), ("bg.wav", 220)):
            subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", f"sine=frequency={hz}:duration={4 if name == 'narration.wav' else 1}",
                            str(d / name)], check=True)
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "color=c=gray:s=320x240:d=1", "-frames:v", "1", str(d / "p.png")], check=True)
        out = make_video(d, [Shot(d / "p.png", 0, 4.0)], "320x568", captions=False, sound=d / "bg.wav", sound_volume=0.2)
        r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(out)],
                           capture_output=True, text=True)
        self.assertAlmostEqual(float(r.stdout), 4.0, delta=0.4)            # as long as the voice, not the looped sound


if __name__ == "__main__":
    unittest.main()
