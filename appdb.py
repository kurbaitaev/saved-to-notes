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
create table if not exists shares (
  url text primary key, ts real, status text, category text, title text
);
"""


def save_id(url: str) -> str:
    return hashlib.sha1(url.encode()).hexdigest()[:12]


def _db() -> sqlite3.Connection:
    ROOT.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB, timeout=10)
    c.row_factory = sqlite3.Row
    c.executescript(_SCHEMA)
    try:
        # Bumped on every re-cut. The phone caches clips by URL, so without it a
        # re-cut workout kept showing the previous cut's videos.
        c.execute("alter table clips add column version integer default 0")
    except sqlite3.OperationalError:
        pass  # already there
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
        v = int(time.time())
        c.executemany("insert into clips (save_id,idx,name,file,start,end,version) values (?,?,?,?,?,?,?)",
                      [(sid, i, k.get("name"), k["file"], k.get("start"), k.get("end"), v)
                       for i, k in enumerate(clips)])
        c.execute("update saves set updated=? where id=?", (time.time(), sid))


def all_saves() -> list[dict]:
    with _db() as c:
        rows = [dict(r) for r in c.execute("select * from saves order by created desc, updated desc")]
        clips = {}
        for k in c.execute("select * from clips order by save_id, idx"):
            q = f"?v={k['version'] or 0}"
            clips.setdefault(k["save_id"], []).append(
                {"name": k["name"], "url": f"/v1/clips/{k['file']}{q}",
                 "poster": f"/v1/clips/{k['file'].removesuffix('.mp4')}.jpg{q}",
                 "start": k["start"], "end": k["end"]})
    for r in rows:
        r["details"] = json.loads(r["details"] or "{}")
        cl = clips.get(r["id"], [])
        r["loop"] = cl[0]["url"] if cl else None
        r["poster"] = cl[0]["poster"] if cl else None
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


def take_inbox(limit: int | None = None) -> list[tuple[str, str]]:
    """Claim up to `limit` queued links (oldest first; all when None) and
    delete their files. The rest stay on disk, so a restart loses none."""
    if not INBOX.exists():
        return []
    out = []
    for p in sorted(INBOX.glob("*.json"))[:limit]:
        try:
            d = json.loads(p.read_text())
        except (OSError, ValueError):
            d = {}
        p.unlink(missing_ok=True)
        url = str(d.get("url") or "").strip()
        if url.startswith(("http://", "https://")):
            out.append((url, str(d.get("note") or "").strip()))
    return out


MAKING = ROOT / "making"


def mark_making(sid: str, on: bool) -> None:
    """A workout whose clips are still being cut (see bot._sync_app)."""
    f = MAKING / sid
    if on:
        MAKING.mkdir(parents=True, exist_ok=True)
        f.touch()
    else:
        f.unlink(missing_ok=True)


def pending_count() -> int:
    """Work the app should wait for: links still in the inbox, links the bot is
    processing (its pending ledger), and workouts whose clips are being cut."""
    n = len(list(INBOX.glob("*.json"))) if INBOX.exists() else 0
    # A crashed cut must not leave the app "sorting" forever: ignore markers
    # older than ten minutes.
    if MAKING.exists():
        n += sum(1 for f in MAKING.iterdir() if time.time() - f.stat().st_mtime < 600)
    ledger_file = pathlib.Path(__file__).resolve().parent / "pending.json"
    try:
        n += len(json.loads(ledger_file.read_text()) or {})
    except (OSError, ValueError):
        pass
    return n


# --- what happened to links shared from the phone ------------------------
# A share that turns out to be a knowledge note goes to Notion, not the app.
# Without this the "Sorting" card just vanished and the person never learned
# where their save went.

def share_started(url: str) -> None:
    with _db() as c:
        c.execute("insert into shares (url,ts,status) values (?,?,'sorting') on conflict(url) "
                  "do update set ts=excluded.ts, status='sorting', category=null, title=null",
                  (url, time.time()))


def share_done(url: str, status: str, category: str = "", title: str = "") -> None:
    """status: 'app' (in the app), 'notion' (filed as a knowledge note),
    'duplicate' (already saved) or 'failed'."""
    with _db() as c:
        c.execute("insert into shares (url,ts,status,category,title) values (?,?,?,?,?) "
                  "on conflict(url) do update set ts=excluded.ts, status=excluded.status, "
                  "category=excluded.category, title=excluded.title",
                  (url, time.time(), status, category, title))


def share_status(url: str) -> str | None:
    """The app's status for a link, or None when it wasn't shared from the app."""
    with _db() as c:
        r = c.execute("select status from shares where url=?", (url,)).fetchone()
    return r["status"] if r else None


def recent_shares(hours: int = 24, limit: int = 5) -> list[dict]:
    with _db() as c:
        return [dict(r) for r in c.execute(
            "select url, ts, status, category, title from shares where ts > ? "
            "order by ts desc limit ?", (time.time() - hours * 3600, limit))]


def set_moves(sid: str, moves: list[dict]) -> None:
    """Replace a save's move list (details.moves) — rebuilt from its clips, so
    the app shows one list in video order instead of reconciling two."""
    with _db() as c:
        row = c.execute("select details from saves where id=?", (sid,)).fetchone()
        if not row:
            return
        d = json.loads(row["details"] or "{}")
        d["moves"] = moves
        c.execute("update saves set details=?, updated=? where id=?",
                  (json.dumps(d, ensure_ascii=False), time.time(), sid))
