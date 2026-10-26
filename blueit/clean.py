"""Turns a post's Markdown into plain text that reads well out loud."""
from __future__ import annotations

import html
import re

_EDIT = re.compile(r"^\s*(?:\*{0,2})(?:edit|update|eta|ps|p\.s\.)\b.*$", re.I | re.M)
_LINK = re.compile(r"\[([^\]]+)\]\([^)]+\)")
_URL = re.compile(r"https?://\S+")
_MARK = re.compile(r"(\*\*|__|\*|_|~~|`|^>+\s?|^#+\s*)", re.M)
_RULE = re.compile(r"^\s*(?:[-*_]\s*){3,}$", re.M)
_SPOILER = re.compile(r">!(.*?)!<", re.S)

# Reddit shorthand read out as words.
SAY = {
    r"\bAITA\b": "am I the jerk",
    r"\bTL;?DR\b": "in short",
    r"\bMIL\b": "mother-in-law",
    r"\bFIL\b": "father-in-law",
    r"\bIRL\b": "in real life",
    r"\bIMO\b": "in my opinion",
    r"\bw/o\b": "without",
    r"\bw/\b": "with",
    # Ages like "my neighbor (34M)" become "my neighbor, a 34-year-old man,".
    r"\s*[(\[](\d{1,2})\s?[Mm][)\]]": r", a \1-year-old man,",
    r"\s*[(\[](\d{1,2})\s?[Ff][)\]]": r", a \1-year-old woman,",
}


def clean(text: str, keep_edits: bool = False) -> str:
    text = html.unescape(text).replace("\r\n", "\n")
    text = _SPOILER.sub(r"\1", text)
    if not keep_edits:
        # Edits are usually replies to commenters, not part of the story; they go at the end.
        cut = _EDIT.search(text)
        if cut and cut.start() > len(text) * 0.6:
            text = text[: cut.start()]
    text = _LINK.sub(r"\1", text)
    text = _URL.sub("", text)
    text = _RULE.sub("", text)
    text = _MARK.sub("", text)
    text = text.replace("&#x200B;", "").replace("​", "")
    for pattern, words in SAY.items():
        text = re.sub(pattern, words, text)
    paragraphs = [re.sub(r"\s+", " ", p).strip() for p in re.split(r"\n\s*\n", text)]
    return "\n\n".join(p for p in paragraphs if p)
