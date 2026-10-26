"""Decides whether a post is a fully finished story, ready to narrate.

A story counts as finished when it is a stand-alone story or the last part of a series, it is long
enough to be a real story, and nothing in it says more is coming. Every rule returns a reason, so
`blueit check` can explain why a post was skipped.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .story import Story

# Titles of series parts: "Part 2", "Pt. 3", "(2/5)", "[Part II]".
PART = re.compile(r"\b(?:part|pt\.?)\s*(\d+|[ivx]+)\b|\(\s*(\d+)\s*/\s*(\d+)\s*\)", re.I)
# Titles that mark the end of a series: "(Final)", "Part 5, Final", "The well: the conclusion".
# The word has to come after a bracket or separator, so "The last time I went camping" doesn't count.
FINAL = re.compile(r"[(\[:,|\-–—]\s*[^()\[\]]*?\b(?:final|finale|last part|conclusion|epilogue|the end)\b", re.I)
# Phrases that say the story isn't over yet.
UNFINISHED = re.compile(
    r"to be continued|\btbc\b|part \w+ (?:coming|soon|tomorrow)|will (?:update|post (?:more|the rest|part))"
    r"|(?:update|more) (?:soon|to come|coming)|stay tuned|next part|continued in|i'?ll (?:update|post (?:more|again))",
    re.I,
)
# Flairs story subreddits use for unfinished series.
UNFINISHED_FLAIRS = {"series", "ongoing", "series (ongoing)", "update", "unfinished"}
FINISHED_FLAIRS = {"series (finished)", "series - finished", "complete", "completed", "finished", "final"}


@dataclass(frozen=True)
class Verdict:
    ok: bool
    reason: str
    part: int | None = None  # set for series parts, e.g. 3 for "Part 3"
    final: bool = False


def _roman(s: str) -> int | None:
    vals = {"i": 1, "v": 5, "x": 10}
    s = s.lower()
    if not s or any(c not in vals for c in s):
        return None
    total = 0
    for a, b in zip(s, s[1:] + " "):
        v = vals[a]
        total += -v if b in vals and vals[b] > v else v
    return total


def series_part(title: str) -> tuple[int | None, int | None]:
    """Returns (part number, total parts) found in a title, or (None, None)."""
    m = PART.search(title)
    if not m:
        return None, None
    if m.group(1):
        n = m.group(1)
        return (int(n) if n.isdigit() else _roman(n)), None
    return int(m.group(2)), int(m.group(3))


def check(story: Story, min_words: int = 400, max_words: int = 12000, allow_nsfw: bool = False) -> Verdict:
    if story.removed or not story.body.strip():
        return Verdict(False, "removed, deleted or has no text")
    if story.over_18 and not allow_nsfw:
        return Verdict(False, "marked NSFW")
    if story.words < min_words:
        return Verdict(False, f"too short ({story.words} words, need {min_words})")
    if story.words > max_words:
        return Verdict(False, f"too long ({story.words} words, limit {max_words})")

    flair = story.flair.lower()
    part, total = series_part(story.title)
    final = bool(FINAL.search(story.title)) or flair in FINISHED_FLAIRS or (part is not None and part == total)

    # Only the last 600 characters are checked for "more coming" phrases, so a story that quotes
    # "to be continued" in the middle still counts.
    tail = story.body[-600:]
    if UNFINISHED.search(tail) and not final:
        return Verdict(False, "ending says more is coming", part, final)
    if flair in UNFINISHED_FLAIRS and not final:
        return Verdict(False, f"flair '{story.flair}' marks an unfinished series", part, final)
    if part is not None and not final:
        return Verdict(False, f"part {part} of a series that isn't marked finished", part, final)
    if final and (part is not None or FINAL.search(story.title) or "series" in flair):
        label = f"final part ({part})" if part else "final part"
        return Verdict(True, f"{label} of a series; earlier parts are needed", part, True)
    return Verdict(True, "stand-alone story", None, final)
