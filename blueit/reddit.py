"""Reads posts through Reddit's official API (oauth.reddit.com), using only the standard library.

Reddit asks every API client to sign in with an app's id and secret and to send a descriptive
User-Agent. Blueit uses "application-only" sign-in (client_credentials): it reads public posts and
can't post, vote or see anything private. Credentials come from the environment or a .env file and
are never written anywhere by Blueit.
"""
from __future__ import annotations

import base64
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .story import Story

TOKEN_URL = "https://www.reddit.com/api/v1/access_token"
API = "https://oauth.reddit.com"
SETUP_HELP = """Reddit credentials are missing.

Blueit reads Reddit through the official API, which needs a free Reddit app:
  1. Sign in to Reddit and open https://www.reddit.com/prefs/apps
  2. Click "create another app", pick "script", and use http://localhost:8080 as the redirect URI
  3. Copy the id under the app's name and its secret into a .env file next to blueit.toml:
       REDDIT_CLIENT_ID=...
       REDDIT_CLIENT_SECRET=...
       REDDIT_USERNAME=your_reddit_username
See .env.example."""


class RedditError(RuntimeError):
    pass


class MissingCredentials(RedditError):
    def __init__(self):
        super().__init__(SETUP_HELP)


def load_env(path: str | Path = ".env", environ: dict | None = None) -> dict:
    """Reads KEY=value lines from a .env file; real environment variables win."""
    env = dict(environ if environ is not None else os.environ)
    p = Path(path)
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    return env


@dataclass
class Credentials:
    client_id: str
    client_secret: str
    username: str = "unknown"

    @classmethod
    def from_env(cls, env: dict) -> "Credentials":
        cid, secret = env.get("REDDIT_CLIENT_ID", ""), env.get("REDDIT_CLIENT_SECRET", "")
        if not cid or not secret:
            raise MissingCredentials()
        return cls(cid, secret, env.get("REDDIT_USERNAME") or "unknown")

    @property
    def user_agent(self) -> str:
        from . import __version__
        return f"python:blueit:{__version__} (by /u/{self.username})"


Opener = Callable[[urllib.request.Request, float], object]


def _default_open(req, timeout):
    return urllib.request.urlopen(req, timeout=timeout)


@dataclass
class Reddit:
    creds: Credentials
    opener: Opener = _default_open
    sleep: Callable[[float], None] = time.sleep
    clock: Callable[[], float] = time.time
    retries: int = 3
    timeout: float = 20.0
    _token: str | None = None
    _token_expires: float = 0.0
    _remaining: float | None = None
    _reset_at: float = 0.0
    calls: list = field(default_factory=list)

    # ---- sign-in ----
    def token(self) -> str:
        if self._token and self.clock() < self._token_expires - 60:
            return self._token
        basic = base64.b64encode(f"{self.creds.client_id}:{self.creds.client_secret}".encode()).decode()
        req = urllib.request.Request(
            TOKEN_URL,
            data=urllib.parse.urlencode({"grant_type": "client_credentials"}).encode(),
            headers={"Authorization": f"Basic {basic}", "User-Agent": self.creds.user_agent},
            method="POST",
        )
        data = self._send(req)
        if "access_token" not in data:
            raise RedditError(f"Reddit didn't return a token: {data.get('error', data)}")
        self._token = data["access_token"]
        self._token_expires = self.clock() + float(data.get("expires_in", 3600))
        return self._token

    # ---- requests ----
    def _wait_for_rate_limit(self):
        # Reddit sends how many requests are left and when the window resets. Out of requests: wait.
        if self._remaining is not None and self._remaining < 1:
            delay = max(0.0, self._reset_at - self.clock())
            if delay:
                self.sleep(delay)

    def _send(self, req) -> dict:
        last = None
        for attempt in range(self.retries + 1):
            self._wait_for_rate_limit()
            try:
                self.calls.append(req.full_url)
                with self.opener(req, self.timeout) as resp:
                    headers = resp.headers
                    if headers.get("X-Ratelimit-Remaining") is not None:
                        self._remaining = float(headers.get("X-Ratelimit-Remaining"))
                        self._reset_at = self.clock() + float(headers.get("X-Ratelimit-Reset", 0))
                    return json.loads(resp.read().decode("utf-8"))
            except urllib.error.HTTPError as e:
                last = e
                if e.code == 401 and "/api/v1/access_token" not in req.full_url:
                    self._token = None                     # token expired early: sign in again once
                    req.headers["Authorization"] = f"bearer {self.token()}"
                    continue
                if e.code in (429, 500, 502, 503, 504) and attempt < self.retries:
                    retry_after = e.headers.get("Retry-After") if e.headers else None
                    self.sleep(float(retry_after) if retry_after else 2 ** attempt)
                    continue
                raise RedditError(f"Reddit answered {e.code} for {req.full_url}") from e
            except urllib.error.URLError as e:
                last = e
                if attempt < self.retries:
                    self.sleep(2 ** attempt)
                    continue
                raise RedditError(f"Couldn't reach Reddit: {e.reason}") from e
        raise RedditError(f"Gave up after {self.retries + 1} tries: {last}")

    def get(self, path: str, **params) -> dict:
        query = urllib.parse.urlencode({k: v for k, v in params.items() if v not in (None, "")})
        req = urllib.request.Request(
            f"{API}{path}?{query}",
            headers={"Authorization": f"bearer {self.token()}", "User-Agent": self.creds.user_agent},
        )
        return self._send(req)

    # ---- listings ----
    def top(self, subreddit: str, time_filter: str = "month", limit: int = 25) -> dict:
        return self.get(f"/r/{subreddit}/top", t=time_filter, limit=min(limit, 100), raw_json=1)

    def search(self, subreddit: str, query: str, time_filter: str = "month", limit: int = 25, sort: str = "top") -> dict:
        return self.get(f"/r/{subreddit}/search", q=query, restrict_sr=1, sort=sort, t=time_filter,
                        limit=min(limit, 100), raw_json=1)

    def submitted(self, user: str, limit: int = 100) -> list[Story]:
        """A user's own posts, newest first (used to find the earlier parts of a series)."""
        listing = self.get(f"/user/{user}/submitted", sort="new", limit=min(limit, 100), raw_json=1)
        return [Story.from_reddit(c["data"]) for c in listing.get("data", {}).get("children", []) if c.get("kind") == "t3"]

    def stories(self, subreddit: str, query: str = "", time_filter: str = "month", limit: int = 25,
                min_score: int = 0) -> list[Story]:
        listing = self.search(subreddit, query, time_filter, limit) if query else self.top(subreddit, time_filter, limit)
        posts = [c["data"] for c in listing.get("data", {}).get("children", []) if c.get("kind") == "t3"]
        return [Story.from_reddit(p) for p in posts if p.get("is_self", True) and int(p.get("score", 0)) >= min_score]
