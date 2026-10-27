"""Joins the parts of a finished series into one story.

When the finished-story check finds the final part of a series ("Part 4 (Final)"), the earlier parts
are needed before it can be narrated. They are found in the author's own post history
(/user/<name>/submitted), matched by title and subreddit, put in order by part number and then by
date, checked, and combined into one Story whose body has every part's text and whose `parts` lists
every part's link.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, replace

from .complete import FINAL, PART, check, series_part
from .story import Story

# Anything in brackets, and the part / final markers themselves, are removed to get the series name.
_BRACKETS = re.compile(r"[\(\[\{][^\)\]\}]*[\)\]\}]")
_MARKERS = re.compile(
    r"\b(?:part|pt\.?)\s*(?:\d+|[ivx]+)\b|\b(?:final|finale|last part|conclusion|epilogue|the end)\b", re.I
)


def series_name(title: str) -> str:
    """The title without part numbers or "final": "The Well, Part 3 (Final)" -> "the well"."""
    t = _BRACKETS.sub(" ", title)
    t = _MARKERS.sub(" ", t)
    t = re.sub(r"[^\w\s']", " ", t)
    return " ".join(t.lower().split())


@dataclass(frozen=True)
class SeriesResult:
    ok: bool
    reason: str
    story: Story | None = None   # the joined story when ok
    parts: tuple[Story, ...] = ()


def _part_problem(part: Story, allow_nsfw: bool) -> str | None:
    """Earlier parts naturally say "part 2 coming soon", so only problems that make a part unusable count."""
    if part.removed or not part.body.strip():
        return "removed, deleted or has no text"
    if part.over_18 and not allow_nsfw:
        return "marked NSFW"
    return None


def order_parts(final: Story, candidates: list[Story]) -> list[Story]:
    """The final part plus the candidates that belong to the same series, in reading order.

    A candidate belongs when it has the same author, subreddit and series name, and was posted no
    later than the final part. If the same part number shows up twice (a repost), the first one posted
    is kept. Parts without a number are placed by date.
    """
    name = series_name(final.title)
    same = [
        s for s in candidates
        if s.id != final.id and s.author == final.author and s.subreddit.lower() == final.subreddit.lower()
        and series_name(s.title) == name and s.created_utc <= final.created_utc
    ]
    by_number: dict[int, Story] = {}
    unnumbered: list[Story] = []
    for s in sorted(same, key=lambda s: s.created_utc):
        n, _ = series_part(s.title)
        if n is None:
            unnumbered.append(s)
        elif n not in by_number:
            by_number[n] = s
    final_n, _ = series_part(final.title)
    if final_n is not None:
        by_number.pop(final_n, None)
    ordered = [by_number[n] for n in sorted(by_number)] + unnumbered
    ordered.sort(key=lambda s: (series_part(s.title)[0] or 10**6, s.created_utc))
    return ordered + [final]


def join(final: Story, candidates: list[Story], *, min_words: int = 400, max_words: int = 60000,
         allow_nsfw: bool = False) -> SeriesResult:
    """Joins `final` with its earlier parts found in `candidates`."""
    verdict = check(final, min_words=0, max_words=10**9, allow_nsfw=allow_nsfw)
    if not verdict.ok or not verdict.final:
        return SeriesResult(False, f"not the final part of a finished series ({verdict.reason})")
    parts = order_parts(final, candidates)
    final_n, total = series_part(final.title)
    expected = total or final_n
    numbers = [series_part(p.title)[0] for p in parts[:-1]]
    if expected:
        missing = [n for n in range(1, expected) if n not in numbers]
        if missing:
            return SeriesResult(False, f"missing part {', '.join(map(str, missing))}", parts=tuple(parts))
    elif len(parts) < 2:
        return SeriesResult(False, "no earlier parts found", parts=tuple(parts))
    for i, p in enumerate(parts, 1):
        problem = _part_problem(p, allow_nsfw)
        if problem:
            return SeriesResult(False, f"part {i} ({p.title!r}) is {problem}", parts=tuple(parts))

    body = "\n\n".join(f"Part {i}.\n\n{p.body.strip()}" for i, p in enumerate(parts, 1))
    story = replace(
        final,
        title=_display_title(final.title),
        body=body,
        created_utc=parts[0].created_utc,
        score=max(p.score for p in parts),
        parts=tuple(p.url for p in parts),
    )
    if story.words < min_words:
        return SeriesResult(False, f"joined series is too short ({story.words} words)", parts=tuple(parts))
    if story.words > max_words:
        return SeriesResult(False, f"joined series is too long ({story.words} words, limit {max_words})", parts=tuple(parts))
    return SeriesResult(True, f"joined {len(parts)} parts", story, tuple(parts))


def _display_title(title: str) -> str:
    """The series title as the author wrote it, minus the part and final markers."""
    t = _BRACKETS.sub(" ", title)
    t = PART.sub(" ", t)
    t = FINAL.sub(" ", t) if FINAL.search(t) else t
    t = re.sub(r"\s*[,:|\-–—]\s*$", "", " ".join(t.split()))
    return t.strip(" ,:-|–—") or title


def find_and_join(reddit, final: Story, **kw) -> SeriesResult:
    """Looks up the author's posts through the Reddit client and joins the series."""
    if final.author in ("", "[deleted]"):
        return SeriesResult(False, "the author's account is deleted, so earlier parts can't be found")
    candidates = reddit.submitted(final.author)
    return join(final, candidates, **kw)
