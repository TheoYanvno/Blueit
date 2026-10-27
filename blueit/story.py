"""A Reddit post as Blueit sees it, built from the JSON Reddit's API returns for a post."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Story:
    id: str
    subreddit: str
    title: str
    author: str
    body: str
    url: str
    created_utc: float
    score: int = 0
    flair: str = ""
    over_18: bool = False
    removed: bool = False
    tags: tuple[str, ...] = field(default=())
    parts: tuple[str, ...] = field(default=())  # links to every part when this story joins a series

    @property
    def words(self) -> int:
        return len(self.body.split())

    @classmethod
    def from_reddit(cls, data: dict) -> "Story":
        """Builds a Story from one post's `data` object (the `t3` kind in Reddit's listings)."""
        body = data.get("selftext") or ""
        removed = (
            body in ("[removed]", "[deleted]")
            or data.get("author") in (None, "[deleted]")
            or bool(data.get("removed_by_category"))
        )
        return cls(
            id=data["id"],
            subreddit=data.get("subreddit", ""),
            title=(data.get("title") or "").strip(),
            author=data.get("author") or "[deleted]",
            body=body,
            url="https://www.reddit.com" + data.get("permalink", f"/comments/{data['id']}/"),
            created_utc=float(data.get("created_utc", 0)),
            score=int(data.get("score", 0)),
            flair=(data.get("link_flair_text") or "").strip(),
            over_18=bool(data.get("over_18")),
            removed=removed,
        )
