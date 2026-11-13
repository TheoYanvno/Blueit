"""`blueit doctor`: checks everything Blueit needs and says how to fix what's missing, before you
spend time on a long narration.
"""
from __future__ import annotations

import shutil
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .config import Config


@dataclass(frozen=True)
class Check:
    name: str
    ok: bool
    detail: str


def run_checks(cfg: Config, env: str = ".env", which=shutil.which, voice_factory=None,
               python=sys.version_info, environ=None) -> list[Check]:
    from .library import Library
    from .narrate import VoiceError, make_voice
    from .pictures import PICTURE_TYPES
    from .reddit import load_env
    out = []
    out.append(Check("Python 3.11 or newer", tuple(python[:2]) >= (3, 11), f"you have {python[0]}.{python[1]}"))
    ff, fp = which("ffmpeg"), which("ffprobe")
    out.append(Check("FFmpeg", bool(ff and fp), ff or "not found: install it from https://ffmpeg.org/download.html "
                                                   "(Windows: winget install ffmpeg), then open a new terminal"))
    try:
        voice = (voice_factory or (lambda: make_voice(cfg.voice_engine, cfg.voice, cfg.voice_rate)))()
        with tempfile.TemporaryDirectory() as d:
            voice.say("Testing one two three.", Path(d) / "test.wav")
            ok = (Path(d) / "test.wav").stat().st_size > 44
        out.append(Check(f"Voice ({cfg.voice_engine})", ok, "speaks" if ok else "made an empty file"))
    except (VoiceError, OSError) as e:
        out.append(Check(f"Voice ({cfg.voice_engine})", False, str(e)))
    from .moods import SOUND_TYPES, counts, ensure_folders
    folder = Path(cfg.images)
    music = Path(getattr(cfg, "music", "music"))
    try:
        ensure_folders(folder, music)            # images/scary/, music/scary/, ... so there's a place for each
    except OSError:
        pass
    pics = counts(folder, PICTURE_TYPES)
    total = sum(pics.values())
    by_kind = ", ".join(f"{k} {n}" for k, n in pics.items() if k and n)
    out.append(Check("Pictures", total > 0, (f"{total} in {folder}" + (f" ({by_kind})" if by_kind else "")) if total else
                     f"none yet: put .jpg, .png or .webp files in {folder}/ or its mood folders ({folder}/scary/, ...)"))
    sounds = counts(music, SOUND_TYPES)
    s_total = sum(sounds.values())
    s_kind = ", ".join(f"{k} {n}" for k, n in sounds.items() if k and n)
    out.append(Check("Background sound (optional)", True, (f"{s_total} in {music}" + (f" ({s_kind})" if s_kind else "")) if s_total else
                     f"none, so videos have the voice only; add .mp3 or .wav files to {music}/scary/, {music}/funny/, ..."))
    keys = load_env(env, environ)
    has = all(keys.get(k) for k in ("REDDIT_CLIENT_ID", "REDDIT_CLIENT_SECRET"))
    out.append(Check("Reddit app keys", has, f"found in {env}" if has else
                     f"missing: copy .env.example to {env} and add your app's id and secret (see Reddit access)"))
    if Path(cfg.library).exists():
        with Library(cfg.library) as lib:
            c = lib.counts()
        out.append(Check("Story library", True, f"{c['new']} waiting, {c['narrated']} narrated"))
    else:
        out.append(Check("Story library", True, "empty so far (run `blueit fetch` or `blueit ui`)"))
    try:
        Path(cfg.output).mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=cfg.output):
            pass
        out.append(Check("Output folder", True, f"{cfg.output} is writable"))
    except OSError as e:
        out.append(Check("Output folder", False, f"can't write to {cfg.output}: {e}"))
    return out


def report(checks: list[Check]) -> str:
    lines = [f"{'✔' if c.ok else '✘'} {c.name}: {c.detail}" for c in checks]
    bad = sum(not c.ok for c in checks)
    lines.append("Everything's ready." if not bad else f"{bad} {'thing needs' if bad == 1 else 'things need'} fixing.")
    return "\n".join(lines)
