"""Command line.
  python -m blueit fetch              save the configured subreddits' posts to listings/*.json, and the
                                      finished stories to the library (library.db)
  python -m blueit check posts.json   explain which posts in a saved listing are finished stories
  python -m blueit find [words…]      search the library by words, --subreddit and --status
  python -m blueit mark ID            mark a library story as narrated (--new to undo)
  python -m blueit ui                 open a page in your browser to pick what stories to find from menus
  python -m blueit narrate ID         read a library story aloud into output/<story>/narration.wav (--next: the
                                      highest-scored story not narrated yet)
  python -m blueit video ID           make output/<story>/full.mp4 and its 1-minute parts from the narration
  python -m blueit doctor             check FFmpeg, the voice, your pictures and Reddit keys, with how to fix each
  python -m blueit run                the whole thing: (--fetch first), then narrate the top waiting story and make
                                      its videos; --count N does N stories
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


def _pick_story(library: Library, args):
    if args.next:
        waiting = library.find(status="new", limit=1)
        return waiting[0] if waiting else None
    return library.get(args.id)


def cmd_narrate(args, cfg: Config, voice=None) -> int:
    from .narrate import VoiceError, make_voice, narrate
    from .project import prepare
    if not args.id and not args.next:
        print("Give a story id (see `blueit find`) or --next.", file=sys.stderr)
        return 2
    with Library(_library_path(args, cfg)) as library:
        entry = _pick_story(library, args)
        if entry is None:
            print("No story waiting to be narrated." if args.next else f"No story with id {args.id!r} in the library.",
                  file=sys.stderr)
            return 1
        try:
            voice = voice or make_voice(args.voice or cfg.voice_engine, cfg.voice, cfg.voice_rate)
            folder = prepare(cfg.output, entry)
            print(f"Narrating {entry.title[:70]!r} ({entry.words} words) with the {voice.name} voice…")
            n = narrate((folder / "script.txt").read_text(encoding="utf-8"), voice, folder,
                        progress=lambda done, total: print(f"\r  {done}/{total} pieces", end="", flush=True))
        except VoiceError as e:
            print(f"\n{e}", file=sys.stderr)
            return 2
        library.mark_narrated(entry.id)
    m, s = divmod(round(n.seconds), 60)
    print(f"\nDone: {m} min {s:02} s → {n.audio}")
    return 0


def cmd_video(args, cfg: Config, runner=None) -> int:
    from .pictures import PictureError
    from .pipeline import make
    from .project import folder_for
    from .video import VideoError
    with Library(_library_path(args, cfg)) as library:
        entry = library.get(args.id)
    if entry is None:
        print(f"No story with id {args.id!r} in the library.", file=sys.stderr)
        return 1
    print(f"Making the video for {entry.title[:70]!r}…")
    try:
        made = make(folder_for(cfg.output, entry), cfg, runner=runner)
    except (VideoError, PictureError) as e:
        print(e, file=sys.stderr)
        return 2
    m, s = divmod(round(made.seconds), 60)
    print(f"Done: {m} min {s:02} s, {len(made.parts)} parts → {made.folder}")
    return 0


def cmd_run(args, cfg: Config, voice=None, runner=None, reddit=None) -> int:
    from .narrate import VoiceError, make_voice, narrate
    from .pictures import PictureError, find_pictures
    from .pipeline import make
    from .project import folder_for, prepare
    from .video import VideoError, ffmpeg_path
    try:
        if runner is None:
            ffmpeg_path()                                   # say so now, not after a long narration
        find_pictures(cfg.output / "_", cfg.images)
        voice = voice or make_voice(args.voice or cfg.voice_engine, cfg.voice, cfg.voice_rate)
    except (VideoError, PictureError, VoiceError) as e:
        print(e, file=sys.stderr)
        return 2
    if args.fetch:
        code = cmd_fetch(args, cfg, reddit)
        if code:
            return code
    done = 0
    with Library(_library_path(args, cfg)) as library:
        for _ in range(max(1, args.count)):
            waiting = library.find(status="new", limit=1)
            if not waiting:
                print("No more stories waiting." if done else "No story waiting. Run with --fetch, or `blueit ui`.")
                break
            entry = waiting[0]
            print(f"[{done + 1}] {entry.title[:70]!r} (r/{entry.subreddit}, {entry.words} words)")
            try:
                folder = prepare(cfg.output, entry)
                narrate((folder / "script.txt").read_text(encoding="utf-8"), voice, folder)
                library.mark_narrated(entry.id)
                made = make(folder_for(cfg.output, entry), cfg, runner=runner)
            except (VoiceError, VideoError, PictureError) as e:
                print(f"  stopped: {e}", file=sys.stderr)
                return 2
            m, sec = divmod(round(made.seconds), 60)
            print(f"  done: {m} min {sec:02} s, {len(made.parts)} parts → {made.folder}")
            done += 1
    return 0


def cmd_doctor(args, cfg: Config) -> int:
    from dataclasses import replace
    from .doctor import report, run_checks
    checks = run_checks(replace(cfg, library=_library_path(args, cfg)), env=args.env)
    print(report(checks))
    return 0 if all(c.ok for c in checks) else 1


def frozen() -> bool:
    """True when running as the packaged Windows app (PyInstaller) rather than from Python."""
    return bool(getattr(sys, "frozen", False))


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
    n = sub.add_parser("narrate", help="read a library story aloud with a stock voice")
    n.add_argument("id", nargs="?", help="the story's id, as `find` shows it")
    n.add_argument("--next", action="store_true", help="the highest-scored story that isn't narrated yet")
    n.add_argument("--voice", choices=["windows", "espeak", "silent"], help="override voice_engine in blueit.toml")
    v = sub.add_parser("video", help="make the full video and 1-minute parts for a narrated story")
    v.add_argument("id", help="the story's id, as `find` shows it")
    r = sub.add_parser("run", help="narrate the top waiting stories and make their videos (--fetch to search first)")
    r.add_argument("--fetch", action="store_true", help="fetch new stories from the subreddits in blueit.toml first")
    r.add_argument("--count", type=int, default=1, help="how many stories to make (default 1)")
    r.add_argument("--voice", choices=["windows", "espeak", "silent"], help="override voice_engine in blueit.toml")
    r.add_argument("--out", default="listings", help="folder for the saved listings (with --fetch)")
    r.add_argument("--env", default=".env", help="file with REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET (with --fetch)")
    dr = sub.add_parser("doctor", help="check that everything Blueit needs is set up")
    dr.add_argument("--env", default=".env", help="file with REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET")
    for p in (f, s, m, u, n, v, r, dr):
        p.add_argument("--library", help="the library file (default: library in blueit.toml, or library.db)")
    if argv is None:
        argv = sys.argv[1:]
    if not argv and frozen():
        argv = ["ui"]                    # double-clicking Blueit.exe opens the page
    args = parser.parse_args(argv)
    cfg = Config.load(args.config)
    return {"check": cmd_check, "fetch": cmd_fetch, "find": cmd_find, "mark": cmd_mark, "ui": cmd_ui,
            "narrate": cmd_narrate, "video": cmd_video,
            "run": cmd_run, "doctor": cmd_doctor}[args.cmd](args, cfg)


def cmd_ui(args, cfg: Config) -> int:
    from .web import serve
    return serve(cfg, port=args.port, out=Path(args.out), env=args.env, library=_library_path(args, cfg),
                 open_browser=not args.no_browser)


if __name__ == "__main__":
    sys.exit(main())
