"""1-minute parts: the full video cut into pieces of at most `clip_seconds`, for Shorts, Reels and
TikTok. Cuts only fall between sentences (where a narration piece ends), so no part starts or ends
in the middle of a line; a part only runs over the limit if one piece is longer than the limit.
The captions are already in full.mp4, so every part keeps them.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from .video import VideoError, ffmpeg_path


def cut_points(segments, clip_seconds: float = 60) -> list[tuple[float, float]]:
    """(start, end) for each part. A part ends at the last piece boundary that keeps it within
    clip_seconds; the last part runs to the end of the narration."""
    if clip_seconds <= 0:
        raise VideoError("clip_seconds must be more than 0")
    if not segments:
        return []
    total = segments[-1].end
    parts, start = [], 0.0
    while total - start > clip_seconds:
        fits = [s.end for s in segments if start < s.end <= start + clip_seconds]
        end = fits[-1] if fits else next(s.end for s in segments if s.end > start)   # one very long piece
        parts.append((round(start, 3), round(end, 3)))
        start = end
    if total - start > 0.01:
        parts.append((round(start, 3), round(total, 3)))
    return parts


def part_name(i: int) -> str:
    return f"part-{i:02}.mp4"


def make_parts(folder: Path, segments, clip_seconds: float = 60, runner=subprocess.run,
               exe: str | None = None) -> list[Path]:
    """Cuts folder/full.mp4 into folder/part-01.mp4, part-02.mp4, … and removes old parts first."""
    folder = Path(folder)
    full = folder / "full.mp4"
    if not full.exists():
        raise VideoError(f"{folder.name} has no full.mp4 yet")
    for old in folder.glob("part-*.mp4"):
        old.unlink()
    exe = exe or ffmpeg_path()
    out = []
    for i, (start, end) in enumerate(cut_points(segments, clip_seconds), 1):
        path = folder / part_name(i)
        # re-encoding (not copying) makes every part start exactly on its cut, with a key frame
        cmd = [exe, "-hide_banner", "-loglevel", "error", "-y", "-ss", f"{start:.3f}", "-to", f"{end:.3f}",
               "-i", "full.mp4", "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p",
               "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", path.name]
        r = runner(cmd, cwd=folder, capture_output=True, text=True)
        if r.returncode != 0:
            raise VideoError(f"FFmpeg couldn't cut part {i}: {(r.stderr or '').strip()[-300:]}")
        out.append(path)
    return out
