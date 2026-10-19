#!/usr/bin/env python3
"""The Afterscroll app's own store — real-life saves and their clips.

The app used to read Notion. It doesn't any more: Notion is slow to query, its
file links expire hourly, it caps uploads at 5 MB, and it would need every user
to have their own workspace. The bot already runs on this server, so the app's
data lives next to it: one SQLite file plus a folder of clips, served by api.py.

Only real-life categories (folders.REAL_LIFE) are stored here. Knowledge notes
keep going to Notion and the vault, where the content work happens.
"""

import hashlib
import json
import os
import pathlib
import sqlite3
import time

import folders

ROOT = pathlib.Path(os.environ.get("APP_DATA_DIR") or pathlib.Path(__file__).resolve().parent / "app-data")
DB = ROOT / "app.db"
CLIPS = ROOT / "clips"
INBOX = ROOT / "inbox"

_SCHEMA = """
create table if not exists saves (
  id text primary key, url text not null, category text not null, title text,
  author text, summary text, details text, created text, updated real
);
create table if not exists clips (
  save_id text not null, idx integer not null, name text, file text not null,
  start real, end real, primary key (save_id, idx)
);
"""


def save_id(url: str) -> str:
    return hashlib.sha1(url.encode()).hexdigest()[:12]


def _db() -> sqlite3.Connection:
    ROOT.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB, timeout=10)
    c.row_factory = sqlite3.Row
    c.executescript(_SCHEMA)
    return c


def upsert(url: str, category: str, title: str, author: str = "", summary: str = "",
           details: dict | None = None, created: str = "") -> str | None:
    """Store a real-life save. Knowledge categories are ignored (returns None),
    and a save re-filed OUT of a real-life category is removed from the app."""
    sid = save_id(url)
    category = folders.normalize(category)
    with _db() as c:
        if category not in folders.REAL_LIFE:
            c.execute("delete from saves where id=?", (sid,))
            return None
        c.execute(
            "insert into saves (id,url,category,title,author,summary,details,created,updated) "
            "values (?,?,?,?,?,?,?,?,?) on conflict(id) do update set category=excluded.category, "
            "title=excluded.title, author=excluded.author, summary=excluded.summary, "
            "details=excluded.details, updated=excluded.updated",
            (sid, url, category, title, author, summary, json.dumps(details or {}, ensure_ascii=False),
             created or time.strftime("%Y-%m-%d"), time.time()))
    return sid


def set_clips(sid: str, clips: list[dict]) -> None:
    """Replace a save's clips. Each: {name, file (relative to CLIPS), start, end};
    index 0 is the whole-reel loop, 1..n the individual moves."""
    with _db() as c:
        c.execute("delete from clips where save_id=?", (sid,))
        c.executemany("insert into clips (save_id,idx,name,file,start,end) values (?,?,?,?,?,?)",
                      [(sid, i, k.get("name"), k["file"], k.get("start"), k.get("end"))
                       for i, k in enumerate(clips)])
        c.execute("update saves set updated=? where id=?", (time.time(), sid))


def all_saves() -> list[dict]:
    with _db() as c:
        rows = [dict(r) for r in c.execute("select * from saves order by created desc, updated desc")]
        clips = {}
        for k in c.execute("select * from clips order by save_id, idx"):
            clips.setdefault(k["save_id"], []).append(
                {"name": k["name"], "url": f"/v1/clips/{k['file']}", "start": k["start"], "end": k["end"]})
    for r in rows:
        r["details"] = json.loads(r["details"] or "{}")
        cl = clips.get(r["id"], [])
        r["loop"] = cl[0]["url"] if cl else None
        r["moves"] = cl[1:]
    return rows


def enqueue(url: str, note: str = "") -> pathlib.Path:
    """A link shared from the phone, waiting for the bot to process it."""
    INBOX.mkdir(parents=True, exist_ok=True)
    p = INBOX / f"{time.time_ns()}.json"
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps({"url": url, "note": note}))
    tmp.rename(p)  # atomic: the bot never reads a half-written file
    return p


def take_inbox() -> list[tuple[str, str]]:
    """Claim every queued link (oldest first) and delete its file."""
    if not INBOX.exists():
        return []
    out = []
    for p in sorted(INBOX.glob("*.json")):
        try:
            d = json.loads(p.read_text())
        except (OSError, ValueError):
            d = {}
        p.unlink(missing_ok=True)
        url = str(d.get("url") or "").strip()
        if url.startswith(("http://", "https://")):
            out.append((url, str(d.get("note") or "").strip()))
    return out
