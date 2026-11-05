"""Narration: turns a story's cleaned text into one WAV file with a stock text-to-speech voice, and
records when each piece of text is spoken so the video can show captions in time with the voice.

The text is read in short pieces (a few sentences each, never more than `max_chars`), one audio file
per piece, joined with a short pause between pieces and a longer one between paragraphs. Short
pieces keep every voice engine fast and reliable, and give the captions their timings for free.

Voices (no extra Python packages needed):
  windows   the voices built into Windows, through PowerShell's System.Speech
  espeak    eSpeak NG (Linux, macOS, or Windows with eSpeak NG installed)
  silent    silence as long as the text would take to read; for tests and quick previews
A voice cloned from your own recordings will be another engine here later.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
import wave
from dataclasses import dataclass, asdict
from pathlib import Path

WORDS_PER_MINUTE = 150
_SENTENCE = re.compile(r"(?<=[.!?…])[\"”’)\]]*\s+(?=[\"“‘(\[]?[A-Z0-9])")


def sentences(paragraph: str) -> list[str]:
    """Splits a paragraph into sentences, keeping closing quotes with the sentence they end."""
    out = []
    start = 0
    for m in _SENTENCE.finditer(paragraph):
        out.append(paragraph[start:m.start() + len(m.group(0).rstrip())].strip())
        start = m.end()
    out.append(paragraph[start:].strip())
    return [s for s in out if s]


@dataclass(frozen=True)
class Piece:
    text: str
    ends_paragraph: bool


def pieces(text: str, max_chars: int = 300) -> list[Piece]:
    """Groups each paragraph's sentences into pieces of at most `max_chars` (a longer sentence is
    split at commas, then spaces), so no piece runs across a paragraph break."""
    out: list[Piece] = []
    for para in [p.strip() for p in text.split("\n\n") if p.strip()]:
        current = ""
        group: list[str] = []
        for s in sentences(para):
            for part in _split_long(s, max_chars):
                if current and len(current) + 1 + len(part) > max_chars:
                    group.append(current)
                    current = part
                else:
                    current = f"{current} {part}".strip()
        if current:
            group.append(current)
        out += [Piece(t, i == len(group) - 1) for i, t in enumerate(group)]
    return out


def _split_long(sentence: str, max_chars: int) -> list[str]:
    if len(sentence) <= max_chars:
        return [sentence]
    parts, current = [], ""
    for word in re.split(r"(?<=,)\s+|\s+", sentence):
        if current and len(current) + 1 + len(word) > max_chars:
            parts.append(current)
            current = word
        else:
            current = f"{current} {word}".strip()
    return parts + ([current] if current else [])


def estimate_seconds(text: str, wpm: int = WORDS_PER_MINUTE) -> float:
    return max(0.4, len(text.split()) * 60 / wpm)


# ---- voices ----

class VoiceError(RuntimeError):
    pass


class SilentVoice:
    """Writes silence as long as the text would take to read at `wpm`. Used by tests and previews."""
    name = "silent"

    def __init__(self, wpm: int = WORDS_PER_MINUTE, rate: int = 22050):
        self.wpm, self.rate = wpm, rate

    def say(self, text: str, path: Path) -> None:
        frames = int(estimate_seconds(text, self.wpm) * self.rate)
        with wave.open(str(path), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(self.rate)
            w.writeframes(b"\x00\x00" * frames)


class WindowsVoice:
    """A voice built into Windows, through PowerShell's System.Speech (no install needed).
    `voice` is part of a voice's name, such as "David" or "Zira"; `rate` is -10 (slow) to 10 (fast)."""
    name = "windows"

    def __init__(self, voice: str = "", rate: int = 0, runner=subprocess.run):
        if not -10 <= rate <= 10:
            raise VoiceError("the Windows voice rate goes from -10 to 10")
        self.voice, self.rate, self.run = voice, rate, runner

    def script(self, text_file: Path, path: Path) -> str:
        q = lambda s: "'" + str(s).replace("'", "''") + "'"   # a PowerShell single-quoted string
        pick = (f"$v = $s.GetInstalledVoices() | Where-Object {{ $_.VoiceInfo.Name -like {q('*' + self.voice + '*')} }} | "
                f"Select-Object -First 1; if ($v) {{ $s.SelectVoice($v.VoiceInfo.Name) }}; ") if self.voice else ""
        return ("Add-Type -AssemblyName System.Speech; $s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
                f"{pick}$s.Rate = {int(self.rate)}; $s.SetOutputToWaveFile({q(path)}); "
                f"$s.Speak([IO.File]::ReadAllText({q(text_file)}, [Text.Encoding]::UTF8)); $s.Dispose()")

    def say(self, text: str, path: Path) -> None:
        # The text goes through a file, never the command line, so nothing in a story can run as code.
        text_file = path.with_suffix(".txt")
        text_file.write_text(text, encoding="utf-8")
        try:
            r = self.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", self.script(text_file, path)],
                         capture_output=True, text=True, timeout=120)
        except FileNotFoundError as e:
            raise VoiceError("PowerShell wasn't found; the windows voice only works on Windows") from e
        finally:
            text_file.unlink(missing_ok=True)
        if r.returncode != 0 or not path.exists():
            raise VoiceError(f"the Windows voice failed: {(r.stderr or r.stdout).strip()[:300]}")


class EspeakVoice:
    """eSpeak NG. `voice` is an eSpeak voice such as "en-us"; `rate` is words per minute."""
    name = "espeak"

    def __init__(self, voice: str = "en-us", rate: int = 160, runner=subprocess.run):
        self.voice, self.rate, self.run = voice or "en-us", rate or 160, runner
        self.exe = shutil.which("espeak-ng") or shutil.which("espeak") or "espeak-ng"

    def say(self, text: str, path: Path) -> None:
        try:
            r = self.run([self.exe, "-v", self.voice, "-s", str(int(self.rate)), "-w", str(path), "--stdin"],
                         input=text, capture_output=True, text=True, timeout=120)
        except FileNotFoundError as e:
            raise VoiceError("eSpeak NG isn't installed (https://github.com/espeak-ng/espeak-ng)") from e
        if r.returncode != 0 or not path.exists():
            raise VoiceError(f"eSpeak failed: {r.stderr.strip()[:300]}")


VOICES = {"windows": WindowsVoice, "espeak": EspeakVoice, "silent": SilentVoice}


def make_voice(engine: str, voice: str = "", rate: int | None = None):
    if engine not in VOICES:
        raise VoiceError(f"unknown voice engine {engine!r}; choose one of {', '.join(VOICES)}")
    if engine == "silent":
        return SilentVoice()
    return VOICES[engine](voice, rate) if rate is not None else VOICES[engine](voice)


# ---- joining the audio ----

@dataclass(frozen=True)
class Segment:
    start: float
    end: float
    text: str


def join_wavs(paths: list[Path], out: Path, gaps: list[float]) -> list[tuple[float, float]]:
    """Joins WAV files into one, with `gaps[i]` seconds of silence after file i. Every file must have
    the same format (a voice always produces the same one). Returns each file's (start, end) time."""
    times: list[tuple[float, float]] = []
    params = None
    t = 0.0
    with wave.open(str(out), "wb") as dst:
        for path, gap in zip(paths, gaps):
            with wave.open(str(path), "rb") as src:
                p = (src.getnchannels(), src.getsampwidth(), src.getframerate())
                if params is None:
                    params = p
                    dst.setnchannels(p[0]); dst.setsampwidth(p[1]); dst.setframerate(p[2])
                elif p != params:
                    raise VoiceError(f"{path.name} has a different audio format from the first piece")
                frames = src.readframes(src.getnframes())
                length = src.getnframes() / p[2]
            dst.writeframes(frames)
            times.append((round(t, 3), round(t + length, 3)))
            silence = int(gap * params[2]) * params[0] * params[1]
            dst.writeframes(b"\x00" * silence)
            t += length + int(gap * params[2]) / params[2]
    return times


@dataclass(frozen=True)
class Narration:
    audio: Path
    segments: list[Segment]

    @property
    def seconds(self) -> float:
        return self.segments[-1].end if self.segments else 0.0

    def save(self, path: Path) -> None:
        path.write_text(json.dumps({"audio": self.audio.name, "segments": [asdict(s) for s in self.segments]}, indent=1),
                        encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> "Narration":
        d = json.loads(path.read_text(encoding="utf-8"))
        return cls(path.parent / d["audio"], [Segment(**s) for s in d["segments"]])


def narrate(text: str, voice, folder: Path, pause: float = 0.35, paragraph_pause: float = 0.8,
            max_chars: int = 300, progress=lambda done, total: None) -> Narration:
    """Reads `text` aloud into folder/narration.wav and saves the timings to folder/narration.json."""
    folder.mkdir(parents=True, exist_ok=True)
    ps = pieces(text, max_chars)
    if not ps:
        raise VoiceError("there's no text to narrate")
    with tempfile.TemporaryDirectory(dir=folder) as tmp:
        files = []
        for i, p in enumerate(ps):
            f = Path(tmp) / f"{i:05}.wav"
            voice.say(p.text, f)
            files.append(f)
            progress(i + 1, len(ps))
        gaps = [paragraph_pause if p.ends_paragraph else pause for p in ps]
        gaps[-1] = 0.5
        times = join_wavs(files, folder / "narration.wav", gaps)
    result = Narration(folder / "narration.wav", [Segment(s, e, p.text) for (s, e), p in zip(times, ps)])
    result.save(folder / "narration.json")
    return result
