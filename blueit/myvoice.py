"""My voice: narration in your own voice, cloned from a recording you make once.

You read a script out loud for about five minutes (Blueit's page records it in your browser; nothing
is uploaded anywhere), and Blueit saves the recording in voices/<name>/. From it, Blueit cuts the
clearest 15 seconds as the "prompt" the voice engine copies. The longer recording is kept so a
better clip can be picked later and so future engines that learn from more audio can use it.

The engine is Chatterbox by Resemble AI (MIT license, commercial use allowed), an optional add-on:
it's a large download (PyTorch and a model of about 2 GB), so it isn't inside Blueit.exe. Install it
with `pip install chatterbox-tts`. Chatterbox marks everything it makes with an inaudible watermark
(PerTh), and every story narrated with it gets an "AI-generated narration" line in its credit.txt,
because TikTok and YouTube ask creators to label AI voices.

Only your own voice: saving a recording needs a tick that it's yours, and Blueit won't use a voice
without it. Cloning someone else's voice without permission isn't allowed.
"""
from __future__ import annotations

import json
import re
import shutil
import time
import wave
from array import array
from dataclasses import asdict, dataclass
from pathlib import Path

from .narrate import VoiceError

PROMPT_SECONDS = 15        # Chatterbox copies a voice from a 5 to 20 second clip
MIN_SECONDS = 20           # shortest recording Blueit accepts (5 minutes is better)
SUGGESTED_SECONDS = 300
AI_CREDIT = ("Narration: AI-generated voice (the creator's own voice, cloned with Chatterbox). "
             "Label the video as AI-generated when you post it; TikTok and YouTube ask for this.")
INSTALL_HINT = ("the My voice add-on isn't installed: run `pip install chatterbox-tts` (a large download, "
                "about 2 GB with its model; a graphics card makes it much faster)")

# About 750 words, read in about five minutes. It mixes questions, exclamations, whispers, numbers,
# names and every common English sound, so the clip Blueit picks carries how you really talk.
SCRIPT = """\
Hi, this is my voice, and I'm recording it so Blueit can tell stories the way I would tell them. I'll read at my normal speed, like I'm talking to a friend across the table.

Let's start with something easy. One, two, three, four, five. Six, seven, eight, nine, ten. Twenty-one. Fifty-five. One hundred and twelve. The year was 1987, and the address was 4319 Willow Creek Road.

The old house at the end of the street had been empty for years. Nobody remembered who lived there last. Some people said it was a doctor named Harold Finch. Others swore it was a family of five who left in the middle of the night, with dinner still on the table. Which one was true? Nobody could say.

My grandmother used to warn us about it. "Don't you go near that place," she'd say, pointing a crooked finger. "You hear me? Not after dark." We'd nod, and then, of course, we'd go anyway.

I remember the first time. It was October, cold enough to see your breath. Jake had a flashlight. Maria brought her phone. I brought nothing but nerves. The gate squeaked when we pushed it. The porch boards groaned under our shoes. Somewhere inside, something dripped. Drip. Drip. Drip.

"Hello?" Jake called. His voice echoed down the hallway and came back thinner.

Nothing.

Then, very quietly, from upstairs: a thump. Then another. Then footsteps, slow and heavy, crossing the ceiling right above our heads.

We didn't scream. We didn't even breathe. We just looked at each other, and then we ran! Down the steps, across the yard, through the gate, all the way to the corner store, where the lights were bright and the man behind the counter asked if we were okay.

Were we? I'm still not sure.

Now let me read some lines with different feelings, the way a story needs them.

Happy: That's the best news I've heard all week! I can't believe it actually worked!

Worried: I don't know. Something about this feels wrong. Are you sure we should keep going?

Angry: No. Absolutely not. I told you three times already, and you still didn't listen.

Whispering: Stay very still. Don't make a sound. It's right outside the door.

Tired: It was late, almost two in the morning, and all I wanted was to sleep.

Surprised: Wait, what? You're telling me she was here the whole time?

Here are some words with sounds that are easy to mix up: thin and thing, sheep and cheap, very and berry, light and right, wide and white, measure and treasure, judge and church, ship and chip, vision and fusion. Peter Piper picked a peck of pickled peppers. She sells seashells by the seashore. Red leather, yellow leather.

And some names and places: Samantha, Oliver, Priya, Mateo, Chloe, Darius, Hannah, Kenji. Atlanta, Seattle, Orlando, Boston, Phoenix, New Orleans, Minneapolis.

A few questions, because stories are full of them. Where were you on the night of the storm? Why didn't anyone call the police? How long had the lights been flickering? Who left the back door open? What would you have done?

Let me try a longer sentence, the kind that goes on for a while, with a pause here, and another one there, before it finally, after all that waiting, comes to an end.

The next morning, everything looked normal. The sun was out. Dogs were barking. Mr. Alvarez was mowing his lawn like he did every Saturday. I walked past the old house on my way to school, and I almost convinced myself we'd imagined the whole thing.

Almost.

Because in the upstairs window, the one that had been boarded up for as long as anyone could remember, the boards were gone. And the curtain moved.

I told my grandmother that afternoon. She didn't laugh. She didn't tell me I was making it up. She just set down her coffee, looked at me for a long moment, and said, "Then it's back."

That's where I'll stop. Thank you for listening. This has been my voice, reading for Blueit, and I agree to Blueit using this recording to narrate my videos.
"""


def slug(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return s[:40] or "my-voice"


@dataclass
class SavedVoice:
    slug: str
    name: str
    created: str
    seconds: float
    own_voice: bool
    engine: str = "chatterbox"

    def folder(self, root: Path) -> Path:
        return Path(root) / self.slug


def wav_info(path: Path) -> tuple[int, int, int, int]:
    """(channels, sample width, rate, frames) of a WAV file, or VoiceError if it isn't one."""
    try:
        with wave.open(str(path), "rb") as w:
            return w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()
    except (wave.Error, EOFError) as e:
        raise VoiceError("that recording isn't a WAV file Blueit can read") from e


def best_clip(src: Path, dst: Path, seconds: float = PROMPT_SECONDS, step: float = 0.5) -> tuple[float, float]:
    """Copies the clearest `seconds` of a 16-bit WAV into `dst`: the stretch with the most steady
    speech, where loud-enough half seconds are counted and long silences (pauses, page turns, the
    first breath) are avoided. Returns the (start, end) it chose, in seconds."""
    channels, width, rate, frames = wav_info(src)
    if width != 2:
        raise VoiceError("the recording must be 16-bit WAV")
    with wave.open(str(src), "rb") as w:
        data = array("h", w.readframes(frames))
    hop = max(1, int(rate * step)) * channels
    energy = []
    for i in range(0, len(data), hop):
        chunk = data[i:i + hop:max(1, channels * 4)]          # every 4th sample is plenty for loudness
        energy.append(sum(x * x for x in chunk) / max(1, len(chunk)))
    if not energy:
        raise VoiceError("the recording is empty")
    window = max(1, min(len(energy), int(seconds / step)))
    loud = sorted(energy)[len(energy) // 2] * 0.5 + 1           # half the median: below this is a pause
    voiced = [1 if e > loud else 0 for e in energy]
    best, best_at = -1, 0
    run = sum(voiced[:window])
    for start in range(0, len(energy) - window + 1):
        if start:
            run += voiced[start + window - 1] - voiced[start - 1]
        if run > best:
            best, best_at = run, start
    first = best_at * hop
    last = min(len(data), first + window * hop)
    with wave.open(str(dst), "wb") as out:
        out.setnchannels(channels)
        out.setsampwidth(2)
        out.setframerate(rate)
        out.writeframes(data[first:last].tobytes())
    return round(first / channels / rate, 2), round(last / channels / rate, 2)


class VoiceStore:
    """Saved voices in voices/<slug>/ (recording.wav, prompt.wav, voice.json), and which one is the
    default in voices/voices.json."""

    def __init__(self, root: Path = Path("voices")):
        self.root = Path(root)

    def _index(self) -> dict:
        try:
            return json.loads((self.root / "voices.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _write_index(self, data: dict) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "voices.json").write_text(json.dumps(data, indent=1), encoding="utf-8")

    def list(self) -> list[SavedVoice]:
        out = []
        if self.root.is_dir():
            for f in sorted(self.root.glob("*/voice.json")):
                try:
                    out.append(SavedVoice(**json.loads(f.read_text(encoding="utf-8"))))
                except (OSError, ValueError, TypeError):
                    continue
        return out

    def get(self, key: str) -> SavedVoice | None:
        key = (key or "").strip()
        for v in self.list():
            if key in (v.slug, v.name) or slug(key) == v.slug:
                return v
        return None

    @property
    def default(self) -> SavedVoice | None:
        chosen = self.get(self._index().get("default", ""))
        if chosen:
            return chosen
        voices = self.list()
        return voices[0] if len(voices) == 1 else None

    def set_default(self, key: str) -> SavedVoice:
        v = self.get(key)
        if not v:
            raise VoiceError(f"there's no saved voice called {key!r}")
        self._write_index({**self._index(), "default": v.slug})
        return v

    def save(self, name: str, wav: Path | bytes, own_voice: bool, now=time.time) -> SavedVoice:
        """Saves a recording as a new voice. `own_voice` must be True: Blueit only clones the voice of
        the person using it."""
        if not own_voice:
            raise VoiceError("tick that this recording is your own voice; Blueit only clones your own voice")
        name = " ".join((name or "My voice").split())[:60]
        s = slug(name)
        n = 2
        while (self.root / s).exists():
            s = f"{slug(name)[:36]}-{n}"
            n += 1
        folder = self.root / s
        folder.mkdir(parents=True)
        try:
            rec = folder / "recording.wav"
            if isinstance(wav, (bytes, bytearray)):
                rec.write_bytes(wav)
            else:
                shutil.copyfile(wav, rec)
            channels, width, rate, frames = wav_info(rec)
            seconds = frames / rate
            if seconds < MIN_SECONDS:
                raise VoiceError(f"the recording is {seconds:.0f} seconds; record at least {MIN_SECONDS} "
                                 f"(about {SUGGESTED_SECONDS // 60} minutes is best)")
            best_clip(rec, folder / "prompt.wav")
            v = SavedVoice(s, name, time.strftime("%Y-%m-%d %H:%M", time.localtime(now())), round(seconds, 1), True)
            (folder / "voice.json").write_text(json.dumps(asdict(v), indent=1), encoding="utf-8")
        except Exception:
            shutil.rmtree(folder, ignore_errors=True)
            raise
        if not self._index().get("default"):
            self._write_index({**self._index(), "default": v.slug})
        return v

    def rename(self, key: str, new_name: str) -> SavedVoice:
        v = self.get(key)
        if not v:
            raise VoiceError(f"there's no saved voice called {key!r}")
        v.name = " ".join(new_name.split())[:60] or v.name
        (v.folder(self.root) / "voice.json").write_text(json.dumps(asdict(v), indent=1), encoding="utf-8")
        return v

    def delete(self, key: str) -> None:
        v = self.get(key)
        if not v:
            raise VoiceError(f"there's no saved voice called {key!r}")
        folder = v.folder(self.root).resolve()
        if folder.parent != self.root.resolve():
            raise VoiceError("that voice isn't inside the voices folder")
        shutil.rmtree(folder)
        index = self._index()
        if index.get("default") == v.slug:
            index.pop("default")
            self._write_index(index)


def load_chatterbox():
    """Loads Chatterbox once (on a graphics card when there is one). VoiceError if it isn't installed."""
    try:
        import torch
        from chatterbox.tts import ChatterboxTTS
    except ImportError as e:
        raise VoiceError(INSTALL_HINT) from e
    device = "cuda" if torch.cuda.is_available() else ("mps" if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available() else "cpu")
    return ChatterboxTTS.from_pretrained(device=device)


def addon_installed() -> bool:
    import importlib.util
    return importlib.util.find_spec("chatterbox") is not None


def write_samples(path: Path, samples, rate: int) -> None:
    """Writes float samples (-1 to 1, a list or a tensor) as a 16-bit mono WAV."""
    if hasattr(samples, "detach"):
        samples = samples.detach().cpu().reshape(-1).tolist()
    elif hasattr(samples, "tolist"):
        samples = list(samples.reshape(-1).tolist()) if hasattr(samples, "reshape") else samples.tolist()
    pcm = array("h", (int(max(-1.0, min(1.0, float(x))) * 32767) for x in samples))
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(int(rate))
        w.writeframes(pcm.tobytes())


class MyVoice:
    """A narrator that speaks in a saved voice. `voice` is a saved voice's name (empty means the
    default one); `rate` isn't used. `model_factory` loads the engine (tests pass a fake)."""
    name = "myvoice"
    ai_generated = True

    def __init__(self, voice: str = "", rate=None, root: Path = Path("voices"), model_factory=load_chatterbox,
                 exaggeration: float = 0.5):
        store = VoiceStore(root)
        self.saved = store.get(voice) if voice else store.default
        if not self.saved:
            raise VoiceError("no saved voice to narrate with: open Record my voice in `blueit ui` and record one"
                             if not store.list() else f"there's no saved voice called {voice!r}; saved: "
                             + ", ".join(v.name for v in store.list()))
        if not self.saved.own_voice:
            raise VoiceError(f"{self.saved.name} wasn't confirmed as your own voice, so Blueit won't use it")
        self.prompt = self.saved.folder(root) / "prompt.wav"
        if not self.prompt.exists():
            raise VoiceError(f"{self.saved.name}'s prompt.wav is missing; record the voice again")
        self.model_factory, self.exaggeration, self._model = model_factory, exaggeration, None

    @property
    def model(self):
        if self._model is None:
            self._model = self.model_factory()
        return self._model

    def say(self, text: str, path: Path) -> None:
        m = self.model
        try:
            wav = m.generate(text, audio_prompt_path=str(self.prompt), exaggeration=self.exaggeration)
        except Exception as e:  # noqa: BLE001 - any engine failure becomes a VoiceError the page can show
            raise VoiceError(f"My voice couldn't read that piece: {e}") from e
        write_samples(path, wav, m.sr)


def add_ai_credit(folder: Path) -> None:
    """Adds the AI-generated narration line to a story's credit.txt (once)."""
    credit = Path(folder) / "credit.txt"
    text = credit.read_text(encoding="utf-8") if credit.exists() else ""
    if AI_CREDIT not in text:
        credit.write_text(text + ("" if text.endswith("\n") or not text else "\n") + AI_CREDIT + "\n", encoding="utf-8")


def set_setting(path: Path, key: str, value) -> None:
    """Sets one setting in blueit.toml, keeping everything else (and its comments) as it is."""
    path = Path(path)
    v = json.dumps(value) if isinstance(value, str) else ("true" if value is True else "false" if value is False else str(value))
    text = path.read_text(encoding="utf-8") if path.exists() else "[blueit]\n"
    line = re.compile(rf"^{re.escape(key)}\s*=.*?(\s+#.*)?$", re.M)
    if line.search(text):
        text = line.sub(lambda m: f"{key} = {v}{m.group(1) or ''}", text, count=1)
    else:
        if "[blueit]" not in text:
            text = "[blueit]\n" + text
        head, sep, rest = text.partition("[blueit]\n")
        nxt = re.search(r"^\[", rest, re.M)
        cut = nxt.start() if nxt else len(rest)
        body = rest[:cut]
        kept = body.rstrip("\n")
        tail = body[len(kept):] if nxt else ""          # keep the blank line before the next [section]
        text = head + sep + (kept + "\n" if kept else "") + f"{key} = {v}\n" + (tail[1:] if tail else "") + rest[cut:]
    path.write_text(text, encoding="utf-8")
