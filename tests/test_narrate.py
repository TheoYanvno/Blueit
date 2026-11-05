import tempfile
import unittest
import wave
from pathlib import Path
from types import SimpleNamespace

from blueit.narrate import (EspeakVoice, Narration, SilentVoice, VoiceError, WindowsVoice, estimate_seconds,
                            join_wavs, make_voice, narrate, pieces, sentences)


class SentencesTest(unittest.TestCase):
    def test_splits_on_sentence_ends_and_keeps_closing_quotes(self):
        self.assertEqual(sentences('I froze. "Who\'s there?" Nobody answered! Then… silence.'),
                         ['I froze.', '"Who\'s there?"', 'Nobody answered!', 'Then… silence.'])

    def test_does_not_split_inside_numbers_or_lowercase_runs(self):
        self.assertEqual(sentences("It was 3.5 miles away. ok then."), ["It was 3.5 miles away. ok then."])


class PiecesTest(unittest.TestCase):
    def test_groups_sentences_and_never_crosses_a_paragraph(self):
        text = "One. Two. Three.\n\nFour."
        ps = pieces(text, max_chars=12)
        self.assertEqual([p.text for p in ps], ["One. Two.", "Three.", "Four."])
        self.assertEqual([p.ends_paragraph for p in ps], [False, True, True])

    def test_splits_a_very_long_sentence(self):
        long = ", ".join(["the hallway kept going"] * 30) + "."
        ps = pieces(long, max_chars=100)
        self.assertTrue(all(len(p.text) <= 100 for p in ps))
        self.assertEqual(" ".join(p.text for p in ps), long)

    def test_empty_text(self):
        self.assertEqual(pieces("  \n\n "), [])


class VoicesTest(unittest.TestCase):
    def test_silent_voice_writes_a_wav_as_long_as_reading_takes(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "a.wav"
            SilentVoice(wpm=150).say(" ".join(["word"] * 150), f)
            with wave.open(str(f)) as w:
                self.assertAlmostEqual(w.getnframes() / w.getframerate(), 60, places=1)
        self.assertEqual(estimate_seconds("hi"), 0.4)

    def test_windows_voice_reads_the_text_from_a_file_so_nothing_runs_as_code(self):
        calls = []

        def runner(cmd, **kw):
            calls.append(cmd)
            import re
            out = Path(re.search(r"SetOutputToWaveFile\('((?:[^']|'')*)'\)", cmd[-1]).group(1).replace("''", "'"))
            SilentVoice().say("x", out)
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        with tempfile.TemporaryDirectory() as d:
            v = WindowsVoice(voice="Zira", rate=-2, runner=runner)
            out = Path(d) / "it's.wav"
            v.say("'; Remove-Item C:\\ -Recurse; '", out)
            script = calls[0][-1]
            self.assertNotIn("Remove-Item", script)
            self.assertIn("ReadAllText", script)
            self.assertIn("$s.Rate = -2", script)
            self.assertIn("'*Zira*'", script)
            self.assertIn("it''s.wav", script, "quotes in paths are escaped")
            self.assertFalse(out.with_suffix(".txt").exists(), "the text file is cleaned up")
        with self.assertRaises(VoiceError):
            WindowsVoice(rate=11)

    def test_espeak_gets_the_text_on_stdin(self):
        seen = {}

        def runner(cmd, **kw):
            seen.update(cmd=cmd, input=kw["input"])
            SilentVoice().say("x", Path(cmd[cmd.index("-w") + 1]))
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        with tempfile.TemporaryDirectory() as d:
            EspeakVoice("en-gb", 170, runner=runner).say("--help me", Path(d) / "a.wav")
        self.assertEqual(seen["input"], "--help me")
        self.assertIn("--stdin", seen["cmd"])
        self.assertEqual(seen["cmd"][seen["cmd"].index("-s") + 1], "170")

    def test_a_failing_voice_says_why(self):
        bad = lambda cmd, **kw: SimpleNamespace(returncode=1, stdout="", stderr="no voice")
        with tempfile.TemporaryDirectory() as d, self.assertRaisesRegex(VoiceError, "no voice"):
            EspeakVoice(runner=bad).say("hi", Path(d) / "a.wav")

    def test_make_voice(self):
        self.assertIsInstance(make_voice("silent"), SilentVoice)
        self.assertEqual(make_voice("windows", "David", 1).rate, 1)
        with self.assertRaises(VoiceError):
            make_voice("robot")


class JoinAndNarrateTest(unittest.TestCase):
    def test_join_adds_pauses_and_reports_each_piece_time(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            v = SilentVoice(wpm=60, rate=8000)
            a, b = d / "a.wav", d / "b.wav"
            v.say("one two", a)      # 2 s
            v.say("three", b)        # 1 s
            times = join_wavs([a, b], d / "out.wav", [0.5, 0.0])
            self.assertEqual(times, [(0.0, 2.0), (2.5, 3.5)])
            with wave.open(str(d / "out.wav")) as w:
                self.assertAlmostEqual(w.getnframes() / w.getframerate(), 3.5, places=2)

    def test_join_refuses_mixed_formats(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            SilentVoice(rate=8000).say("a", d / "a.wav")
            SilentVoice(rate=16000).say("b", d / "b.wav")
            with self.assertRaises(VoiceError):
                join_wavs([d / "a.wav", d / "b.wav"], d / "o.wav", [0, 0])

    def test_narrate_writes_audio_and_timed_segments_that_load_back(self):
        with tempfile.TemporaryDirectory() as d:
            folder = Path(d) / "story"
            seen = []
            n = narrate("The door opened. Nobody was there.\n\nI ran.", SilentVoice(), folder, max_chars=20,
                        progress=lambda done, total: seen.append((done, total)))
            self.assertTrue((folder / "narration.wav").exists())
            self.assertEqual([s.text for s in n.segments], ["The door opened.", "Nobody was there.", "I ran."])
            starts = [s.start for s in n.segments]
            self.assertEqual(starts, sorted(starts))
            self.assertGreater(n.segments[2].start - n.segments[1].end, n.segments[1].start - n.segments[0].end,
                               "a paragraph break pauses longer than a sentence break")
            self.assertEqual(seen[-1], (3, 3))
            again = Narration.load(folder / "narration.json")
            self.assertEqual(again.segments, n.segments)
            self.assertEqual(again.audio, folder / "narration.wav")
            self.assertEqual(sorted(p.name for p in folder.iterdir()), ["narration.json", "narration.wav"])
            with self.assertRaises(VoiceError):
                narrate("   ", SilentVoice(), folder)


if __name__ == "__main__":
    unittest.main()
