#!/usr/bin/env python3
"""Weekly digest — the loop-closer.

    python3 digest.py            # send to Telegram
    python3 digest.py --dry-run  # print instead

Three things, once a week, Sunday evening:

1. What you saved this week.
2. How your review went — how many cards, how many you actually recalled.
3. One note you saved long ago and have never once been asked about, with its
   question. Bergman 2021: only 16% of bookmarks are ever retrieved, and the
   folder hierarchy accounts for 4%. Nothing comes back on its own; something
   has to bring it.

Every run also appends a snapshot to logs/adherence.jsonl. No read-later tool
has ever published a retention or adherence number — the biggest spaced-
repetition dataset in existence excludes everyone who quit. This file is the
start of the number nobody has.
"""

import argparse
import datetime as dt
import html
import json
import os
import pathlib
import re
import sys
import urllib.parse
import urllib.request

PROJ = pathlib.Path(__file__).resolve().parent
VAULT = PROJ / "vault"
ADHERENCE = PROJ / "logs" / "adherence.jsonl"
NOTION = "https://api.notion.com/v1"


def load_env() -> None:
    f = PROJ / ".env"
    if not f.exists():
        return
    for line in f.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


# --- data --------------------------------------------------------------------

def saved_this_week(today: dt.date, days: int = 7) -> list[dict]:
    """Vault notes dated inside the window, newest first."""
    since = (today - dt.timedelta(days=days)).isoformat()
    out = []
    for f in VAULT.rglob("*.md"):
        t = f.read_text()
        d = re.search(r"^date:\s*(\d{4}-\d{2}-\d{2})", t, re.M)
        if not d or d.group(1) < since:
            continue
        title = re.search(r"^# (.+)$", t, re.M)
        out.append({"date": d.group(1), "title": (title.group(1) if title else f.stem),
                    "folder": f.parent.name})
    return sorted(out, key=lambda r: r["date"], reverse=True)


def _notion(path: str, body: dict | None = None) -> dict:
    req = urllib.request.Request(
        NOTION + path, method="POST" if body is not None else "GET",
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Authorization": f"Bearer {os.environ['NOTION_TOKEN']}",
                 "Notion-Version": "2022-06-28", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def _text(prop, key="rich_text") -> str:
    return "".join(t.get("plain_text", "") for t in (prop or {}).get(key, [])).strip()


def notion_rows() -> list[dict]:
    """Every row, reduced to what the digest needs. [] when Notion is off."""
    db = os.environ.get("NOTION_DATABASE_ID", "").strip()
    if not (db and os.environ.get("NOTION_TOKEN", "").strip()):
        return []
    rows, cursor = [], None
    while True:
        body = {"page_size": 100, "sorts": [{"property": "Date", "direction": "ascending"}]}
        if cursor:
            body["start_cursor"] = cursor
        d = _notion(f"/databases/{db}/query", body)
        for r in d.get("results", []):
            p = r["properties"]
            rows.append({
                "title": _text(p.get("Name"), "title"),
                "url": (p.get("Source") or {}).get("url") or "",
                "date": ((p.get("Date") or {}).get("date") or {}).get("start") or "",
                "question": _text(p.get("Review question")),
                "reviews": (p.get("Reviews") or {}).get("number") or 0,
                "recalled": (p.get("Recalled") or {}).get("number") or 0,
                "last_reviewed": ((p.get("Last reviewed") or {}).get("date") or {}).get("start") or "",
                "last_result": ((p.get("Last result") or {}).get("select") or {}).get("name") or "",
            })
        if not d.get("has_more"):
            break
        cursor = d["next_cursor"]
    return rows


# --- pure pieces (tested) ----------------------------------------------------

def reviewed_in_window(rows: list[dict], today: dt.date, days: int = 7) -> list[dict]:
    since = (today - dt.timedelta(days=days)).isoformat()
    return [r for r in rows if r.get("last_reviewed", "")[:10] >= since and r.get("reviews", 0)]


def recall_rate(rows: list[dict]) -> tuple[int, int]:
    """(recalled, total) across the given rows' most recent answers."""
    total = len(rows)
    recalled = sum(1 for r in rows if r.get("last_result") == "recalled")
    return recalled, total


def oldest_unasked(rows: list[dict]) -> dict | None:
    """The note that has waited longest without ever being reviewed — and can
    be, i.e. carries a question. Rows arrive date-ascending from Notion."""
    for r in rows:
        if r.get("question") and not r.get("reviews"):
            return r
    return None


def lifetime(rows: list[dict]) -> tuple[int, int]:
    return (sum(r.get("recalled", 0) for r in rows), sum(r.get("reviews", 0) for r in rows))


def render(today: dt.date, saved: list[dict], week: list[dict], rows: list[dict]) -> str:
    esc = html.escape
    L = [f"<b>Your week</b> · {today.strftime('%-d %b')}", ""]

    if saved:
        by = {}
        for s in saved:
            by.setdefault(s["folder"], []).append(s["title"])
        L.append(f"📥 <b>Saved {len(saved)}</b>")
        for folder, titles in sorted(by.items(), key=lambda kv: -len(kv[1])):
            shown = ", ".join(esc(t) for t in titles[:3]) + (f" +{len(titles)-3}" if len(titles) > 3 else "")
            L.append(f"  {esc(folder)} ({len(titles)}): {shown}")
    else:
        L.append("📥 Nothing saved this week.")
    L.append("")

    rec, tot = recall_rate(week)
    if tot:
        L.append(f"🧠 <b>Reviewed {tot}</b> — recalled {rec} ({rec * 100 // tot}%)")
    else:
        L.append("🧠 No reviews this week. One card a day is the whole habit.")
    lr, lt = lifetime(rows)
    if lt:
        L.append(f"  all time: {lr}/{lt} recalled ({lr * 100 // lt}%)")
    L.append("")

    old = oldest_unasked(rows)
    if old:
        try:
            age = (today - dt.date.fromisoformat(old["date"][:10])).days
            when = f"{age} days ago"
        except ValueError:
            when = "a while ago"
        L.append(f"⏳ <b>Never asked about, saved {when}:</b>")
        L.append(f"<b>{esc(old['title'])}</b>")
        L.append(f"<i>{esc(old['question'])}</i>")
        if old.get("url"):
            L.append(f'<a href="{esc(old["url"])}">original</a>')
    return "\n".join(L)


# --- send ----------------------------------------------------------------------

def send(text: str) -> None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat = os.environ.get("ALLOWED_USER_IDS", "").split(",")[0].strip()
    if not (token and chat):
        sys.exit("TELEGRAM_BOT_TOKEN / ALLOWED_USER_IDS missing")
    data = urllib.parse.urlencode({"chat_id": chat, "text": text, "parse_mode": "HTML",
                                   "disable_web_page_preview": "true"}).encode()
    with urllib.request.urlopen(
            urllib.request.Request(f"https://api.telegram.org/bot{token}/sendMessage", data=data),
            timeout=20) as r:
        if not json.load(r).get("ok"):
            sys.exit("Telegram refused the digest")


def log_snapshot(today: dt.date, saved: list[dict], week: list[dict], rows: list[dict]) -> None:
    rec, tot = recall_rate(week)
    lr, lt = lifetime(rows)
    ADHERENCE.parent.mkdir(exist_ok=True)
    with ADHERENCE.open("a") as f:
        f.write(json.dumps({
            "week_ending": today.isoformat(), "saved": len(saved),
            "reviewed": tot, "recalled": rec,
            "lifetime_reviews": lt, "lifetime_recalled": lr,
            "notes_total": len(rows),
            "notes_with_question": sum(1 for r in rows if r.get("question")),
            "notes_never_reviewed": sum(1 for r in rows if r.get("question") and not r.get("reviews")),
        }) + "\n")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    load_env()
    today = dt.date.today()
    saved = saved_this_week(today)
    rows = notion_rows()
    week = reviewed_in_window(rows, today)
    text = render(today, saved, week, rows)
    if args.dry_run:
        print(text)
        return 0
    send(text)
    log_snapshot(today, saved, week, rows)
    print(f"sent: {len(saved)} saved, {len(week)} reviewed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
