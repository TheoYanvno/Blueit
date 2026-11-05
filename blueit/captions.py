"""Captions: the narration's timed pieces turned into short on-screen lines, saved as an SRT file.

A piece can be a few sentences long, too much for the screen at once, so each piece is split into
captions of at most `max_lines` lines of `max_chars` characters, and the piece's time is shared
between them by how many words each has (people read about as fast as the narrator talks).
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Caption:
    start: float
    end: float
    lines: tuple[str, ...]

    @property
    def text(self) -> str:
        return "\n".join(self.lines)


def wrap(text: str, max_chars: int = 32) -> list[str]:
    """Breaks text into lines of at most max_chars, between words (a single longer word gets its own line)."""
    lines, current = [], ""
    for word in text.split():
        if current and len(current) + 1 + len(word) > max_chars:
            lines.append(current)
            current = word
        else:
            current = f"{current} {word}".strip()
    return lines + ([current] if current else [])


def captions(segments, max_chars: int = 32, max_lines: int = 2) -> list[Caption]:
    out: list[Caption] = []
    for seg in segments:
        lines = wrap(seg.text, max_chars)
        groups = [tuple(lines[i:i + max_lines]) for i in range(0, len(lines), max_lines)]
        words = [sum(len(l.split()) for l in g) for g in groups]
        total = sum(words) or 1
        t = seg.start
        for i, (g, n) in enumerate(zip(groups, words)):
            end = seg.end if i == len(groups) - 1 else round(t + (seg.end - seg.start) * n / total, 3)
            out.append(Caption(round(t, 3), round(end, 3), g))
            t = end
    return out


def shift(caps: list[Caption], start: float, end: float) -> list[Caption]:
    """The captions between start and end, moved so `start` becomes 0 (for one part of the video)."""
    out = []
    for c in caps:
        if c.end <= start or c.start >= end:
            continue
        out.append(Caption(round(max(c.start, start) - start, 3), round(min(c.end, end) - start, 3), c.lines))
    return out


def timestamp(seconds: float) -> str:
    ms = int(round(seconds * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02}:{m:02}:{s:02},{ms:03}"


def to_srt(caps: list[Caption]) -> str:
    return "".join(f"{i}\n{timestamp(c.start)} --> {timestamp(c.end)}\n{c.text}\n\n" for i, c in enumerate(caps, 1))


def write_srt(caps: list[Caption], path: Path) -> Path:
    Path(path).write_text(to_srt(caps), encoding="utf-8")
    return Path(path)
