"""The story library: every finished story `fetch` finds, kept in one SQLite file so later steps
(narration, video) know what's waiting and nothing is made twice.

A story is stored once, by its Reddit id. Fetching it again updates its score and text but keeps
its status, so a story that has been narrated stays narrated.
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .story import Story

STATUSES = ("new", "narrated")

SCHEMA = """
CREATE TABLE IF NOT EXISTS stories (
    id          TEXT PRIMARY KEY,                 -- Reddit's post id (for a joined series, the final part's)
    subreddit   TEXT NOT NULL,
    title       TEXT NOT NULL,
    author      TEXT NOT NULL,
    url         TEXT NOT NULL,
    body        TEXT NOT NULL,
    words       INTEGER NOT NULL,
    score       INTEGER NOT NULL DEFAULT 0,
    created_utc REAL NOT NULL,
    parts       TEXT NOT NULL DEFAULT '[]',       -- JSON list of every part's link, for a joined series
    status      TEXT NOT NULL DEFAULT 'new' CHECK (status IN ('new', 'narrated')),
    added_at    TEXT NOT NULL,
    narrated_at TEXT
);
CREATE INDEX IF NOT EXISTS stories_subreddit ON stories (subreddit COLLATE NOCASE);
CREATE INDEX IF NOT EXISTS stories_status ON stories (status);
"""


@dataclass(frozen=True)
class Entry:
    """One story in the library."""
    id: str
    subreddit: str
    title: str
    author: str
    url: str
    body: str
    words: int
    score: int
    created_utc: float
    parts: tuple[str, ...]
    status: str
    added_at: str
    narrated_at: str | None

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "Entry":
        d = dict(row)
        d["parts"] = tuple(json.loads(d["parts"]))
        return cls(**d)


def _now(when: datetime | None) -> str:
    return (when or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat(timespec="seconds")


def _like(word: str) -> str:
    """A LIKE pattern that matches the word anywhere, with % and _ in the word taken literally."""
    return "%" + word.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


class Library:
    def __init__(self, path: str | Path = "library.db"):
        self.path = Path(path)
        if str(path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path))
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)

    def __enter__(self) -> "Library":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def close(self) -> None:
        self.db.close()

    def add(self, story: Story, when: datetime | None = None) -> bool:
        """Saves a story. Returns True if it's new, False if it was already in the library
        (then its title, text, score and parts are refreshed, and its status is kept)."""
        with self.db:
            existed = self.db.execute("SELECT 1 FROM stories WHERE id = ?", (story.id,)).fetchone() is not None
            self.db.execute(
                """INSERT INTO stories (id, subreddit, title, author, url, body, words, score, created_utc, parts, added_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT (id) DO UPDATE SET
                     title = excluded.title, body = excluded.body, words = excluded.words,
                     score = excluded.score, parts = excluded.parts""",
                (story.id, story.subreddit, story.title, story.author, story.url, story.body, story.words,
                 story.score, story.created_utc, json.dumps(list(story.parts)), _now(when)),
            )
        return not existed

    def get(self, story_id: str) -> Entry | None:
        row = self.db.execute("SELECT * FROM stories WHERE id = ?", (story_id,)).fetchone()
        return Entry.from_row(row) if row else None

    def mark(self, story_id: str, status: str = "narrated", when: datetime | None = None) -> bool:
        """Sets a story's status ('narrated', or back to 'new'). Returns False if the id isn't in the library."""
        if status not in STATUSES:
            raise ValueError(f"status must be one of {', '.join(STATUSES)}")
        with self.db:
            cur = self.db.execute(
                "UPDATE stories SET status = ?, narrated_at = ? WHERE id = ?",
                (status, _now(when) if status == "narrated" else None, story_id),
            )
        return cur.rowcount == 1

    def mark_narrated(self, story_id: str, when: datetime | None = None) -> bool:
        return self.mark(story_id, "narrated", when)

    def find(self, subreddit: str | None = None, words: list[str] | tuple[str, ...] = (),
             status: str | None = None, limit: int = 50) -> list[Entry]:
        """Stories matching every filter: the subreddit (any capitalization), every word in the title
        or text (any capitalization), and the status. Highest score first."""
        if status is not None and status not in STATUSES:
            raise ValueError(f"status must be one of {', '.join(STATUSES)}")
        where, params = [], []
        if subreddit:
            where.append("subreddit = ? COLLATE NOCASE")
            params.append(subreddit.removeprefix("r/"))
        for word in words:
            where.append("(title LIKE ? ESCAPE '\\' OR body LIKE ? ESCAPE '\\')")
            params += [_like(word), _like(word)]
        if status:
            where.append("status = ?")
            params.append(status)
        sql = "SELECT * FROM stories" + (" WHERE " + " AND ".join(where) if where else "")
        sql += " ORDER BY score DESC, created_utc DESC LIMIT ?"
        return [Entry.from_row(r) for r in self.db.execute(sql, (*params, limit))]

    def counts(self) -> dict[str, int]:
        """How many stories have each status, e.g. {'new': 12, 'narrated': 3}."""
        rows = self.db.execute("SELECT status, COUNT(*) AS n FROM stories GROUP BY status").fetchall()
        return {s: 0 for s in STATUSES} | {r["status"]: r["n"] for r in rows}
