"""Kinds of stories to look for, each a set of subreddits where people post whole stories as text.

The web page's "What kind of stories" menu is built from this list. Add a kind, or change a list,
here. Every subreddit is a place where first-person stories are the point of the community.
"""
from __future__ import annotations

STORY_TYPES: dict[str, dict] = {
    "scary": {
        "label": "Scary and creepy",
        "subreddits": ["nosleep", "LetsNotMeet", "TrueScaryStories", "shortscarystories", "creepyencounters"],
    },
    "paranormal": {
        "label": "Paranormal and unexplained",
        "subreddits": ["Paranormal", "Glitch_in_the_Matrix", "Thetruthishere", "Humanoidencounters"],
    },
    "revenge": {
        "label": "Revenge",
        "subreddits": ["ProRevenge", "pettyrevenge", "NuclearRevenge"],
    },
    "work": {
        "label": "Work and customers",
        "subreddits": ["MaliciousCompliance", "TalesFromRetail", "talesfromtechsupport", "TalesFromYourServer"],
    },
    "family": {
        "label": "Family drama",
        "subreddits": ["entitledparents", "entitledpeople", "JUSTNOMIL"],
    },
    "funny": {
        "label": "Funny mishaps",
        "subreddits": ["tifu"],
    },
}

# How long a story should be. Narration runs about 150 words a minute.
LENGTHS: dict[str, dict] = {
    "any": {"label": "Any length (about 3–80 min)", "min_words": 400, "max_words": 12000},
    "short": {"label": "Short (about 3–10 min)", "min_words": 400, "max_words": 1500},
    "medium": {"label": "Medium (about 10–30 min)", "min_words": 1500, "max_words": 4500},
    "long": {"label": "Long (about 30–80 min)", "min_words": 4500, "max_words": 12000},
}

TIMES = {"day": "Past day", "week": "Past week", "month": "Past month", "year": "Past year", "all": "All time"}
MIN_SCORES = [0, 50, 100, 500, 1000, 5000]
LIMITS = [10, 25, 50, 100]


def subreddits_for(kind: str, subreddit: str = "") -> list[str]:
    """The subreddits to search: one chosen subreddit of a kind, or all of that kind's subreddits."""
    if kind not in STORY_TYPES:
        raise ValueError(f"unknown kind of story {kind!r}; choose one of {', '.join(STORY_TYPES)}")
    subs = STORY_TYPES[kind]["subreddits"]
    if not subreddit:
        return list(subs)
    match = [s for s in subs if s.lower() == subreddit.removeprefix("r/").lower()]
    if not match:
        raise ValueError(f"r/{subreddit} isn't one of the {STORY_TYPES[kind]['label'].lower()} subreddits")
    return match
