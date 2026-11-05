import tempfile
import unittest
from pathlib import Path

from blueit.config import Config
from blueit.doctor import report, run_checks
from blueit.narrate import SilentVoice, VoiceError


class DoctorTest(unittest.TestCase):
    def test_everything_ready(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            (d / "images").mkdir()
            (d / "images" / "a.jpg").write_bytes(b"x")
            (d / ".env").write_text("REDDIT_CLIENT_ID=abc\nREDDIT_CLIENT_SECRET=xyz\n")
            cfg = Config(images=d / "images", output=d / "out", library=d / "library.db", voice_engine="silent")
            checks = run_checks(cfg, env=str(d / ".env"), which=lambda name: f"/usr/bin/{name}", voice_factory=SilentVoice,
                                python=(3, 12), environ={})
            self.assertTrue(all(c.ok for c in checks), report(checks))
            self.assertTrue(report(checks).endswith("Everything's ready."))

    def test_each_missing_thing_says_how_to_fix_it(self):
        def broken():
            raise VoiceError("eSpeak NG isn't installed")
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            cfg = Config(images=d / "images", output=d / "out", library=d / "library.db", voice_engine="espeak")
            checks = {c.name: c for c in run_checks(cfg, env=str(d / ".env"), which=lambda n: None, voice_factory=broken,
                                                    python=(3, 10), environ={})}
            self.assertFalse(checks["Python 3.11 or newer"].ok)
            self.assertIn("winget install ffmpeg", checks["FFmpeg"].detail)
            self.assertIn("eSpeak NG isn't installed", checks["Voice (espeak)"].detail)
            self.assertIn("put .jpg, .png or .webp files in", checks["Pictures"].detail)
            self.assertIn("copy .env.example", checks["Reddit app keys"].detail)
            self.assertIn("5 things need fixing.", report(list(checks.values())))


if __name__ == "__main__":
    unittest.main()
