"""One folder per story under output/, holding everything made for it:

  output/<id>-<title-slug>/
    script.txt        the exact text that is read aloud (an intro line, then the cleaned story)
    credit.txt        who wrote it and where, to put in the video's description
    narration.wav     the voice
    narration.json    when each piece of text is spoken (for captions)
    full.mp4, part-01.mp4, …   the videos (made by the video steps)
"""
from __future__ import annotations

import re
import unicodedata
from pathlib import Path

from .clean import clean


def slug(title: str, max_len: int = 50) -> str:
    """A safe folder name from a title: plain ASCII letters and digits joined by dashes."""
    text = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode()
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    return (text[:max_len].rstrip("-")) or "story"


def folder_for(output: Path, entry) -> Path:
    return Path(output) / f"{re.sub(r'[^a-z0-9]', '', entry.id.lower())}-{slug(entry.title)}"


def intro(entry) -> str:
    """The first thing the narrator says: the title and who wrote it."""
    title = re.sub(r"\s*[\[(](?:final|finished|complete|\d+\s*/\s*\d+)[\])]\s*", " ", entry.title, flags=re.I).strip()
    return f"{title}. Written by {entry.author}, on r/{entry.subreddit}."


def script(entry) -> str:
    return intro(entry) + "\n\n" + clean(entry.body)


def credit(entry) -> str:
    lines = [f"\"{entry.title}\" by u/{entry.author}", f"r/{entry.subreddit}: {entry.url}"]
    if entry.parts:
        lines.append("Parts:")
        lines += [f"  {i}. {link}" for i, link in enumerate(entry.parts, 1)]
    lines.append("Ask the author before posting this video publicly, and keep this credit with it.")
    return "\n".join(lines) + "\n"


def prepare(output: Path, entry) -> Path:
    """Creates the story's folder with script.txt and credit.txt, and returns the folder."""
    folder = folder_for(output, entry)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "script.txt").write_text(script(entry), encoding="utf-8")
    (folder / "credit.txt").write_text(credit(entry), encoding="utf-8")
    return folder
