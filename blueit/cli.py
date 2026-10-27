"""Command line.
  python -m blueit fetch              save the configured subreddits' posts to listings/*.json
  python -m blueit check posts.json   explain which posts in a saved listing are finished stories
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .clean import clean
from .complete import check
from .config import Config
from .reddit import Credentials, Reddit, RedditError, load_env
from .series import find_and_join
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


def cmd_fetch(args, cfg: Config, reddit: Reddit | None = None) -> int:
    try:
        reddit = reddit or Reddit(Credentials.from_env(load_env(args.env)))
    except RedditError as e:
        print(e, file=sys.stderr)
        return 2
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    for sub in cfg.subreddits:
        listing = (reddit.search(sub, cfg.search, cfg.time_filter, cfg.limit) if cfg.search
                   else reddit.top(sub, cfg.time_filter, cfg.limit))
        children = [c for c in listing.get("data", {}).get("children", [])
                    if c.get("kind") == "t3" and int(c["data"].get("score", 0)) >= cfg.min_score]
        path = out / f"{sub}.json"
        path.write_text(json.dumps({"kind": "Listing", "data": {"children": children}}, indent=1), encoding="utf-8")
        finished, series = 0, []
        for c in children:
            story = Story.from_reddit(c["data"])
            verdict = check(story, cfg.min_words, cfg.max_words, cfg.allow_nsfw)
            finished += verdict.ok
            if verdict.ok and verdict.final and verdict.reason.endswith("earlier parts are needed"):
                result = find_and_join(reddit, story, min_words=cfg.min_words, allow_nsfw=cfg.allow_nsfw)
                print(f"  series {story.title[:60]!r}: {result.reason}")
                if result.ok:
                    s = result.story
                    series.append({"id": s.id, "title": s.title, "author": s.author, "subreddit": s.subreddit,
                                   "words": s.words, "parts": list(s.parts), "body": s.body})
        if series:
            (out / f"{sub}.series.json").write_text(json.dumps(series, indent=1), encoding="utf-8")
        print(f"r/{sub}: {len(children)} posts, {finished} finished stories, {len(series)} joined series → {path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="blueit", description="Finished Reddit stories to narrated videos.")
    parser.add_argument("--config", default="blueit.toml")
    sub = parser.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check", help="say which posts in a saved Reddit JSON file are finished stories")
    c.add_argument("file")
    c.add_argument("--show", action="store_true", help="print the cleaned text of finished stories")
    f = sub.add_parser("fetch", help="download posts from the subreddits in blueit.toml through Reddit's API")
    f.add_argument("--out", default="listings", help="folder for the saved listings")
    f.add_argument("--env", default=".env", help="file with REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET")
    args = parser.parse_args(argv)
    cfg = Config.load(args.config)
    return {"check": cmd_check, "fetch": cmd_fetch}[args.cmd](args, cfg)


if __name__ == "__main__":
    sys.exit(main())
