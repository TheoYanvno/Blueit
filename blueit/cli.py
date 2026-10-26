"""Command line: `python -m blueit check posts.json` explains which posts are finished stories."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .clean import clean
from .complete import check
from .config import Config
from .story import Story


def _posts(path: Path) -> list[dict]:
    """Reads a saved Reddit listing (or a plain list of posts) and returns each post's data."""
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        data = data.get("data", {}).get("children", [])
    return [p.get("data", p) for p in data]


def cmd_check(args, cfg: Config) -> int:
    for post in _posts(Path(args.file)):
        story = Story.from_reddit(post)
        v = check(story, cfg.min_words, cfg.max_words, cfg.allow_nsfw)
        mark = "✔" if v.ok else "✘"
        print(f"{mark} r/{story.subreddit}  {story.title[:70]!r}  ({story.words} words) — {v.reason}")
        if v.ok and args.show:
            print("\n" + clean(story.body) + "\n")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="blueit", description="Finished Reddit stories to narrated videos.")
    parser.add_argument("--config", default="blueit.toml")
    sub = parser.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check", help="say which posts in a saved Reddit JSON file are finished stories")
    c.add_argument("file")
    c.add_argument("--show", action="store_true", help="print the cleaned text of finished stories")
    args = parser.parse_args(argv)
    cfg = Config.load(args.config)
    return {"check": cmd_check}[args.cmd](args, cfg)


if __name__ == "__main__":
    sys.exit(main())
