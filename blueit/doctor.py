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
    folder = Path(cfg.images)
    pics = [p for p in folder.iterdir() if p.suffix.lower() in PICTURE_TYPES] if folder.is_dir() else []
    out.append(Check("Pictures", bool(pics), f"{len(pics)} in {folder}" if pics else
                     f"none yet: put .jpg, .png or .webp files in {folder}/"))
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
