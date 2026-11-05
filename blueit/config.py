"""Settings, read from blueit.toml in the working folder (see blueit.example.toml)."""
from __future__ import annotations

import platform
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

# Scary and creepy story communities to start with. Change these in blueit.toml.
DEFAULT_SUBREDDITS = ["nosleep", "LetsNotMeet", "Glitch_in_the_Matrix", "TrueScaryStories", "shortscarystories"]


@dataclass
class Config:
    subreddits: list[str] = field(default_factory=lambda: list(DEFAULT_SUBREDDITS))
    search: str = ""  # optional search words, e.g. "cabin"; empty means top posts
    time_filter: str = "month"  # hour, day, week, month, year or all
    limit: int = 25
    min_words: int = 400
    max_words: int = 12000
    min_score: int = 100
    allow_nsfw: bool = False
    output: Path = Path("output")
    images: Path = Path("images")
    clip_seconds: int = 60
    library: Path = Path("library.db")  # the story library (SQLite)
    voice_engine: str = field(default_factory=lambda: "windows" if platform.system() == "Windows" else "espeak")
    voice: str = ""         # part of a voice's name ("David", "Zira") or an eSpeak voice ("en-us")
    voice_rate: int | None = None  # Windows: -10 to 10; eSpeak: words per minute

    @classmethod
    def load(cls, path: str | Path = "blueit.toml") -> "Config":
        p = Path(path)
        if not p.exists():
            return cls()
        data = tomllib.loads(p.read_text(encoding="utf-8"))
        known = {k: v for k, v in data.get("blueit", data).items() if k in cls.__dataclass_fields__}
        for key in ("output", "images", "library"):
            if key in known:
                known[key] = Path(known[key])
        return cls(**known)
