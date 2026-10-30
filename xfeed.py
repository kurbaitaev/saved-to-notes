#!/usr/bin/env python3
"""X bookmarks → the bot's normal pipeline.

    python3 xfeed.py              # hand every new X bookmark to the bot
    python3 xfeed.py --only ID    # hand over just this post (a test, or one that was missed)
    python3 xfeed.py --backfill   # also hand over the bookmarks from before the first run
    python3 xfeed.py --dry-run    # say what would be handed over, change nothing

The X importer (x-morning-reader, its own project on the server) copies new
bookmarks into a Notion database every night, but they never reached the vault:
11 of its 270 bookmarks had a note, each sent to the bot by hand. This reads the
importer's SQLite file read-only (`X_READER_DB` in .env) and drops each new post
into the bot's inbox as a plain save, the same as a link sent in Telegram, so it
gets a note, a Notion row and engine scoring. The X database stays an archive.

The first run only records what is already there, so turning this on doesn't
send 270 links at once; `--backfill` hands those over when wanted.
"""

import argparse
import datetime as dt
import json
import logging
import os
import pathlib
import sqlite3
import sys

PROJ = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(PROJ))

import acquire  # noqa: E402
import appdb  # noqa: E402
import ledger  # noqa: E402

log = logging.getLogger("saved-to-notes.xfeed")

STATE = PROJ / "logs" / "xfeed_state.json"
SOURCE = "x"


def load_env() -> None:
    f = PROJ / ".env"
    if f.exists():
        for line in f.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def post_url(post_id: str, raw: str) -> str:
    """The importer keeps the API's post with the author's handle added."""
    try:
        author = str(json.loads(raw).get("author") or "")
    except ValueError:
        author = ""
    return f"https://x.com/{author or 'i'}/status/{post_id}"


def bookmarks(db_path: str) -> list[tuple[str, str]]:
    """(post id, link) for every bookmark the importer has, oldest first."""
    db = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=30)
    try:
        rows = db.execute("SELECT id, raw FROM notes ORDER BY day, id").fetchall()
    finally:
        db.close()
    return [(str(i), post_url(str(i), raw)) for i, raw in rows]


def saved_ids() -> set[str]:
    """Post ids the bot already has, done or still queued: links sent by hand
    must not come back as a second note."""
    keys = list(ledger._load()) + list(ledger.pending_all())
    return {m.group(2) for k in keys if (m := acquire._TWEET_RE.search(str(k)))}


def _load_state() -> dict | None:
    try:
        return json.loads(STATE.read_text())
    except (OSError, ValueError):
        return None


def _save_state(state: dict) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=1))
    os.replace(tmp, STATE)


def run(db_path: str, only: str | None = None, backfill: bool = False, dry_run: bool = False) -> int:
    """Hand new bookmarks to the bot; return how many were handed over."""
    now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    state = _load_state()
    first = state is None
    state = state or {"since": now, "seen": {}}
    seen = state["seen"]
    have = saved_ids()
    handed = 0
    rows = dict(bookmarks(db_path))
    for pid, url in rows.items():
        if only and pid != only:
            if first:  # an --only test as the very first run still records the rest
                seen.setdefault(pid, {"url": url, "how": "before", "at": now})
            continue
        rec = seen.get(pid)
        if rec and not only and not (backfill and rec["how"] == "before"):
            continue
        if first and not backfill and not only:
            seen[pid] = {"url": url, "how": "before", "at": now}
            continue
        if pid in have:
            log.info("already saved: %s", url)
            seen[pid] = {"url": url, "how": "already saved", "at": now}
            continue
        log.info("%s %s", "would hand over" if dry_run else "handing over", url)
        if not dry_run:
            appdb.enqueue(url, source=SOURCE)
            seen[pid] = {"url": url, "how": "handed", "at": now}
        handed += 1
    if only and only not in rows:
        log.warning("no bookmark %s in the importer's database", only)
    if not dry_run:
        _save_state(state)
    before = sum(1 for r in seen.values() if r["how"] == "before")
    log.info("%d handed over%s; %d known, %d from before the first run",
             handed, " (dry run)" if dry_run else "", len(seen), before)
    return handed


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--only")
    ap.add_argument("--backfill", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    load_env()
    db_path = os.environ.get("X_READER_DB", "")
    if not db_path:
        log.info("X_READER_DB is not set; nothing to do")
        return 0
    if not pathlib.Path(db_path).is_file():
        log.error("X_READER_DB points at %s, which doesn't exist", db_path)
        return 1
    run(db_path, a.only, a.backfill, a.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
