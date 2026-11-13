"""The steps after narration, in order, for one story folder: captions, the picture plan, the full
video and the 1-minute parts. The `video` and `run` commands and the web page all call `make`."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .captions import captions, write_srt
from .narrate import Narration
from .parts import make_parts
from .moods import find_sound, story_kind
from .pictures import find_pictures, plan
from .video import VideoError, make_video


@dataclass(frozen=True)
class Made:
    folder: Path
    full: Path
    parts: list[Path]
    seconds: float
    pictures: int


def make(folder: Path, cfg, log=print, runner=None) -> Made:
    folder = Path(folder)
    if not (folder / "narration.json").exists():
        raise VideoError(f"{folder.name} hasn't been narrated yet. Run `blueit narrate` first.")
    n = Narration.load(folder / "narration.json")
    caps = captions(n.segments)
    write_srt(caps, folder / "captions.srt")
    kind = story_kind(folder)
    pictures = find_pictures(folder, cfg.images, kind)
    sound = find_sound(folder, getattr(cfg, "music", Path("music")), kind) if getattr(cfg, "music_volume", 0) > 0 else None
    shots = plan(pictures, n.segments, cfg.picture_seconds, folder.name if cfg.shuffle_pictures else None)
    log(f"  {len(caps)} captions, {len(shots)} picture changes from {len(pictures)} pictures"
        f"{f' ({kind})' if kind else ''}{f', background: {sound.name}' if sound else ''}")
    extra = {"runner": runner} if runner else {}
    full = make_video(folder, shots, cfg.video_size, cfg.captions, sound=sound,
                      sound_volume=getattr(cfg, "music_volume", 0.12), **extra)
    log(f"  full video → {full}")
    parts = make_parts(folder, n.segments, cfg.clip_seconds, **extra)
    log(f"  {len(parts)} {'part' if len(parts) == 1 else 'parts'} of up to {cfg.clip_seconds} s")
    return Made(folder, full, parts, n.seconds, len(pictures))
