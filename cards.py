#!/usr/bin/env python3
"""Cards: each save becomes one next step, sent to where that work happens.

Saving something is not using it: 0 of 244 review questions were ever answered,
while saves that turned into a concrete thing to make (a remake) earned 203K
views. Context Engine already knows which project a save fits and what to do
with it. A card is that match turned into ONE step with buttons, waiting in the
project's topic, so the save arrives where the work is instead of on a shelf.

This file is the store and the rules. Surfaces only read and act on it:
Telegram topics (bot.py), the API (api.py) for the app and for Claude sessions
(the /saves skill). Every action and comment is kept as an event, so the number
that decides whether this works can be measured: the share of cards acted on
within 14 days.

Rules (the "Saves Into Action" design, Oct 31 2026):
- one card per save, in the topic of its best project
- at most CAP open cards per topic; the rest wait, newest save first
- an open card nobody acts on expires after EXPIRE_DAYS (the save stays in
  Notion); a waiting card whose save is older than that never shows up
- a note you wrote when saving wins: if it names a topic or a library, the
  card goes there

Personal setup (topics, their aliases, the libraries a resource can be added
to) lives in app-data/cards.json, never in this public repo; cards.example.json
shows the shape. Every row carries `user`, so a second person is a new value,
not a new schema.
"""

import datetime as dt
import hashlib
import json
import os
import pathlib
import re
import sqlite3
import time

import appdb
import folders

CAP = int(os.environ.get("CARDS_CAP", "3"))
EXPIRE_DAYS = 14
DONE = {"done", "remade", "added"}  # what counts as acting on a card
CLOSED = DONE | {"notnow", "expired", "stale"}

EXAMPLE = pathlib.Path(__file__).resolve().parent / "cards.example.json"

_SCHEMA = """
create table if not exists cards (
  id text primary key, user text not null, url text not null, save_id text,
  title text, category text, save_date text, topic text not null, project text,
  kind text not null, step text not null, steps text, also text, destination text,
  fit real, my_note text, status text not null, thread_id integer, message_id integer,
  created real, sent real, acted real, unique (user, url)
);
create table if not exists card_events (
  id integer primary key autoincrement, card_id text not null, user text not null,
  ts real not null, action text not null, text text
);
create table if not exists notes (
  user text not null, url text not null, note text not null, ts real,
  primary key (user, url)
);
create table if not exists topics (
  user text not null, topic text not null, thread_id integer, primary key (user, topic)
);
create table if not exists card_kv (k text primary key, v text);
"""


def default_user() -> str:
    """The owner: the first allowed Telegram id, which is also their chat id."""
    return os.environ.get("ALLOWED_USER_IDS", "").split(",")[0].strip() or "me"


def _db() -> sqlite3.Connection:
    appdb.ROOT.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(appdb.DB, timeout=10)
    c.row_factory = sqlite3.Row
    c.executescript(_SCHEMA)
    return c


def _row(r: sqlite3.Row | None) -> dict | None:
    if r is None:
        return None
    d = dict(r)
    for k in ("steps", "also"):
        d[k] = json.loads(d[k]) if d.get(k) else []
    return d


# --- personal setup -------------------------------------------------------

def config() -> dict:
    """Topics and libraries. Read on every call: it's tiny, and an edit on the
    server then needs no restart."""
    p = appdb.ROOT / "cards.json"
    for f in (p, EXAMPLE):
        try:
            return json.loads(f.read_text())
        except (OSError, ValueError):
            continue
    return {"topics": [], "destinations": []}


def topics() -> list[dict]:
    return config().get("topics", [])


def topic(tid: str) -> dict | None:
    return next((t for t in topics() if t["id"] == tid), None)


def topic_for_project(project: str) -> str | None:
    """Context Engine's project id → the topic it lives in. Editing shares the
    Content topic; a project with no topic gets no cards (it stays in Notion)."""
    return next((t["id"] for t in topics() if project in t.get("projects", [])), None)


def _mentions(text: str, words: list[str]) -> bool:
    """Word-start match, so a stem catches its forms ("музык" → "музыка"); short
    words must match whole, or "lak" would fire on "lake"."""
    low = f" {text.lower()} "
    return any(re.search(r"(?<!\w)" + re.escape(w.lower()) + (r"(?!\w)" if len(w) <= 4 else ""), low)
               for w in words if w)


def topic_named_in(text: str) -> str | None:
    """A topic the text names by id, name or alias ("for the gameplan site",
    "this is Lak"). None when it names none or more than one."""
    hits = [t["id"] for t in topics()
            if _mentions(text, [t["id"], t.get("name", "")] + t.get("aliases", []))]
    return hits[0] if len(hits) == 1 else None


def destination_for(text: str) -> dict | None:
    """The library a resource belongs in, by its keywords."""
    return next((d for d in config().get("destinations", []) if _mentions(text, d.get("keywords", []))),
                None)


def destination(did: str) -> dict | None:
    return next((d for d in config().get("destinations", []) if d["id"] == did), None)


# --- your own words -------------------------------------------------------

def remember_note(url: str, note: str, user: str | None = None) -> None:
    """What you typed when saving, kept apart from anything a model wrote, so it
    can steer the card and later the matcher."""
    note = (note or "").strip()
    if not note:
        return
    with _db() as c:
        c.execute("insert into notes (user,url,note,ts) values (?,?,?,?) on conflict(user,url) "
                  "do update set note=excluded.note, ts=excluded.ts",
                  (user or default_user(), url, note[:600], time.time()))


def note_for(url: str, user: str | None = None) -> str:
    with _db() as c:
        r = c.execute("select note from notes where user=? and url=?",
                      (user or default_user(), url)).fetchone()
    return r["note"] if r else ""


# --- creating cards -------------------------------------------------------

def card_id(user: str, url: str) -> str:
    return hashlib.sha1(f"{user}|{url}".encode()).hexdigest()[:12]


def propose(item: dict, user: str | None = None, now: float | None = None) -> str | None:
    """One matched save from Context Engine → a waiting card, or None.

    item: url, title, category, date (YYYY-MM-DD), project, fit, asset,
    application (the step), steps (list), also (other projects it fits).
    """
    user = user or default_user()
    now = now or time.time()
    url = str(item.get("url") or "").strip()
    step = str(item.get("application") or "").strip()
    category = folders.normalize(item.get("category"))
    if not url or not step or category in folders.REAL_LIFE:
        return None  # real-life saves live in the app, where they're done
    if _age_days(item.get("date"), now) > EXPIRE_DAYS:
        return None  # an old save is reference now, not a next step
    project = str(item.get("project") or "")
    tid = topic_for_project(project)
    mine = note_for(url, user)
    named = topic_named_in(mine) if mine else None
    if named:
        tid = named
    kind, dest = "step", None
    if str(item.get("asset") or "") in ("tool", "list", "reference") or item.get("resource"):
        # The title and your note say what a save IS; the step only says how to
        # use it, and "add the sound design" made a list of editing videos look
        # like a sound library.
        d = destination_for(" ".join([str(item.get("title") or ""), mine]))
        if d:
            kind, dest = "add", d["id"]
            tid = named or d.get("topic") or tid
    if not tid or not topic(tid):
        return None
    cid = card_id(user, url)
    with _db() as c:
        cur = c.execute(
            "insert or ignore into cards (id,user,url,save_id,title,category,save_date,topic,project,"
            "kind,step,steps,also,destination,fit,my_note,status,created) "
            "values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'queued',?)",
            (cid, user, url, item.get("save_id"), str(item.get("title") or "")[:200], category,
             item.get("date"), tid, project, kind, step[:300],
             json.dumps([str(s)[:200] for s in (item.get("steps") or [])][:4], ensure_ascii=False),
             json.dumps(item.get("also") or [], ensure_ascii=False), dest,
             float(item.get("fit") or 0), mine, now))
        if cur.rowcount:
            _event(c, cid, user, "proposed", project)
    return cid if cur.rowcount else None


def _age_days(date: str | None, now: float) -> float:
    try:
        d = dt.date.fromisoformat(str(date)[:10])
    except (TypeError, ValueError):
        return 0.0
    return (dt.date.fromtimestamp(now) - d).days


def _event(c: sqlite3.Connection, cid: str, user: str, action: str, text: str = "") -> None:
    c.execute("insert into card_events (card_id,user,ts,action,text) values (?,?,?,?,?)",
              (cid, user, time.time(), action, text))


# --- the flow of a card ---------------------------------------------------

def due(user: str | None = None) -> list[dict]:
    """Waiting cards that fit under each topic's cap, newest save first: a save
    is worth most on the day it was saved."""
    user = user or default_user()
    out = []
    with _db() as c:
        open_by = dict(c.execute("select topic, count(*) from cards where user=? and status='open' "
                                 "group by topic", (user,)).fetchall())
        for t in topics():
            room = CAP - open_by.get(t["id"], 0)
            if room <= 0:
                continue
            rows = c.execute("select * from cards where user=? and topic=? and status='queued' "
                             "order by save_date desc, fit desc, created desc limit ?",
                             (user, t["id"], room)).fetchall()
            out += [_row(r) for r in rows]
    return out


def opened(cid: str, thread_id: int | None, message_id: int | None) -> None:
    with _db() as c:
        c.execute("update cards set status='open', thread_id=?, message_id=?, sent=? where id=?",
                  (thread_id, message_id, time.time(), cid))
        r = c.execute("select user from cards where id=?", (cid,)).fetchone()
        if r:
            _event(c, cid, r["user"], "sent")


def get(cid: str) -> dict | None:
    with _db() as c:
        return _row(c.execute("select * from cards where id=?", (cid,)).fetchone())


def by_message(message_id: int, user: str | None = None) -> dict | None:
    with _db() as c:
        return _row(c.execute("select * from cards where user=? and message_id=?",
                              (user or default_user(), message_id)).fetchone())


def latest_open(tid: str, user: str | None = None) -> dict | None:
    with _db() as c:
        return _row(c.execute("select * from cards where user=? and topic=? and status='open' "
                              "order by sent desc limit 1", (user or default_user(), tid)).fetchone())


def act(cid: str, action: str, text: str = "") -> dict | None:
    """done / remade / added / notnow. Returns the card as it is now."""
    if action not in DONE | {"notnow"}:
        raise ValueError(f"unknown action {action!r}")
    with _db() as c:
        r = c.execute("select user, status from cards where id=?", (cid,)).fetchone()
        if not r:
            return None
        c.execute("update cards set status=?, acted=? where id=?", (action, time.time(), cid))
        _event(c, cid, r["user"], action, text)
    return get(cid)


def comment(cid: str, text: str) -> None:
    """Anything you write back about a card. Kept word for word: it is the
    clearest signal there is, and the matcher learns from it."""
    with _db() as c:
        r = c.execute("select user from cards where id=?", (cid,)).fetchone()
        if r:
            _event(c, cid, r["user"], "comment", text[:1000])


def move(cid: str, tid: str) -> dict | None:
    """You said the card belongs elsewhere: it changes topic and goes out again."""
    with _db() as c:
        r = c.execute("select user, topic from cards where id=?", (cid,)).fetchone()
        if not r or not topic(tid) or r["topic"] == tid:
            return None
        c.execute("update cards set topic=?, status='queued', message_id=null, thread_id=null "
                  "where id=?", (tid, cid))
        _event(c, cid, r["user"], "moved", f"{r['topic']}→{tid}")
    return get(cid)


def rewrite(cid: str, step: str, steps: list[str] | None = None) -> dict | None:
    with _db() as c:
        r = c.execute("select user from cards where id=?", (cid,)).fetchone()
        if not r:
            return None
        c.execute("update cards set step=?, steps=? where id=?",
                  (step[:300], json.dumps(steps or [], ensure_ascii=False), cid))
        _event(c, cid, r["user"], "rewritten", step[:300])
    return get(cid)


def set_note(url: str, note: str, user: str | None = None) -> dict | None:
    """A note written after the card was made: saved first, then shared again
    with a reason. It joins the card's events as a comment, so the matcher learns
    from it too. None when there's no card or nothing new."""
    user = user or default_user()
    cid = card_id(user, url)
    note = note.strip()[:600]
    with _db() as c:
        r = c.execute("select kind, destination, my_note from cards where id=?", (cid,)).fetchone()
        if not r or r["my_note"] == note:
            return None
        d = destination_for(note) if r["kind"] == "add" else None
        c.execute("update cards set my_note=?, destination=? where id=?",
                  (note, d["id"] if d else r["destination"], cid))
        _event(c, cid, user, "comment", note)
    return get(cid)


def topic_for_note(card: dict, note: str) -> str | None:
    """The topic a note sends a card to, by the rule propose() follows: one it
    names, or the home of a library it names. None when it points nowhere new."""
    tid = topic_named_in(note)
    if not tid and card["kind"] == "add":
        tid = (destination_for(note) or {}).get("topic")
    return tid if tid and tid != card["topic"] and topic(tid) else None


def applied(cid: str) -> None:
    """An added resource has gone into its library (done in a Claude session)."""
    with _db() as c:
        r = c.execute("select user from cards where id=?", (cid,)).fetchone()
        if r:
            _event(c, cid, r["user"], "applied")


def pending_adds(user: str | None = None) -> list[dict]:
    """Resources you tapped Add on that haven't gone into their library yet."""
    with _db() as c:
        return [_row(r) for r in c.execute(
            "select * from cards where user=? and status='added' and id not in "
            "(select card_id from card_events where action='applied') order by acted",
            (user or default_user(),)).fetchall()]


def expire(user: str | None = None, now: float | None = None) -> list[dict]:
    """Open cards untouched for EXPIRE_DAYS close quietly, so a topic never
    turns into a backlog. Returns them so the surface can mark the message."""
    user = user or default_user()
    now = now or time.time()
    cutoff = now - EXPIRE_DAYS * 86400
    stale_day = dt.date.fromtimestamp(now) - dt.timedelta(days=EXPIRE_DAYS)
    with _db() as c:
        gone = [_row(r) for r in c.execute("select * from cards where user=? and status='open' "
                                           "and sent<?", (user, cutoff)).fetchall()]
        for g in gone:
            c.execute("update cards set status='expired', acted=? where id=?", (now, g["id"]))
            _event(c, g["id"], user, "expired")
        c.execute("update cards set status='stale' where user=? and status='queued' and save_date<?",
                  (user, stale_day.isoformat()))
    return gone


def listing(user: str | None = None, tid: str | None = None, status: str | None = "open",
            limit: int = 50) -> list[dict]:
    q, args = "select * from cards where user=?", [user or default_user()]
    if tid:
        q, args = q + " and topic=?", args + [tid]
    if status:
        q, args = q + " and status=?", args + [status]
    q += " order by coalesce(sent, created) desc limit ?"
    with _db() as c:
        return [_row(r) for r in c.execute(q, args + [limit]).fetchall()]


def events(user: str | None = None, since: float = 0, actions: tuple = ()) -> list[dict]:
    q, args = ("select e.*, c.url, c.title, c.topic, c.project, c.step from card_events e "
               "join cards c on c.id=e.card_id where e.user=? and e.ts>?"), [user or default_user(), since]
    if actions:
        q += f" and e.action in ({','.join('?' * len(actions))})"
        args += list(actions)
    with _db() as c:
        return [dict(r) for r in c.execute(q + " order by e.ts", args).fetchall()]


def stats(user: str | None = None, now: float | None = None) -> dict:
    """The number that says whether this works: of the cards that have been out
    for at least 14 days, the share acted on within those 14 days; plus actions
    in the last 7 days. Working means >= 20% and >= 5 a week."""
    user = user or default_user()
    now = now or time.time()
    win = EXPIRE_DAYS * 86400
    with _db() as c:
        sent = c.execute("select status, sent, acted from cards where user=? and sent is not null",
                         (user,)).fetchall()
        week = c.execute("select count(*) from card_events where user=? and ts>? and action in "
                         "('done','remade','added')", (user, now - 7 * 86400)).fetchone()[0]
    matured = [r for r in sent if r["sent"] <= now - win]
    acted = [r for r in matured if r["status"] in DONE and r["acted"] and r["acted"] - r["sent"] <= win]
    return {"sent": len(sent), "matured": len(matured), "acted_in_14d": len(acted),
            "rate": round(len(acted) / len(matured), 3) if matured else None,
            "actions_7d": week, "open": sum(r["status"] == "open" for r in sent)}


def week_done(user: str | None = None, now: float | None = None) -> dict[str, list[dict]]:
    """What you finished in the last 7 days, per topic: the Saturday line."""
    now = now or time.time()
    out: dict[str, list[dict]] = {}
    for e in events(user, now - 7 * 86400, ("done", "remade", "added")):
        out.setdefault(e["topic"], []).append(e)
    return out


# --- Telegram topic ids ---------------------------------------------------

def thread_of(tid: str, user: str | None = None) -> int | None:
    with _db() as c:
        r = c.execute("select thread_id from topics where user=? and topic=?",
                      (user or default_user(), tid)).fetchone()
    return r["thread_id"] if r else None


def set_thread(tid: str, thread_id: int | None, user: str | None = None) -> None:
    with _db() as c:
        c.execute("insert into topics (user,topic,thread_id) values (?,?,?) on conflict(user,topic) "
                  "do update set thread_id=excluded.thread_id", (user or default_user(), tid, thread_id))


def topic_of_thread(thread_id: int, user: str | None = None) -> str | None:
    with _db() as c:
        r = c.execute("select topic from topics where user=? and thread_id=?",
                      (user or default_user(), thread_id)).fetchone()
    return r["topic"] if r else None


def kv_get(k: str) -> str | None:
    with _db() as c:
        r = c.execute("select v from card_kv where k=?", (k,)).fetchone()
    return r["v"] if r else None


def kv_set(k: str, v: str) -> None:
    with _db() as c:
        c.execute("insert into card_kv (k,v) values (?,?) on conflict(k) do update set v=excluded.v",
                  (k, v))
