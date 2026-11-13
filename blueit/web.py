"""A small page in your browser for picking what stories to find, from drop-down menus.

  python -m blueit ui          opens http://127.0.0.1:8642

The menus choose the kind of story (scary, revenge, work…), one subreddit or all of that kind, how far
back to look, how long the stories should be, the fewest upvotes and how many posts to look at. "Find
stories" runs the same search as `blueit fetch` with those choices and shows the finished stories it
found; the Library tab lists everything saved so far and marks stories narrated. "Make video" on any
story narrates it (if it isn't yet) and makes its full video and 1-minute parts in the background, one
story at a time, with the progress shown on the page.

Only the Python standard library is used. The server listens on 127.0.0.1 only, answers only requests
addressed to localhost (so a web page elsewhere can't reach it through DNS tricks), and only takes JSON
in POST requests (so another site can't submit a form to it).
"""
from __future__ import annotations

import html
import json
import platform
import threading
import webbrowser
from dataclasses import replace
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .categories import LENGTHS, LIMITS, MIN_SCORES, STORY_TYPES, TIMES, subreddits_for
from .config import Config
from .library import STATUSES, Entry, Library
from .reddit import Credentials, Reddit, RedditError, load_env

MAX_RECORDING = 60 * 1024 * 1024                    # a WAV upload: about 10 minutes at 48 kHz
STATIC = Path(__file__).parent / "static"          # the React app, built by `npm run build` in ui/
MEDIA_TYPES = {".mp4": "video/mp4", ".srt": "text/plain; charset=utf-8", ".txt": "text/plain; charset=utf-8",
               ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}
STATIC_TYPES = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
                ".css": "text/css; charset=utf-8", ".svg": "image/svg+xml", ".png": "image/png", ".ico": "image/x-icon"}

WORDS_PER_MINUTE = 150


class BadRequest(ValueError):
    pass


def byte_range(header: str | None, size: int) -> tuple[int, int] | None:
    """The (start, end) bytes asked for by a Range header like "bytes=100-" so the video player can
    seek; None means send the whole file. Ranges that don't fit the file are clamped or ignored."""
    if not header or not header.startswith("bytes=") or "," in header or size <= 0:
        return None
    start_s, _, end_s = header[6:].strip().partition("-")
    try:
        if start_s == "":                       # "bytes=-500": the last 500 bytes
            n = int(end_s)
            return (max(0, size - n), size - 1) if n > 0 else None
        start = int(start_s)
        end = min(int(end_s), size - 1) if end_s else size - 1
    except ValueError:
        return None
    return (start, end) if 0 <= start <= end else None


def _story(e: Entry) -> dict:
    return {"id": e.id, "title": e.title, "author": e.author, "subreddit": e.subreddit, "words": e.words,
            "minutes": max(1, round(e.words / WORDS_PER_MINUTE)), "score": e.score, "url": e.url,
            "parts": len(e.parts), "status": e.status}


def _pick(params: dict, key: str, allowed, default):
    value = params.get(key, default)
    if value in ("", None):
        value = default
    if isinstance(default, int):
        try:
            value = int(value)
        except (TypeError, ValueError):
            raise BadRequest(f"{key} must be a number")
    if value not in allowed:
        raise BadRequest(f"{key} must be one of {', '.join(map(str, allowed))}")
    return value


class App:
    """What the page can ask for, kept apart from HTTP so it can be tested directly."""

    def __init__(self, cfg: Config, library: Path, out: Path = Path("listings"), reddit_factory=None, env=".env",
                 voice_factory=None, video_runner=None, youtube_dir: Path = Path("."), youtube_http=None,
                 config_path: Path = Path("blueit.toml")):
        self.cfg = cfg
        self.config_path = Path(config_path)         # where "use my voice as the narrator" is saved
        self.youtube_dir = Path(youtube_dir)          # where youtube_client.json and youtube_token.json live
        self.youtube_http = youtube_http
        self.youtube_state: str | None = None
        self.share: dict = {"state": "idle"}
        self.voice_factory = voice_factory
        self.video_runner = video_runner
        self.job: dict = {"state": "idle"}
        self.job_lock = threading.Lock()
        self.library_path = Path(library)
        self.out = Path(out)
        self.env = env
        self.reddit_factory = reddit_factory or (lambda: Reddit(Credentials.from_env(load_env(env))))
        self.busy = threading.Lock()          # one search at a time keeps within Reddit's rate limits

    def options(self) -> dict:
        return {
            "kinds": [{"id": k, "label": v["label"], "subreddits": v["subreddits"]} for k, v in STORY_TYPES.items()],
            "times": [{"id": k, "label": v} for k, v in TIMES.items()],
            "lengths": [{"id": k, "label": v["label"]} for k, v in LENGTHS.items()],
            "minScores": MIN_SCORES,
            "limits": LIMITS,
            "defaults": {"kind": "scary", "time": self.cfg.time_filter if self.cfg.time_filter in TIMES else "month",
                         "length": "any", "minScore": 100, "limit": 25},
        }

    def find(self, params: dict) -> dict:
        from .cli import _fetch_one          # the same search `blueit fetch` runs
        kind = _pick(params, "kind", STORY_TYPES, "scary")
        try:
            subs = subreddits_for(kind, str(params.get("subreddit") or ""))
        except ValueError as e:
            raise BadRequest(str(e))
        length = LENGTHS[_pick(params, "length", LENGTHS, "any")]
        words = " ".join(str(params.get("words") or "").split())[:100]
        cfg = replace(self.cfg,
                      time_filter=_pick(params, "time", TIMES, "month"),
                      limit=_pick(params, "limit", LIMITS, 25),
                      min_score=_pick(params, "minScore", MIN_SCORES, 100),
                      min_words=length["min_words"], max_words=length["max_words"], search=words)
        if not self.busy.acquire(blocking=False):
            raise BadRequest("A search is already running. Wait for it to finish.")
        try:
            try:
                reddit = self.reddit_factory()
            except RedditError as e:
                return {"ok": False, "error": str(e), "log": [], "stories": []}
            log, found = [], []
            self.out.mkdir(parents=True, exist_ok=True)
            with Library(self.library_path) as library:
                for sub in subs:
                    try:
                        found += _fetch_one(reddit, cfg, sub, self.out, library, log=log.append)
                    except RedditError as e:
                        log.append(f"r/{sub}: {e}")
                stories = [library.get(i) for i in dict.fromkeys(found)]
            stories = sorted((s for s in stories if s), key=lambda e: -e.score)
            return {"ok": True, "log": log, "stories": [_story(e) for e in stories]}
        finally:
            self.busy.release()

    def library(self, params: dict) -> dict:
        status = params.get("status") or None
        if status is not None and status not in STATUSES:
            raise BadRequest(f"status must be one of {', '.join(STATUSES)}")
        kind = params.get("kind") or ""
        if kind and kind not in STORY_TYPES:
            raise BadRequest(f"unknown kind of story {kind!r}")
        words = str(params.get("words") or "").split()
        if not self.library_path.exists():
            return {"stories": [], "counts": {s: 0 for s in STATUSES}}
        with Library(self.library_path) as library:
            found = library.find(words=words, status=status, limit=1000)
            counts = library.counts()
        if kind:
            subs = {s.lower() for s in STORY_TYPES[kind]["subreddits"]}
            found = [e for e in found if e.subreddit.lower() in subs]
        return {"stories": [_story(e) for e in found[:200]], "counts": counts}

    def mark(self, params: dict) -> dict:
        status = _pick(params, "status", STATUSES, "narrated")
        story_id = str(params.get("id") or "")
        with Library(self.library_path) as library:
            if not library.mark(story_id, status):
                raise BadRequest(f"No story with id {story_id!r} in the library.")
            return {"story": _story(library.get(story_id))}


    # ---- making videos in the background ----

    def make(self, params: dict, wait: bool = False) -> dict:
        story_id = str(params.get("id") or "")
        with Library(self.library_path) as library:
            entry = library.get(story_id)
        if entry is None:
            raise BadRequest(f"No story with id {story_id!r} in the library.")
        with self.job_lock:
            if self.job.get("state") == "running":
                raise BadRequest(f"Already making {self.job['title']!r}. Wait for it to finish.")
            self.job = {"state": "running", "id": entry.id, "title": entry.title, "step": "Starting", "done": 0, "total": 0}
        worker = threading.Thread(target=self._make, args=(entry,), daemon=True)
        worker.start()
        if wait:
            worker.join()
        return self.status()

    # ---- one story in full, the setup checks and the settings, for the React app ----

    def story(self, params: dict) -> dict:
        from .project import folder_for
        story_id = str(params.get("id") or "")
        with Library(self.library_path) as library:
            entry = library.get(story_id)
        if entry is None:
            raise BadRequest(f"No story with id {story_id!r} in the library.")
        folder = folder_for(self.cfg.output, entry)
        files = sorted(p.name for p in folder.iterdir() if p.is_file() and p.suffix.lower() in MEDIA_TYPES) if folder.is_dir() else []
        videos = [f for f in files if f.endswith(".mp4")]
        return {"story": {**_story(entry), "body": entry.body, "added_at": entry.added_at, "narrated_at": entry.narrated_at},
                "folder": folder.name, "files": files,
                "full": "full.mp4" if "full.mp4" in videos else None,
                "parts": [f for f in videos if f.startswith("part-")]}

    def doctor(self) -> dict:
        from .doctor import run_checks
        checks = run_checks(self.cfg, env=self.env, voice_factory=self.voice_factory)
        return {"ok": all(c.ok for c in checks), "checks": [{"name": c.name, "ok": c.ok, "detail": c.detail} for c in checks]}

    def settings(self) -> dict:
        from dataclasses import asdict
        return {"settings": {k: (str(v) if isinstance(v, Path) else v) for k, v in asdict(self.cfg).items()}}

    # ---- My voice ----

    def _voices(self):
        from .myvoice import VoiceStore
        return VoiceStore(self.cfg.voices)

    def voices(self) -> dict:
        from dataclasses import asdict
        from .myvoice import MIN_SECONDS, SCRIPT, SUGGESTED_SECONDS, addon_installed
        store = self._voices()
        default = store.default
        return {"voices": [asdict(v) for v in store.list()], "default": default.slug if default else None,
                "narrator": self.cfg.voice_engine == "myvoice", "engine": self.cfg.voice_engine,
                "addon": addon_installed(), "script": SCRIPT, "minSeconds": MIN_SECONDS, "suggestedSeconds": SUGGESTED_SECONDS}

    def voice_upload(self, name: str, mine: bool, data: bytes) -> dict:
        from .narrate import VoiceError
        try:
            v = self._voices().save(name, data, own_voice=mine)
        except VoiceError as e:
            raise BadRequest(str(e))
        return {"saved": v.slug, **self.voices()}

    def voice_action(self, params: dict) -> dict:
        """rename, delete, default, or use (My voice as the narrator: on or off), saved to blueit.toml."""
        from .myvoice import set_setting
        from .narrate import VoiceError
        store, action, key = self._voices(), str(params.get("action") or ""), str(params.get("voice") or "")
        try:
            if action == "rename":
                store.rename(key, str(params.get("name") or ""))
            elif action == "delete":
                store.delete(key)
            elif action == "default":
                store.set_default(key)
            elif action == "use":
                on = bool(params.get("on"))
                if on:
                    v = store.set_default(key) if key else store.default
                    if not v:
                        raise BadRequest("Record and save a voice first.")
                    engine, voice = "myvoice", v.name
                else:
                    engine, voice = ("windows" if platform.system() == "Windows" else "espeak"), ""
                set_setting(self.config_path, "voice_engine", engine)
                set_setting(self.config_path, "voice", voice)
                self.cfg.voice_engine, self.cfg.voice = engine, voice
            else:
                raise BadRequest("Unknown voice action.")
        except VoiceError as e:
            raise BadRequest(str(e))
        return self.voices()

    def voice_clip(self, slug: str, which: str) -> Path:
        """A saved voice's recording or 15-second prompt, to listen to on the page."""
        v = self._voices().get(slug)
        name = {"prompt": "prompt.wav", "recording": "recording.wav"}.get(which)
        if not v or not name or v.slug != slug:
            raise BadRequest("No such voice.")
        path = v.folder(Path(self.cfg.voices)) / name
        if not path.is_file():
            raise BadRequest("That recording is missing.")
        return path

    def media_path(self, folder: str, name: str) -> Path:
        """A file inside one story's output folder; anything that tries to step outside it is refused."""
        root = Path(self.cfg.output).resolve()
        path = (root / folder / name).resolve()
        if root not in path.parents or path.parent.parent != root or path.suffix.lower() not in MEDIA_TYPES:
            raise BadRequest("Not a story file.")
        if not path.is_file():
            raise BadRequest("That file hasn't been made yet.")
        return path

    def status(self) -> dict:
        with self.job_lock:
            return dict(self.job)

    # ---- sharing to YouTube ----

    def _yt(self):
        from . import youtube
        client = youtube.Client.load(self.youtube_dir / "youtube_client.json")
        return youtube, client, self.youtube_dir / "youtube_token.json"

    def youtube_status(self) -> dict:
        has_client = (self.youtube_dir / "youtube_client.json").is_file()
        connected = (self.youtube_dir / "youtube_token.json").is_file()
        with self.job_lock:
            share = dict(self.share)
        return {"ready": has_client, "connected": has_client and connected, "share": share}

    def youtube_connect(self, redirect_uri: str) -> dict:
        youtube, client, _ = self._yt_or_bad()
        url, self.youtube_state = youtube.auth_url(client, redirect_uri)
        return {"url": url}

    def youtube_callback(self, params: dict, redirect_uri: str) -> None:
        youtube, client, token_path = self._yt_or_bad()
        if not self.youtube_state or params.get("state") != self.youtube_state:
            raise BadRequest("That sign-in link is old or wasn't started here. Press Connect YouTube again.")
        if params.get("error"):
            raise BadRequest(f"Google said: {params['error']}")
        self.youtube_state = None
        try:
            youtube.exchange_code(client, str(params.get("code") or ""), redirect_uri, token_path,
                                  **({"http": self.youtube_http} if self.youtube_http else {}))
        except youtube.YouTubeError as e:
            raise BadRequest(str(e)) from None

    def _yt_or_bad(self):
        from .youtube import YouTubeError
        try:
            return self._yt()
        except YouTubeError as e:
            raise BadRequest(str(e)) from None

    def share_youtube(self, params: dict, wait: bool = False) -> dict:
        data = self.story(params)
        video = str(params.get("video") or data["full"] or "")
        if video not in ([data["full"]] if data["full"] else []) + data["parts"]:
            raise BadRequest("Make the video first, then pick the full video or one part to share.")
        privacy = str(params.get("privacy") or "private")
        youtube, client, token_path = self._yt_or_bad()
        try:
            youtube.access_token(client, token_path, **({"http": self.youtube_http} if self.youtube_http else {}))
            w, _, h = self.cfg.video_size.partition("x")
            upright = int(w) < int(h) if w.isdigit() and h.isdigit() else True
            part = None if video == "full.mp4" else video.replace("part-", "Part ").replace(".mp4", "").replace("Part 0", "Part ")
            s = data["story"]
            details = youtube.video_details(s["title"], s["author"], s["subreddit"], s["url"], upright, part, privacy)
        except youtube.YouTubeError as e:
            raise BadRequest(str(e)) from None
        with self.job_lock:
            if self.share.get("state") == "running":
                raise BadRequest("Already uploading a video. Wait for it to finish.")
            self.share = {"state": "running", "id": s["id"], "video": video, "title": details["snippet"]["title"], "done": 0, "total": 0}
        path = self.media_path(data["folder"], video)
        worker = threading.Thread(target=self._upload, args=(youtube, client, token_path, path, details), daemon=True)
        worker.start()
        if wait:
            worker.join()
        with self.job_lock:
            return dict(self.share)

    def _upload(self, youtube, client, token_path, path, details) -> None:
        extra = {"http": self.youtube_http} if self.youtube_http else {}
        def progress(done, total):
            with self.job_lock:
                self.share.update(done=done, total=total)
        try:
            token = youtube.access_token(client, token_path, **extra)
            vid = youtube.upload(path, details, token, progress=progress, **extra)
            with self.job_lock:
                self.share.update(state="done", video_id=vid, link=f"https://youtu.be/{vid}")
        except Exception as e:                  # shown on the page; the server keeps running
            with self.job_lock:
                self.share.update(state="error", error=str(e))

    def _set(self, **changes) -> None:
        with self.job_lock:
            self.job.update(changes)

    def _make(self, entry: Entry) -> None:
        from .narrate import make_voice, narrate
        from .pipeline import make
        from .project import prepare
        try:
            folder = prepare(self.cfg.output, entry)
            if not (folder / "narration.json").exists():
                voice = (self.voice_factory or (lambda: make_voice(self.cfg.voice_engine, self.cfg.voice, self.cfg.voice_rate, self.cfg.voices)))()
                self._set(step="Narrating")
                narrate((folder / "script.txt").read_text(encoding="utf-8"), voice, folder,
                        progress=lambda done, total: self._set(done=done, total=total))
                with Library(self.library_path) as library:
                    library.mark_narrated(entry.id)
            self._set(step="Making the video", done=0, total=0)
            made = make(folder, self.cfg, log=lambda line: self._set(step=line.strip()), runner=self.video_runner)
            self._set(state="done", step="Done", folder=str(made.folder), parts=len(made.parts),
                      minutes=round(made.seconds / 60, 1))
        except Exception as e:                  # shown on the page; the server keeps running
            self._set(state="error", step="Stopped", error=str(e))


def make_handler(app: App, allowed_hosts: set[str]):
    class Handler(BaseHTTPRequestHandler):
        server_version = "blueit"

        def log_message(self, *args):          # keep the terminal quiet
            pass

        def _send(self, status: int, body: bytes, kind: str, extra: dict | None = None):
            self.send_response(status)
            self.send_header("Content-Type", kind)
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy",
                             "default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
                             "connect-src 'self'; img-src 'self' data:; media-src 'self'; frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, status: int, data: dict):
            self._send(status, json.dumps(data).encode(), "application/json; charset=utf-8")

        def _static(self, path: str):
            """The React app, or a short note on how to build it."""
            index = STATIC / "index.html"
            if not index.is_file():
                return self._send(HTTPStatus.OK, NOT_BUILT.encode(), "text/html; charset=utf-8")
            target = index if path == "/" else (STATIC / path.lstrip("/")).resolve()
            if STATIC.resolve() not in target.parents or not target.is_file() or target.suffix not in STATIC_TYPES:
                return self._json(HTTPStatus.NOT_FOUND, {"error": "Not found"})
            return self._send(HTTPStatus.OK, target.read_bytes(), STATIC_TYPES[target.suffix])

        def _redirect_uri(self) -> str:
            # Google's desktop clients accept any loopback port, so the sign-in comes straight back here.
            return f"http://127.0.0.1:{self.server.server_address[1]}/oauth/youtube"

        def _host_ok(self) -> bool:
            host = (self.headers.get("Host") or "").rsplit(":", 1)[0].strip("[]").lower()
            if host in allowed_hosts:
                return True
            self._json(HTTPStatus.FORBIDDEN, {"error": "Blueit only answers requests to localhost."})
            return False

        def do_GET(self):
            if not self._host_ok():
                return
            url = urlparse(self.path)
            params = {k: v[-1] for k, v in parse_qs(url.query).items()}
            try:
                if url.path == "/" or (url.path.startswith("/assets/") and STATIC.is_dir()):
                    return self._static(url.path)
                if url.path == "/api/story":
                    return self._json(HTTPStatus.OK, app.story(params))
                if url.path == "/api/doctor":
                    return self._json(HTTPStatus.OK, app.doctor())
                if url.path == "/api/settings":
                    return self._json(HTTPStatus.OK, app.settings())
                if url.path.startswith("/media/"):
                    parts = url.path.split("/")
                    if len(parts) != 4:
                        raise BadRequest("Not a story file.")
                    path = app.media_path(parts[2], parts[3])
                    kind, size = MEDIA_TYPES[path.suffix.lower()], path.stat().st_size
                    wanted = byte_range(self.headers.get("Range"), size)
                    if wanted is None:
                        return self._send(HTTPStatus.OK, path.read_bytes(), kind, {"Accept-Ranges": "bytes"})
                    start, end = wanted
                    with path.open("rb") as f:
                        f.seek(start)
                        chunk = f.read(end - start + 1)
                    return self._send(HTTPStatus.PARTIAL_CONTENT, chunk, kind,
                                      {"Accept-Ranges": "bytes", "Content-Range": f"bytes {start}-{end}/{size}"})
                if url.path == "/api/voices":
                    return self._json(HTTPStatus.OK, app.voices())
                if url.path == "/api/voices/clip":
                    path = app.voice_clip(params.get("voice", ""), params.get("which", "prompt"))
                    return self._send(HTTPStatus.OK, path.read_bytes(), "audio/wav")
                if url.path == "/api/options":
                    return self._json(HTTPStatus.OK, app.options())
                if url.path == "/api/library":
                    return self._json(HTTPStatus.OK, app.library(params))
                if url.path == "/api/job":
                    return self._json(HTTPStatus.OK, app.status())
                if url.path == "/api/youtube":
                    return self._json(HTTPStatus.OK, app.youtube_status())
                if url.path == "/oauth/youtube":
                    try:
                        app.youtube_callback(params, self._redirect_uri())
                        msg = "Connected to YouTube. You can close this tab and go back to Blueit."
                    except BadRequest as e:
                        msg = f"Couldn't connect: {e}"
                    page = f"<!doctype html><meta charset=utf-8><title>Blueit</title><p style='font:18px system-ui;margin:60px'>{html.escape(msg)}</p>"
                    return self._send(HTTPStatus.OK, page.encode(), "text/html; charset=utf-8")
            except BadRequest as e:
                return self._json(HTTPStatus.BAD_REQUEST, {"error": str(e)})
            self._json(HTTPStatus.NOT_FOUND, {"error": "Not found"})

        def do_POST(self):
            if not self._host_ok():
                return
            url = urlparse(self.path)
            if url.path == "/api/voices/upload":         # a WAV recorded on the page: raw bytes, not JSON
                return self._voice_upload(url)
            if not (self.headers.get("Content-Type") or "").startswith("application/json"):
                return self._json(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, {"error": "Send JSON."})
            try:
                size = min(int(self.headers.get("Content-Length") or 0), 10_000)
                params = json.loads(self.rfile.read(size) or b"{}")
                if not isinstance(params, dict):
                    raise BadRequest("Send a JSON object.")
                route = {"/api/find": app.find, "/api/mark": app.mark, "/api/make": app.make,
                         "/api/youtube/connect": lambda p: app.youtube_connect(self._redirect_uri()),
                         "/api/share/youtube": app.share_youtube, "/api/voices": app.voice_action}.get(url.path)
                if not route:
                    return self._json(HTTPStatus.NOT_FOUND, {"error": "Not found"})
                return self._json(HTTPStatus.OK, route(params))
            except (BadRequest, json.JSONDecodeError, ValueError) as e:
                return self._json(HTTPStatus.BAD_REQUEST, {"error": str(e)})

        def _voice_upload(self, url):
            if (self.headers.get("Content-Type") or "").split(";")[0].strip() not in ("audio/wav", "audio/x-wav", "audio/wave"):
                return self._json(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, {"error": "Send the recording as a WAV file."})
            size = int(self.headers.get("Content-Length") or 0)
            if not 44 < size <= MAX_RECORDING:
                return self._json(HTTPStatus.BAD_REQUEST, {"error": "The recording is empty or longer than about 10 minutes."})
            params = {k: v[-1] for k, v in parse_qs(url.query).items()}
            try:
                data = app.voice_upload(params.get("name", ""), params.get("mine") == "1", self.rfile.read(size))
                return self._json(HTTPStatus.OK, data)
            except BadRequest as e:
                return self._json(HTTPStatus.BAD_REQUEST, {"error": str(e)})

    return Handler


def make_server(app: App, port: int = 8642) -> ThreadingHTTPServer:
    allowed = {"127.0.0.1", "localhost", "::1"}
    return ThreadingHTTPServer(("127.0.0.1", port), make_handler(app, allowed))


def serve(cfg: Config, port: int = 8642, out: Path = Path("listings"), env: str = ".env",
          library: Path = Path("library.db"), open_browser: bool = True, config_path: Path = Path("blueit.toml")) -> int:
    server = make_server(App(cfg, library, out, env=env, config_path=config_path), port)
    url = f"http://127.0.0.1:{server.server_address[1]}/"
    print(f"Blueit is running at {url}  (Ctrl+C to stop)")
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        server.server_close()
    return 0


# Shown only when the React app hasn't been built (a fresh clone without blueit/static).
NOT_BUILT = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Blueit</title>
<style>body{font:16px/1.5 system-ui,sans-serif;background:#0f1420;color:#e6e9f0;max-width:640px;margin:60px auto;padding:0 16px}
code{background:#171e2e;padding:2px 6px;border-radius:4px}</style></head>
<body><h1>Blueit</h1><p>The page hasn't been built yet. In the <code>ui</code> folder run:</p>
<p><code>npm install</code> then <code>npm run build</code></p><p>and reload this page.</p></body></html>
"""

