"""Mood folders: pictures and background sound that match the kind of story.

images/ and music/ each get one folder per kind of story in categories.py (scary, paranormal,
revenge, work, family, funny). A story from r/nosleep is a scary story, so its video uses pictures
from images/scary/ and a sound from music/scary/. A story's own output/<story>/images/ (or music/)
folder comes first; files right in images/ or music/ are the fallback for any kind.
"""
from __future__ import annotations

import re
from pathlib import Path

from .categories import STORY_TYPES

KINDS = list(STORY_TYPES)
SOUND_TYPES = {".mp3", ".m4a", ".aac", ".wav", ".ogg", ".flac"}


def kind_for_subreddit(subreddit: str) -> str:
    sub = (subreddit or "").removeprefix("r/").lower()
    for kind, info in STORY_TYPES.items():
        if sub in (s.lower() for s in info["subreddits"]):
            return kind
    return ""


def story_kind(folder: Path) -> str:
    """The kind of a prepared story, from the r/subreddit line in its credit.txt ('' if unknown)."""
    credit = Path(folder) / "credit.txt"
    if credit.exists():
        m = re.search(r"^r/(\w+):", credit.read_text(encoding="utf-8"), re.M)
        if m:
            return kind_for_subreddit(m.group(1))
    return ""


def ensure_folders(*roots: Path) -> list[Path]:
    """Creates images/<kind>/ and music/<kind>/ for every kind, so there's a place for each. Returns
    the folders it made."""
    made = []
    for root in roots:
        for kind in KINDS:
            f = Path(root) / kind
            if not f.is_dir():
                f.mkdir(parents=True, exist_ok=True)
                made.append(f)
    return made


def files_in(folder: Path, types: set[str]) -> list[Path]:
    folder = Path(folder)
    if not folder.is_dir():
        return []
    return sorted((p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in types), key=lambda p: p.name.lower())


def search_order(story_folder: Path, root: Path, kind: str, own: str) -> list[Path]:
    """Where to look, first match wins: the story's own folder, the kind's folder, then the root."""
    order = [Path(story_folder) / own]
    if kind:
        order.append(Path(root) / kind)
    order.append(Path(root))
    return order


def find_sound(story_folder: Path, music_root: Path, kind: str = "") -> Path | None:
    """One background sound for the story (the same one every time for the same story), or None."""
    for folder in search_order(story_folder, music_root, kind, "music"):
        found = files_in(folder, SOUND_TYPES)
        if found:
            return found[sum(map(ord, Path(story_folder).name)) % len(found)]
    return None


def counts(root: Path, types: set[str]) -> dict[str, int]:
    """How many files each kind's folder has, plus '' for the root folder itself."""
    out = {"": len(files_in(root, types))}
    for kind in KINDS:
        out[kind] = len(files_in(Path(root) / kind, types))
    return out
