"""Command line.
  python -m blueit fetch              save the configured subreddits' posts to listings/*.json, and the
                                      finished stories to the library (library.db)
  python -m blueit check posts.json   explain which posts in a saved listing are finished stories
  python -m blueit find [words…]      search the library by words, --subreddit and --status
  python -m blueit mark ID            mark a library story as narrated (--new to undo)
  python -m blueit ui                 open a page in your browser to pick what stories to find from menus
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
from .library import STATUSES, Library
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
    with Library(_library_path(args, cfg)) as library:
        for sub in cfg.subreddits:
            _fetch_one(reddit, cfg, sub, out, library)
        c = library.counts()
        print(f"Library: {c['new']} waiting, {c['narrated']} narrated → {library.path}")
    return 0


def _library_path(args, cfg: Config) -> Path:
    return Path(getattr(args, "library", None) or cfg.library)


def _fetch_one(reddit: Reddit, cfg: Config, sub: str, out: Path, library: Library, log=print) -> list[str]:
    """Saves one subreddit's listing, joins finished series, and adds every finished story to the library.
    Returns the ids of the finished stories found (new or already in the library)."""
    listing = (reddit.search(sub, cfg.search, cfg.time_filter, cfg.limit) if cfg.search
               else reddit.top(sub, cfg.time_filter, cfg.limit))
    children = [c for c in listing.get("data", {}).get("children", [])
                if c.get("kind") == "t3" and int(c["data"].get("score", 0)) >= cfg.min_score]
    path = out / f"{sub}.json"
    path.write_text(json.dumps({"kind": "Listing", "data": {"children": children}}, indent=1), encoding="utf-8")
    finished, series, added, found = 0, [], 0, []
    for c in children:
        story = Story.from_reddit(c["data"])
        verdict = check(story, cfg.min_words, cfg.max_words, cfg.allow_nsfw)
        finished += verdict.ok
        if verdict.ok and verdict.final and verdict.reason.endswith("earlier parts are needed"):
            result = find_and_join(reddit, story, min_words=cfg.min_words, allow_nsfw=cfg.allow_nsfw)
            log(f"  series {story.title[:60]!r}: {result.reason}")
            if result.ok:
                s = result.story
                series.append({"id": s.id, "title": s.title, "author": s.author, "subreddit": s.subreddit,
                               "words": s.words, "parts": list(s.parts), "body": s.body})
                added += library.add(s)
                found.append(s.id)
            # a final part whose earlier parts couldn't be joined isn't a whole story, so it isn't kept
        elif verdict.ok:
            added += library.add(story)
            found.append(story.id)
    if series:
        (out / f"{sub}.series.json").write_text(json.dumps(series, indent=1), encoding="utf-8")
    log(f"r/{sub}: {len(children)} posts, {finished} finished stories, {len(series)} joined series, "
        f"{added} new in the library → {path}")
    return found


def cmd_find(args, cfg: Config) -> int:
    path = _library_path(args, cfg)
    if not path.exists():
        print(f"No library yet at {path}. Run `blueit fetch` first.", file=sys.stderr)
        return 1
    with Library(path) as library:
        found = library.find(subreddit=args.subreddit, words=args.words, status=args.status, limit=args.limit)
    for e in found:
        series = f", {len(e.parts)} parts" if e.parts else ""
        print(f"{e.id}  [{e.status}]  r/{e.subreddit}  {e.title[:70]!r}  ({e.words} words{series}, score {e.score})  {e.url}")
    print(f"{len(found)} {'story' if len(found) == 1 else 'stories'} found.")
    return 0


def cmd_mark(args, cfg: Config) -> int:
    with Library(_library_path(args, cfg)) as library:
        status = "new" if args.new else "narrated"
        if not library.mark(args.id, status):
            print(f"No story with id {args.id!r} in the library.", file=sys.stderr)
            return 1
    print(f"{args.id} marked {status}.")
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
    s = sub.add_parser("find", help="search the story library")
    s.add_argument("words", nargs="*", help="words that must all appear in the title or text")
    s.add_argument("--subreddit", "-r", help="only stories from this subreddit")
    s.add_argument("--status", choices=STATUSES, help="only new (not narrated yet) or narrated stories")
    s.add_argument("--limit", type=int, default=50)
    m = sub.add_parser("mark", help="mark a library story as narrated")
    m.add_argument("id", help="the story's id, as `find` shows it")
    m.add_argument("--new", action="store_true", help="mark it as not narrated again")
    u = sub.add_parser("ui", help="open a page in your browser to pick what stories to find from menus")
    u.add_argument("--port", type=int, default=8642)
    u.add_argument("--out", default="listings", help="folder for the saved listings")
    u.add_argument("--env", default=".env", help="file with REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET")
    u.add_argument("--no-browser", action="store_true", help="don't open the browser")
    for p in (f, s, m, u):
        p.add_argument("--library", help="the library file (default: library in blueit.toml, or library.db)")
    args = parser.parse_args(argv)
    cfg = Config.load(args.config)
    return {"check": cmd_check, "fetch": cmd_fetch, "find": cmd_find, "mark": cmd_mark, "ui": cmd_ui}[args.cmd](args, cfg)


def cmd_ui(args, cfg: Config) -> int:
    from .web import serve
    return serve(cfg, port=args.port, out=Path(args.out), env=args.env, library=_library_path(args, cfg),
                 open_browser=not args.no_browser)


if __name__ == "__main__":
    sys.exit(main())
