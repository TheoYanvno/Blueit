"""Uploading a made video to YouTube with the YouTube Data API v3.

You use your own Google Cloud project: create an OAuth client of type "Desktop app", download its
JSON and save it as youtube_client.json in your Blueit folder (see the README). The first time you
share, Google asks you to sign in and allow uploads; the token is then saved in youtube_token.json
next to it. Both files hold secrets: they are in .gitignore and never leave your computer except to
talk to Google.

Only the standard library is used. Network calls go through `http`, a function that takes a
urllib Request and returns (status, headers, body), so tests can swap in a fake.
"""
from __future__ import annotations

import json
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
UPLOAD_URL = "https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable&part=snippet,status"
SCOPE = "https://www.googleapis.com/auth/youtube.upload"
PRIVACY = ("private", "unlisted", "public")
CHUNK = 8 * 1024 * 1024


class YouTubeError(Exception):
    pass


def urllib_http(req: urllib.request.Request, timeout: int = 120):
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers or {}), e.read()


@dataclass
class Client:
    client_id: str
    client_secret: str

    @classmethod
    def load(cls, path: Path) -> "Client":
        if not path.is_file():
            raise YouTubeError(f"No {path.name} yet. Create a Desktop OAuth client in Google Cloud with the YouTube "
                               f"Data API turned on, download its JSON and save it as {path} (see the README).")
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            info = data.get("installed") or data.get("web") or data
            return cls(info["client_id"], info["client_secret"])
        except (ValueError, KeyError, TypeError) as e:
            raise YouTubeError(f"{path.name} isn't a Google OAuth client file: {e}") from None


def auth_url(client: Client, redirect_uri: str, state: str | None = None) -> tuple[str, str]:
    """The Google sign-in page to send the person to, and the state value to check when they come back."""
    state = state or secrets.token_urlsafe(16)
    q = urllib.parse.urlencode({"client_id": client.client_id, "redirect_uri": redirect_uri, "response_type": "code",
                                "scope": SCOPE, "access_type": "offline", "prompt": "consent", "state": state})
    return f"{AUTH_URL}?{q}", state


def _token_request(fields: dict, http) -> dict:
    req = urllib.request.Request(TOKEN_URL, data=urllib.parse.urlencode(fields).encode(),
                                 headers={"Content-Type": "application/x-www-form-urlencoded"}, method="POST")
    status, _, body = http(req)
    try:
        data = json.loads(body or b"{}")
    except ValueError:
        data = {}
    if status != 200 or "access_token" not in data:
        raise YouTubeError(f"Google refused the sign-in ({status}): {data.get('error_description') or data.get('error') or 'no details'}")
    return data


def exchange_code(client: Client, code: str, redirect_uri: str, token_path: Path, http=urllib_http, now=time.time) -> dict:
    data = _token_request({"code": code, "client_id": client.client_id, "client_secret": client.client_secret,
                           "redirect_uri": redirect_uri, "grant_type": "authorization_code"}, http)
    token = {"access_token": data["access_token"], "refresh_token": data.get("refresh_token"),
             "expires_at": now() + int(data.get("expires_in", 3600))}
    save_token(token, token_path)
    return token


def save_token(token: dict, path: Path) -> None:
    path.write_text(json.dumps(token), encoding="utf-8")
    try:
        path.chmod(0o600)                          # only you can read it (no effect on Windows)
    except OSError:
        pass


def access_token(client: Client, token_path: Path, http=urllib_http, now=time.time) -> str:
    """A working access token, refreshed with the saved refresh token when it's about to expire."""
    if not token_path.is_file():
        raise YouTubeError("Not connected to YouTube yet. Press Connect YouTube on the page (or run `blueit youtube connect`).")
    try:
        token = json.loads(token_path.read_text(encoding="utf-8"))
    except ValueError:
        raise YouTubeError(f"{token_path.name} is damaged. Delete it and connect again.") from None
    if token.get("access_token") and token.get("expires_at", 0) - 60 > now():
        return token["access_token"]
    if not token.get("refresh_token"):
        raise YouTubeError("The YouTube sign-in has expired. Connect again.")
    data = _token_request({"refresh_token": token["refresh_token"], "client_id": client.client_id,
                           "client_secret": client.client_secret, "grant_type": "refresh_token"}, http)
    token.update(access_token=data["access_token"], expires_at=now() + int(data.get("expires_in", 3600)))
    save_token(token, token_path)
    return token["access_token"]


def video_details(title: str, author: str, subreddit: str, url: str, upright: bool, part: str | None = None,
                  privacy: str = "private", tags: list[str] | None = None) -> dict:
    """The title, description and settings sent with the upload. Titles are cut to YouTube's 100
    characters; upright videos of a minute or less get #Shorts so YouTube treats them as Shorts."""
    if privacy not in PRIVACY:
        raise YouTubeError(f"Privacy must be one of {', '.join(PRIVACY)}.")
    label = f" ({part})" if part else ""
    shorts = " #Shorts" if upright and part else ""
    room = 100 - len(label) - len(shorts)
    clean = " ".join(title.replace("<", "").replace(">", "").split())
    full_title = (clean if len(clean) <= room else clean[: room - 1].rstrip() + "…") + label + shorts
    description = (f"{clean}\n\nWritten by u/{author} on r/{subreddit}: {url}\n"
                   f"Narrated with Blueit.{' #Shorts' if shorts else ''}")[:5000]
    return {"snippet": {"title": full_title, "description": description, "categoryId": "24",
                        "tags": (tags or ["story", subreddit])[:15]},
            "status": {"privacyStatus": privacy, "selfDeclaredMadeForKids": False}}


def upload(video: Path, details: dict, token: str, http=urllib_http, progress=None) -> str:
    """Resumable upload in 8 MB chunks. Returns the new video's id."""
    size = video.stat().st_size
    start = urllib.request.Request(UPLOAD_URL, data=json.dumps(details).encode(), method="POST", headers={
        "Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=UTF-8",
        "X-Upload-Content-Type": "video/mp4", "X-Upload-Content-Length": str(size)})
    status, headers, body = http(start)
    where = {k.lower(): v for k, v in headers.items()}.get("location")
    if status != 200 or not where:
        raise YouTubeError(f"YouTube didn't accept the upload ({status}): {_reason(body)}")
    sent = 0
    with video.open("rb") as f:
        while sent < size:
            chunk = f.read(CHUNK)
            end = sent + len(chunk) - 1
            req = urllib.request.Request(where, data=chunk, method="PUT", headers={
                "Authorization": f"Bearer {token}", "Content-Length": str(len(chunk)),
                "Content-Range": f"bytes {sent}-{end}/{size}"})
            status, headers, body = http(req)
            if status in (200, 201):
                if progress:
                    progress(size, size)
                return json.loads(body)["id"]
            if status != 308:
                raise YouTubeError(f"The upload stopped ({status}): {_reason(body)}")
            got = {k.lower(): v for k, v in headers.items()}.get("range")      # e.g. "bytes=0-8388607"
            sent = int(got.split("-")[1]) + 1 if got else 0     # no Range: nothing kept, start over
            f.seek(sent)
            if progress:
                progress(sent, size)
    raise YouTubeError("The upload ended without YouTube confirming the video.")


def _reason(body: bytes) -> str:
    try:
        return json.loads(body)["error"]["message"]
    except (ValueError, KeyError, TypeError):
        return (body or b"").decode(errors="replace")[:200] or "no details"
