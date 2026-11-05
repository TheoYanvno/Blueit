"""The video: the pictures shown in turn, the narration as the sound, and the captions burned in,
made with FFmpeg into output/<story>/full.mp4.

Every picture is scaled to fill the frame and cropped to fit (nothing is stretched), the default
frame is upright 1080×1920 for phones (set video_size = "1920x1080" for widescreen), and the result
is H.264 video with AAC sound, which every site and phone plays.
"""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

CAPTION_STYLE = ("FontName=Arial,FontSize=11,Bold=1,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,"
                 "BorderStyle=1,Outline=2,Shadow=0,Alignment=2,MarginV=60,WrapStyle=2")


class VideoError(RuntimeError):
    pass


def ffmpeg_path() -> str:
    exe = shutil.which("ffmpeg")
    if not exe:
        raise VideoError("FFmpeg isn't installed. Get it from https://ffmpeg.org/download.html "
                         "(on Windows: winget install ffmpeg), then open a new terminal.")
    return exe


def parse_size(size: str) -> tuple[int, int]:
    m = re.fullmatch(r"\s*(\d{3,4})\s*[x×]\s*(\d{3,4})\s*", size or "")
    if not m:
        raise VideoError(f"video_size should look like 1080x1920, not {size!r}")
    w, h = int(m.group(1)), int(m.group(2))
    if w % 2 or h % 2:
        raise VideoError("video_size needs even numbers (H.264 requires it)")
    return w, h


def _quote(path: Path) -> str:
    """A path for FFmpeg's concat list: single-quoted, with any ' written as '\\''."""
    return "'" + str(Path(path).resolve()).replace("\\", "/").replace("'", "'\\''") + "'"


def concat_list(shots) -> str:
    """FFmpeg's concat-demuxer list: each picture and how long it stays. The last picture is listed
    again at the end, which the concat demuxer needs for the last duration to count."""
    lines = []
    for s in shots:
        lines += [f"file {_quote(s.picture)}", f"duration {s.seconds:.3f}"]
    if shots:
        lines.append(f"file {_quote(shots[-1].picture)}")
    return "\n".join(lines) + "\n"


def video_filter(size: tuple[int, int], captions: str | None) -> str:
    w, h = size
    vf = f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},setsar=1,fps=30,format=yuv420p"
    if captions:
        # run from the story folder, so the captions file is a plain name with nothing to escape
        vf += f",subtitles={captions}:force_style='{CAPTION_STYLE}'"
    return vf


def build_command(exe: str, size: tuple[int, int], captions: str | None, out: str = "full.mp4") -> list[str]:
    return [exe, "-hide_banner", "-loglevel", "error", "-y",
            "-f", "concat", "-safe", "0", "-i", "shots.txt",
            "-i", "narration.wav",
            "-vf", video_filter(size, captions),
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "160k", "-shortest", "-movflags", "+faststart", out]


def make_video(folder: Path, shots, size: str = "1080x1920", captions: bool = True, runner=subprocess.run,
               exe: str | None = None) -> Path:
    """Writes folder/full.mp4 from folder/narration.wav, the shots, and folder/captions.srt if
    `captions` is on. Returns the video's path."""
    folder = Path(folder)
    if not (folder / "narration.wav").exists():
        raise VideoError(f"{folder.name} has no narration yet. Run `blueit narrate` first.")
    if captions and not (folder / "captions.srt").exists():
        raise VideoError(f"{folder.name} has no captions.srt")
    (folder / "shots.txt").write_text(concat_list(shots), encoding="utf-8")
    cmd = build_command(exe or ffmpeg_path(), parse_size(size), "captions.srt" if captions else None)
    r = runner(cmd, cwd=folder, capture_output=True, text=True)
    if r.returncode != 0:
        raise VideoError(f"FFmpeg couldn't make the video: {(r.stderr or '').strip()[-400:]}")
    return folder / "full.mp4"


def duration(path: Path, runner=subprocess.run) -> float:
    """A media file's length in seconds, read with ffprobe."""
    probe = shutil.which("ffprobe") or "ffprobe"
    r = runner([probe, "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(path)],
               capture_output=True, text=True)
    try:
        return float(r.stdout.strip())
    except ValueError as e:
        raise VideoError(f"couldn't read the length of {Path(path).name}") from e
