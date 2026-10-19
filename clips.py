#!/usr/bin/env python3
"""Looping clips for workout saves (category Move) — the Afterscroll Move screen.

The point of saving a mobility reel is doing it tomorrow morning without opening
Instagram. So for a Move save the whole reel is turned into a short, silent,
phone-sized loop and attached to its Notion page ("Clip" column), where the app
plays it on repeat.

Whole reel, not per-exercise cuts: the transcript has no timestamps, so cut
points would be guesses, and a wrong cut is worse than a full loop. The reel is
fetched again with yt-dlp because the acquire step deletes the video once it has
a transcript.

Everything here is best-effort: a missing clip must never fail the save.
"""

import json
import logging
import os
import pathlib
import shutil
import subprocess
import urllib.request
import uuid

log = logging.getLogger("saved-to-notes")

TMP = pathlib.Path("/tmp/saved-to-notes/clips")
MAX_SECONDS = 45          # longer reels are trimmed; routines are short
MAX_BYTES = 4_800_000     # Notion's free-plan upload cap is 5 MB per file
NOTION_VERSION = "2022-06-28"


class ClipError(Exception):
    pass


def _fetch(url: str, work: pathlib.Path) -> pathlib.Path:
    try:
        subprocess.run(["yt-dlp", "-q", "--no-playlist", "-f", "mp4/best",
                        "-o", str(work / "src.%(ext)s"), url],
                       check=True, capture_output=True, text=True, timeout=300)
    except FileNotFoundError as e:
        raise ClipError("yt-dlp is not installed") from e
    except subprocess.CalledProcessError as e:
        raise ClipError(f"yt-dlp failed: {(e.stderr or '')[-300:]}") from e
    except subprocess.TimeoutExpired as e:
        raise ClipError("yt-dlp timed out") from e
    vids = [p for p in work.glob("src.*") if p.suffix in {".mp4", ".mkv", ".webm", ".mov"}]
    if not vids:
        raise ClipError("yt-dlp produced no video (photo post?)")
    return vids[0]


def make_loop(source: str | pathlib.Path, out: pathlib.Path, crf: int = 30) -> pathlib.Path:
    """Silent H.264 loop, 480 px wide, at most MAX_SECONDS, small enough for Notion."""
    for attempt_crf, width in ((crf, 480), (crf + 5, 360), (crf + 9, 320)):
        subprocess.run(
            ["ffmpeg", "-nostdin", "-loglevel", "error", "-y", "-i", str(source),
             "-t", str(MAX_SECONDS), "-an", "-vf", f"scale={width}:-2,fps=24",
             "-c:v", "libx264", "-preset", "veryfast", "-crf", str(attempt_crf),
             "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(out)],
            check=True, capture_output=True, text=True, timeout=300)
        if out.stat().st_size <= MAX_BYTES:
            return out
    raise ClipError(f"clip still {out.stat().st_size} bytes after compressing")


def _notion(method: str, url: str, token: str, body: bytes | None, ctype: str) -> dict:
    req = urllib.request.Request(url, data=body, method=method, headers={
        "Authorization": f"Bearer {token}", "Notion-Version": NOTION_VERSION,
        "Content-Type": ctype})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.load(r)


def upload(path: pathlib.Path, token: str) -> str:
    """Notion's direct upload: create an upload, send the bytes. Returns its id."""
    created = _notion("POST", "https://api.notion.com/v1/file_uploads", token,
                      json.dumps({"filename": "loop.mp4", "content_type": "video/mp4"}).encode(),
                      "application/json")
    boundary = uuid.uuid4().hex
    body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; "
            f"filename=\"loop.mp4\"\r\nContent-Type: video/mp4\r\n\r\n").encode() \
        + path.read_bytes() + f"\r\n--{boundary}--\r\n".encode()
    sent = _notion("POST", f"https://api.notion.com/v1/file_uploads/{created['id']}/send", token,
                   body, f"multipart/form-data; boundary={boundary}")
    if sent.get("status") != "uploaded":
        raise ClipError(f"upload status {sent.get('status')}")
    return created["id"]


def attach(page_id: str, upload_id: str, token: str, column: str = "Clip") -> None:
    _notion("PATCH", f"https://api.notion.com/v1/pages/{page_id}", token, json.dumps(
        {"properties": {column: {"files": [
            {"type": "file_upload", "file_upload": {"id": upload_id}, "name": "loop.mp4"}]}}}
    ).encode(), "application/json")


def clip_for_page(source_url: str, page_id: str, video_path: str | None = None) -> str:
    """Fetch (or reuse) the video, loop it, attach it. Returns a status line."""
    token = os.environ.get("NOTION_TOKEN", "").strip()
    if not (token and page_id):
        return "no Notion page to attach to"
    work = TMP / uuid.uuid4().hex[:10]
    work.mkdir(parents=True, exist_ok=True)
    try:
        src = pathlib.Path(video_path) if video_path and pathlib.Path(video_path).exists() \
            else _fetch(source_url, work)
        loop = make_loop(src, work / "loop.mp4")
        attach(page_id, upload(loop, token), token)
        return f"clip attached ({loop.stat().st_size // 1024} KB)"
    finally:
        shutil.rmtree(work, ignore_errors=True)
