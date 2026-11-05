"""A small page in your browser for picking what stories to find, from drop-down menus.

  python -m blueit ui          opens http://127.0.0.1:8642

The menus choose the kind of story (scary, revenge, work…), one subreddit or all of that kind, how far
back to look, how long the stories should be, the fewest upvotes and how many posts to look at. "Find
stories" runs the same search as `blueit fetch` with those choices and shows the finished stories it
found; the Library tab lists everything saved so far and marks stories narrated.

Only the Python standard library is used. The server listens on 127.0.0.1 only, answers only requests
addressed to localhost (so a web page elsewhere can't reach it through DNS tricks), and only takes JSON
in POST requests (so another site can't submit a form to it).
"""
from __future__ import annotations

import json
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

WORDS_PER_MINUTE = 150


class BadRequest(ValueError):
    pass


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

    def __init__(self, cfg: Config, library: Path, out: Path = Path("listings"), reddit_factory=None, env=".env"):
        self.cfg = cfg
        self.library_path = Path(library)
        self.out = Path(out)
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


def make_handler(app: App, allowed_hosts: set[str]):
    class Handler(BaseHTTPRequestHandler):
        server_version = "blueit"

        def log_message(self, *args):          # keep the terminal quiet
            pass

        def _send(self, status: int, body: bytes, kind: str):
            self.send_response(status)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy",
                             "default-src 'none'; script-src 'self' 'unsafe-inline'; style-src 'unsafe-inline'; "
                             "connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, status: int, data: dict):
            self._send(status, json.dumps(data).encode(), "application/json; charset=utf-8")

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
                if url.path == "/":
                    return self._send(HTTPStatus.OK, PAGE.encode(), "text/html; charset=utf-8")
                if url.path == "/api/options":
                    return self._json(HTTPStatus.OK, app.options())
                if url.path == "/api/library":
                    return self._json(HTTPStatus.OK, app.library(params))
            except BadRequest as e:
                return self._json(HTTPStatus.BAD_REQUEST, {"error": str(e)})
            self._json(HTTPStatus.NOT_FOUND, {"error": "Not found"})

        def do_POST(self):
            if not self._host_ok():
                return
            if not (self.headers.get("Content-Type") or "").startswith("application/json"):
                return self._json(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, {"error": "Send JSON."})
            try:
                size = min(int(self.headers.get("Content-Length") or 0), 10_000)
                params = json.loads(self.rfile.read(size) or b"{}")
                if not isinstance(params, dict):
                    raise BadRequest("Send a JSON object.")
                route = {"/api/find": app.find, "/api/mark": app.mark}.get(urlparse(self.path).path)
                if not route:
                    return self._json(HTTPStatus.NOT_FOUND, {"error": "Not found"})
                return self._json(HTTPStatus.OK, route(params))
            except (BadRequest, json.JSONDecodeError, ValueError) as e:
                return self._json(HTTPStatus.BAD_REQUEST, {"error": str(e)})

    return Handler


def make_server(app: App, port: int = 8642) -> ThreadingHTTPServer:
    allowed = {"127.0.0.1", "localhost", "::1"}
    return ThreadingHTTPServer(("127.0.0.1", port), make_handler(app, allowed))


def serve(cfg: Config, port: int = 8642, out: Path = Path("listings"), env: str = ".env",
          library: Path = Path("library.db"), open_browser: bool = True) -> int:
    server = make_server(App(cfg, library, out, env=env), port)
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


PAGE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Blueit</title>
<style>
  :root { --bg: #0f1420; --panel: #171e2e; --line: #2a3448; --text: #e6e9f0; --muted: #94a0b8; --accent: #4f8cff; --ok: #3fb67b; --bad: #ff7a7a; }
  * { box-sizing: border-box; }
  body { margin: 0; font: 15px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif; background: var(--bg); color: var(--text); }
  header { padding: 14px 20px; border-bottom: 1px solid var(--line); background: var(--panel); display: flex; align-items: baseline; gap: 12px; flex-wrap: wrap; }
  header h1 { margin: 0; font-size: 1.2rem; } header p { margin: 0; color: var(--muted); font-size: .9rem; }
  main { max-width: 980px; margin: 0 auto; padding: 18px 20px 40px; }
  .tabs { display: flex; gap: 6px; margin-bottom: 14px; }
  .tabs button[aria-selected="true"] { background: var(--accent); color: #fff; border-color: transparent; }
  button, select, input { font: inherit; color: var(--text); background: #1d2537; border: 1px solid var(--line); border-radius: 8px; padding: 8px 12px; }
  button { cursor: pointer; } button:disabled { opacity: .6; cursor: wait; }
  button.primary { background: var(--accent); border-color: transparent; color: #fff; font-weight: 600; }
  :focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
  form.menus { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 12px; padding: 16px; background: var(--panel); border: 1px solid var(--line); border-radius: 12px; }
  label { display: flex; flex-direction: column; gap: 4px; font-size: .85rem; color: var(--muted); }
  .actions { display: flex; align-items: end; gap: 10px; }
  .status { margin: 12px 2px; color: var(--muted); min-height: 1.5em; }
  .status.error { color: var(--bad); }
  details.log { margin: 4px 0 12px; color: var(--muted); font-size: .85rem; } details.log pre { white-space: pre-wrap; margin: 6px 0 0; }
  ol.stories { list-style: none; margin: 0; padding: 0; display: grid; gap: 10px; }
  .story { padding: 12px 14px; background: var(--panel); border: 1px solid var(--line); border-radius: 10px; display: flex; gap: 12px; align-items: flex-start; }
  .story .body { flex: 1; min-width: 0; } .story a { color: var(--text); font-weight: 600; text-decoration: none; } .story a:hover { text-decoration: underline; }
  .meta { color: var(--muted); font-size: .85rem; margin-top: 2px; }
  .pill { display: inline-block; font-size: .72rem; padding: 1px 8px; border-radius: 99px; border: 1px solid var(--line); margin-left: 6px; }
  .pill.narrated { color: var(--ok); border-color: var(--ok); }
  [hidden] { display: none !important; }
</style>
</head>
<body>
<header><h1>Blueit</h1><p>Pick what stories to find, then narrate the ones you like.</p></header>
<main>
  <div class="tabs" role="tablist">
    <button role="tab" id="tabFind" aria-selected="true" aria-controls="find">Find stories</button>
    <button role="tab" id="tabLib" aria-selected="false" aria-controls="lib">Library</button>
  </div>

  <section id="find" role="tabpanel" aria-labelledby="tabFind">
    <form class="menus" id="findForm">
      <label>What kind of stories <select id="kind" name="kind"></select></label>
      <label>Where <select id="subreddit" name="subreddit"></select></label>
      <label>Posted in the <select id="time" name="time"></select></label>
      <label>How long <select id="length" name="length"></select></label>
      <label>At least this many upvotes <select id="minScore" name="minScore"></select></label>
      <label>Posts to look at in each place <select id="limit" name="limit"></select></label>
      <label>Words to look for (optional) <input id="words" name="words" maxlength="100" placeholder="e.g. cabin"></label>
      <div class="actions"><button class="primary" id="go">Find stories</button></div>
    </form>
    <p class="status" id="findStatus" role="status"></p>
    <details class="log" id="findLog" hidden><summary>What Blueit looked at</summary><pre></pre></details>
    <ol class="stories" id="results"></ol>
  </section>

  <section id="lib" role="tabpanel" aria-labelledby="tabLib" hidden>
    <form class="menus" id="libForm">
      <label>Show <select id="libStatus" name="status">
        <option value="new">Waiting to be narrated</option><option value="narrated">Narrated</option><option value="">All stories</option>
      </select></label>
      <label>Kind <select id="libKind" name="kind"><option value="">Every kind</option></select></label>
      <label>Words (optional) <input id="libWords" name="words" maxlength="100"></label>
      <div class="actions"><button id="libGo">Show</button></div>
    </form>
    <p class="status" id="libStatusText" role="status"></p>
    <ol class="stories" id="library"></ol>
  </section>
</main>
<script>
const $ = (id) => document.getElementById(id);
let OPTIONS;

function fill(select, items, value) {
  select.replaceChildren(...items.map(([v, label]) => new Option(label, v)));
  if (value !== undefined) select.value = String(value);
}

function fillWhere() {
  const kind = OPTIONS.kinds.find((k) => k.id === $('kind').value);
  fill($('subreddit'), [['', `All ${kind.subreddits.length} places`], ...kind.subreddits.map((s) => [s, `r/${s}`])]);
}

async function api(path, body) {
  const res = await fetch(path, body ? { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) } : {});
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || res.statusText);
  return data;
}

function storyItem(s) {
  const li = document.createElement('li');
  li.className = 'story';
  const body = document.createElement('div');
  body.className = 'body';
  const a = Object.assign(document.createElement('a'), { href: s.url, target: '_blank', rel: 'noopener', textContent: s.title });
  const pill = Object.assign(document.createElement('span'), { className: `pill ${s.status}`, textContent: s.status === 'new' ? 'waiting' : 'narrated' });
  const meta = Object.assign(document.createElement('div'), { className: 'meta',
    textContent: `r/${s.subreddit} · u/${s.author} · ${s.words.toLocaleString()} words (about ${s.minutes} min) · ${s.score.toLocaleString()} upvotes${s.parts ? ` · ${s.parts} parts joined` : ''}` });
  body.append(a, pill, meta);
  const button = Object.assign(document.createElement('button'), { textContent: s.status === 'new' ? 'Mark narrated' : 'Mark not narrated' });
  button.addEventListener('click', async () => {
    button.disabled = true;
    try { const { story } = await api('/api/mark', { id: s.id, status: s.status === 'new' ? 'narrated' : 'new' }); li.replaceWith(storyItem(story)); }
    catch (e) { button.disabled = false; alert(e.message); }
  });
  li.append(body, button);
  return li;
}

$('findForm').addEventListener('submit', async (e) => {
  e.preventDefault();
  const params = Object.fromEntries(new FormData(e.target));
  $('go').disabled = true;
  $('findStatus').className = 'status';
  $('findStatus').textContent = 'Searching Reddit… this can take a minute when there are series to join.';
  $('results').replaceChildren();
  $('findLog').hidden = true;
  try {
    const data = await api('/api/find', params);
    if (!data.ok) throw new Error(data.error);
    $('findLog').hidden = !data.log.length;
    $('findLog').querySelector('pre').textContent = data.log.join('\n');
    $('results').replaceChildren(...data.stories.map(storyItem));
    $('findStatus').textContent = data.stories.length
      ? `${data.stories.length} finished ${data.stories.length === 1 ? 'story' : 'stories'} found and saved to your library.`
      : 'No finished stories matched. Try a longer time range, fewer upvotes or any length.';
  } catch (err) {
    $('findStatus').className = 'status error';
    $('findStatus').textContent = err.message;
  } finally {
    $('go').disabled = false;
  }
});

async function showLibrary() {
  const params = new URLSearchParams(new FormData($('libForm')));
  try {
    const data = await api(`/api/library?${params}`);
    $('library').replaceChildren(...data.stories.map(storyItem));
    $('libStatusText').className = 'status';
    $('libStatusText').textContent = `${data.counts.new} waiting, ${data.counts.narrated} narrated in your library. Showing ${data.stories.length}.`;
  } catch (err) { $('libStatusText').className = 'status error'; $('libStatusText').textContent = err.message; }
}
$('libForm').addEventListener('submit', (e) => { e.preventDefault(); showLibrary(); });
['libStatus', 'libKind'].forEach((id) => $(id).addEventListener('change', showLibrary));

for (const [tab, panel] of [['tabFind', 'find'], ['tabLib', 'lib']]) {
  $(tab).addEventListener('click', () => {
    for (const [t, p] of [['tabFind', 'find'], ['tabLib', 'lib']]) { $(t).setAttribute('aria-selected', String(t === tab)); $(p).hidden = t !== tab; }
    if (panel === 'lib') showLibrary();
  });
}

(async () => {
  OPTIONS = await api('/api/options');
  const d = OPTIONS.defaults;
  fill($('kind'), OPTIONS.kinds.map((k) => [k.id, k.label]), d.kind);
  fill($('time'), OPTIONS.times.map((t) => [t.id, t.label]), d.time);
  fill($('length'), OPTIONS.lengths.map((l) => [l.id, l.label]), d.length);
  fill($('minScore'), OPTIONS.minScores.map((n) => [n, n ? n.toLocaleString() : 'Any']), d.minScore);
  fill($('limit'), OPTIONS.limits.map((n) => [n, String(n)]), d.limit);
  $('libKind').append(...OPTIONS.kinds.map((k) => new Option(k.label, k.id)));
  fillWhere();
  $('kind').addEventListener('change', fillWhere);
})();
</script>
</body>
</html>
"""
