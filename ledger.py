#!/usr/bin/env python3
"""Tiny JSON ledger so processed links are remembered (dedup + resume).

One file, keyed by URL. Good enough for single-user; swap for Postgres
in the multi-user phase.
"""

import contextlib
import fcntl
import json
import logging
import os
import pathlib
import threading
import time

_LOCK = threading.Lock()
_LOCKFILE = pathlib.Path(__file__).resolve().parent / ".ledger.lock"


@contextlib.contextmanager
def _exclusive():
    """Lock across PROCESSES, not just threads.

    `bot.py --test` runs the whole pipeline against the same files as the live
    bot. Two processes doing read-modify-write on one JSON file is
    last-writer-wins, so one silently erases the other's entry. flock is
    released automatically if a process dies.
    """
    with _LOCK:
        with open(_LOCKFILE, "w") as fh:
            fcntl.flock(fh, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(fh, fcntl.LOCK_UN)
_PATH = pathlib.Path(__file__).resolve().parent / "ledger.json"
log = logging.getLogger("saved-to-notes.ledger")


def _load_file(path: pathlib.Path) -> dict:
    if path.exists():
        try:
            return json.loads(path.read_text())
        except json.JSONDecodeError:
            # Never silently start from scratch — that would re-process every
            # reel and duplicate it everywhere. Keep the damaged file for repair.
            backup = path.with_name(f"{path.stem}.corrupt-{int(time.time())}.json")
            try:
                path.rename(backup)
            except OSError:
                pass
            log.error("%s was corrupt — saved as %s and starting empty", path.name, backup.name)
            return {}
    return {}


def _save_file(path: pathlib.Path, data: dict) -> None:
    """Atomic write: a crash mid-save can never truncate the real file."""
    tmp = path.with_name(f"{path.name}.tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    os.replace(tmp, path)


def _load() -> dict:
    return _load_file(_PATH)


def get(url: str) -> dict | None:
    return _load().get(url)


def all_done() -> dict:
    """Every completed entry — the content-dedup sweep reads sig/title/path."""
    return {u: r for u, r in _load().items()
            if isinstance(r, dict) and r.get("status") == "done"}


def put(url: str, record: dict) -> None:
    with _exclusive():
        data = _load()
        data[url] = record
        _save_file(_PATH, data)


# --- pending recovery -----------------------------------------------------
# A reel is marked pending while it's being processed. If the bot is killed
# mid-reel (restart / sleep / crash), the entry survives and is resumed on
# the next startup — so reels are never silently dropped.
_PENDING = pathlib.Path(__file__).resolve().parent / "pending.json"


def _load_pending() -> dict:
    return _load_file(_PENDING)


def pending_add(url: str, chat_id: int, note: str = "") -> None:
    with _exclusive():
        d = _load_pending()
        rec = d.get(url) or {}
        # `note` is the user's own reason for saving; it must survive a restart
        # or the recovered note loses the intent it was meant to be written for.
        d[url] = {"chat_id": chat_id, "attempts": rec.get("attempts", 0),
                  "note": note or rec.get("note", "")}
        _save_file(_PENDING, d)


def pending_attempt(url: str) -> int:
    """Count a recovery attempt. Lets the resumer give up on a poison reel."""
    with _exclusive():
        d = _load_pending()
        if url not in d:
            return 0
        n = d[url].get("attempts", 0) + 1
        d[url]["attempts"] = n
        _save_file(_PENDING, d)
        return n


def pending_remove(url: str) -> None:
    with _exclusive():
        d = _load_pending()
        if d.pop(url, None) is not None:
            _save_file(_PENDING, d)


def pending_all() -> dict:
    return _load_pending()
