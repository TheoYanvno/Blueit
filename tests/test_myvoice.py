import math
import tempfile
import unittest
import wave
from array import array
from pathlib import Path

from blueit.myvoice import (AI_CREDIT, SCRIPT, MyVoice, VoiceStore, add_ai_credit, best_clip, set_setting, slug,
                            write_samples)
from blueit.narrate import VoiceError, make_voice, narrate


def tone_wav(path: Path, pattern, rate=8000):
    """A WAV of 0.5-second blocks: 1 = a loud tone (speech), 0 = silence (a pause)."""
    samples = array("h")
    for loud in pattern:
        for i in range(rate // 2):
            samples.append(int(12000 * math.sin(i / 5)) if loud else 0)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate); w.writeframes(samples.tobytes())
    return path


class FakeModel:
    sr = 24000

    def __init__(self):
        self.calls = []

    def generate(self, text, audio_prompt_path, exaggeration=0.5):
        self.calls.append((text, Path(audio_prompt_path).name))
        return [0.1, -0.1] * int(self.sr * 0.25)          # half a second of "speech" per piece


class ScriptTest(unittest.TestCase):
    def test_the_script_takes_about_five_minutes_to_read(self):
        words = len(SCRIPT.split())
        self.assertTrue(650 <= words <= 900, words)
        for must in ("?", "!", "1987", "Whispering", "I agree to Blueit using this recording"):
            self.assertIn(must, SCRIPT)


class StoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.store = VoiceStore(self.tmp / "voices")
        # 25 s of speech with a long pause at the start: the prompt should skip the pause
        self.rec = tone_wav(self.tmp / "rec.wav", [0] * 10 + [1] * 50)

    def test_saving_needs_your_own_voice_and_a_long_enough_recording(self):
        with self.assertRaises(VoiceError):
            self.store.save("Mine", self.rec, own_voice=False)
        short = tone_wav(self.tmp / "short.wav", [1] * 10)
        with self.assertRaisesRegex(VoiceError, "at least 20"):
            self.store.save("Short", short, own_voice=True)
        self.assertEqual(self.store.list(), [], "a failed save leaves nothing behind")

    def test_save_makes_a_prompt_from_the_clearest_stretch_and_becomes_the_default(self):
        v = self.store.save("Anthony", self.rec, own_voice=True, now=lambda: 0)
        folder = self.tmp / "voices" / "anthony"
        self.assertTrue((folder / "recording.wav").exists())
        with wave.open(str(folder / "prompt.wav")) as w:
            self.assertAlmostEqual(w.getnframes() / w.getframerate(), 15, delta=0.6)
            first = array("h", w.readframes(4000))
        self.assertGreater(max(first), 1000, "the prompt starts with speech, not the opening pause")
        self.assertEqual(v.seconds, 30.0)
        self.assertEqual(self.store.default.slug, "anthony")

    def test_bytes_upload_rename_default_and_delete(self):
        a = self.store.save("Anthony", self.rec.read_bytes(), own_voice=True)
        b = self.store.save("Anthony", self.rec, own_voice=True)
        self.assertEqual((a.slug, b.slug), ("anthony", "anthony-2"))
        self.store.rename("anthony-2", "Storyteller voice")
        self.assertEqual(self.store.get("Storyteller voice").slug, "anthony-2")
        self.store.set_default("Storyteller voice")
        self.assertEqual(self.store.default.slug, "anthony-2")
        self.store.delete("anthony-2")
        self.assertIsNone(self.store.get("anthony-2"))
        self.assertEqual(self.store.default.slug, "anthony", "with one voice left, it's the default")
        with self.assertRaises(VoiceError):
            self.store.delete("nobody")

    def test_not_a_wav(self):
        bad = self.tmp / "bad.wav"
        bad.write_bytes(b"not audio")
        with self.assertRaisesRegex(VoiceError, "WAV"):
            self.store.save("Bad", bad, own_voice=True)

    def test_slug(self):
        self.assertEqual(slug("  My Voice #2! "), "my-voice-2")
        self.assertEqual(slug("!!!"), "my-voice")


class EngineTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.root = self.tmp / "voices"
        VoiceStore(self.root).save("Anthony", tone_wav(self.tmp / "rec.wav", [1] * 60), own_voice=True)

    def test_narrates_with_the_saved_voice_and_labels_the_credit(self):
        model = FakeModel()
        voice = MyVoice(root=self.root, model_factory=lambda: model)
        folder = self.tmp / "story"
        folder.mkdir()
        (folder / "credit.txt").write_text('"Title" by u/someone\n', encoding="utf-8")
        n = narrate("First sentence. Second one.\n\nNew paragraph.", voice, folder)
        self.assertEqual([c[1] for c in model.calls], ["prompt.wav", "prompt.wav"])
        self.assertGreater(n.seconds, 1.0)
        credit = (folder / "credit.txt").read_text(encoding="utf-8")
        self.assertIn(AI_CREDIT, credit)
        add_ai_credit(folder)
        self.assertEqual((folder / "credit.txt").read_text(encoding="utf-8").count(AI_CREDIT), 1)

    def test_errors_say_what_to_do(self):
        with self.assertRaisesRegex(VoiceError, "no saved voice called 'Zira'"):
            MyVoice("Zira", root=self.root, model_factory=FakeModel)
        with self.assertRaisesRegex(VoiceError, "Record my voice"):
            MyVoice(root=self.tmp / "empty", model_factory=FakeModel)
        def missing():
            raise VoiceError("the My voice add-on isn't installed")
        v = MyVoice(root=self.root, model_factory=missing)
        with self.assertRaisesRegex(VoiceError, "add-on"):
            v.say("Hello.", self.tmp / "x.wav")

    def test_make_voice_knows_myvoice(self):
        v = make_voice("myvoice", "Anthony", None, self.root)
        self.assertEqual(v.name, "myvoice")
        self.assertTrue(v.ai_generated)

    def test_write_samples_clips_to_16_bit(self):
        p = self.tmp / "s.wav"
        write_samples(p, [0.0, 0.5, 2.0, -3.0], 24000)
        with wave.open(str(p)) as w:
            self.assertEqual(list(array("h", w.readframes(4))), [0, 16383, 32767, -32767])


class SettingTest(unittest.TestCase):
    def test_set_setting_keeps_comments_and_other_lines(self):
        p = Path(tempfile.mkdtemp()) / "blueit.toml"
        p.write_text('[blueit]\nlimit = 25\nvoice_engine = "windows"  # the narrator\n\n[other]\nx = 1\n', encoding="utf-8")
        set_setting(p, "voice_engine", "myvoice")
        set_setting(p, "voice", "Anthony")
        text = p.read_text(encoding="utf-8")
        self.assertIn('voice_engine = "myvoice"  # the narrator', text)
        self.assertIn('# the narrator\nvoice = "Anthony"\n\n[other]', text)
        self.assertLess(text.index('voice = "Anthony"'), text.index("[other]"))
        from blueit.config import Config
        cfg = Config.load(p)
        self.assertEqual((cfg.voice_engine, cfg.voice), ("myvoice", "Anthony"))


if __name__ == "__main__":
    unittest.main()


class PageTest(unittest.TestCase):
    """The Record my voice page's server side: upload, list, rename, default, use as narrator, delete."""

    def setUp(self):
        import http.client
        import threading
        from blueit.config import Config
        from blueit.web import App, make_server
        self.http = http.client
        self.tmp = Path(tempfile.mkdtemp())
        self.toml = self.tmp / "blueit.toml"
        self.toml.write_text('[blueit]\nvoice_engine = "espeak"\n', encoding="utf-8")
        self.cfg = Config(voices=self.tmp / "voices", output=self.tmp / "out", voice_engine="espeak")
        self.app = App(self.cfg, self.tmp / "library.db", config_path=self.toml)
        self.server = make_server(self.app, port=0)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.rec = tone_wav(self.tmp / "rec.wav", [1] * 50).read_bytes()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()

    def request(self, method, path, body=None, kind="application/json"):
        import json
        c = self.http.HTTPConnection("127.0.0.1", self.server.server_address[1])
        data = body if isinstance(body, bytes) else (json.dumps(body).encode() if body is not None else None)
        c.request(method, path, data, {"Content-Type": kind} if data is not None else {})
        r = c.getresponse()
        raw = r.read()
        return r.status, (json.loads(raw) if r.getheader("Content-Type", "").startswith("application/json") else raw)

    def test_upload_needs_the_own_voice_tick_then_lists_and_plays_the_clip(self):
        status, data = self.request("GET", "/api/voices")
        self.assertEqual((status, data["voices"], data["narrator"]), (200, [], False))
        self.assertIn("Whispering", data["script"])
        status, data = self.request("POST", "/api/voices/upload?name=Anthony", self.rec, "audio/wav")
        self.assertEqual(status, 400)
        self.assertIn("own voice", data["error"])
        status, data = self.request("POST", "/api/voices/upload?name=Anthony&mine=1", self.rec, "audio/wav")
        self.assertEqual((status, data["saved"], data["default"]), (200, "anthony", "anthony"))
        status, clip = self.request("GET", "/api/voices/clip?voice=anthony&which=prompt")
        self.assertEqual(status, 200)
        self.assertEqual(clip[:4], b"RIFF")
        self.assertEqual(self.request("GET", "/api/voices/clip?voice=../etc&which=prompt")[0], 400)
        self.assertEqual(self.request("POST", "/api/voices/upload?mine=1", b"x" * 100, "text/plain")[0], 415)

    def test_use_as_narrator_saves_to_blueit_toml_and_can_be_turned_off(self):
        self.request("POST", "/api/voices/upload?name=Anthony&mine=1", self.rec, "audio/wav")
        status, data = self.request("POST", "/api/voices", {"action": "use", "voice": "anthony", "on": True})
        self.assertEqual((status, data["narrator"]), (200, True))
        self.assertIn('voice_engine = "myvoice"', self.toml.read_text(encoding="utf-8"))
        self.assertIn('voice = "Anthony"', self.toml.read_text(encoding="utf-8"))
        status, data = self.request("POST", "/api/voices", {"action": "use", "on": False})
        self.assertFalse(data["narrator"])
        self.assertNotIn("myvoice", self.toml.read_text(encoding="utf-8"))

    def test_rename_and_delete(self):
        self.request("POST", "/api/voices/upload?name=Anthony&mine=1", self.rec, "audio/wav")
        _, data = self.request("POST", "/api/voices", {"action": "rename", "voice": "anthony", "name": "Night voice"})
        self.assertEqual(data["voices"][0]["name"], "Night voice")
        _, data = self.request("POST", "/api/voices", {"action": "delete", "voice": "anthony"})
        self.assertEqual(data["voices"], [])
        status, data = self.request("POST", "/api/voices", {"action": "fly"})
        self.assertEqual(status, 400)
