#!/usr/bin/env python3
"""Write one review question per note into Notion.

    python3 review_questions.py --limit 6      # backfill a few
    python3 review_questions.py --limit 6 --dry-run

Why the tool writes the question instead of the reader: people who write their
own quiz questions get no benefit from answering them, and tend to do *worse*
than if they had just reread — they aim at the wrong material (Myers, Hausman &
Rhodes 2024, J. Exp. Psych: Applied 30(2)). So the question has to come from
something that has read the whole note.

The questions are deliberately higher-order ("why would X change Y") rather than
factual recall, because factual questions only buy back the fact, while
higher-order ones generalise to related material (Hamaker 1986).
"""

import argparse
import json
import os
import pathlib
import subprocess
import sys
import time
import urllib.request

PROJ = pathlib.Path(__file__).resolve().parent
PROP = "Review question"
BATCH = 6          # notes per agent call — one call for many is far cheaper
AGENT_TIMEOUT = 300


def load_env():
    f = PROJ / ".env"
    if f.exists():
        for line in f.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def api(url, method="GET", body=None):
    req = urllib.request.Request(
        url, method=method,
        data=json.dumps(body).encode() if body else None,
        headers={"Authorization": f"Bearer {os.environ['NOTION_TOKEN']}",
                 "Notion-Version": "2022-06-28",
                 "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def ensure_property(dry):
    db = os.environ["NOTION_DATABASE_ID"]
    props = api(f"https://api.notion.com/v1/databases/{db}")["properties"]
    if PROP in props:
        print(f"  '{PROP}' already exists")
        return
    if dry:
        print(f"  would create '{PROP}' (rich_text)")
        return
    api(f"https://api.notion.com/v1/databases/{db}", "PATCH",
        {"properties": {PROP: {"rich_text": {}}}})
    print(f"  created '{PROP}'")


def text(prop, key="rich_text"):
    return "".join(t.get("plain_text", "") for t in (prop or {}).get(key, [])).strip()


def rows_needing_questions(limit):
    db = os.environ["NOTION_DATABASE_ID"]
    out, cursor = [], None
    while len(out) < limit:
        # Oldest first: those are the notes actually past the 7-day delay, so
        # backfilling them is what makes a review available today.
        body = {"page_size": 100,
                "sorts": [{"property": "Date", "direction": "ascending"}]}
        if cursor:
            body["start_cursor"] = cursor
        d = api(f"https://api.notion.com/v1/databases/{db}/query", "POST", body)
        for r in d.get("results", []):
            p = r["properties"]
            if text(p.get(PROP)):
                continue
            title = text(p.get("Name"), "title")
            hook = text(p.get("Hook / key idea"))
            summary = text(p.get("Summary"))
            if not title or not (hook or summary):
                continue          # nothing to build a real question from
            out.append({"id": r["id"], "title": title,
                        "hook": hook, "summary": summary})
            if len(out) >= limit:
                break
        if not d.get("has_more"):
            break
        cursor = d.get("next_cursor")
    return out


PROMPT = """For each saved note below, write ONE question the person should be able to
answer from memory weeks later.

Rules:
- Higher-order, not factual recall. Ask why something works, when it would fail,
  or how it changes a decision — not "what did the post say".
- Answerable from the note's own content. Never require outside knowledge.
- One sentence, under 25 words, ending in a question mark.
- Address the reader as "you".

Return ONLY a JSON array, one object per note, in the same order:
[{"id": "<the id given>", "question": "..."}]

NOTES:
%s"""


def ask_agent(batch):
    blob = "\n\n".join(
        f'id: {n["id"]}\ntitle: {n["title"]}\nkey idea: {n["hook"] or n["summary"]}'
        for n in batch)
    proc = subprocess.run(
        ["claude", "-p", PROMPT % blob],
        capture_output=True, text=True, timeout=AGENT_TIMEOUT, cwd=PROJ)
    raw = proc.stdout.strip()
    start, end = raw.find("["), raw.rfind("]")
    if start < 0 or end < 0:
        raise RuntimeError(f"agent returned no JSON array: {raw[:300]}")
    return json.loads(raw[start:end + 1])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=6)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    load_env()
    if not (os.environ.get("NOTION_TOKEN") and os.environ.get("NOTION_DATABASE_ID")):
        print("Notion is not configured in .env")
        return 1

    print(f"\n{'DRY RUN' if args.dry_run else 'APPLYING'}\n")
    print("1. Notion property")
    ensure_property(args.dry_run)

    print("\n2. Notes without a question")
    todo = rows_needing_questions(args.limit)
    print(f"   {len(todo)} to do")
    if not todo:
        return 0

    print("\n3. Writing questions")
    written = 0
    for i in range(0, len(todo), BATCH):
        batch = todo[i:i + BATCH]
        try:
            answers = ask_agent(batch)
        except Exception as e:                      # noqa: BLE001
            print(f"   batch failed: {e}")
            continue
        by_id = {a.get("id"): a.get("question", "") for a in answers if isinstance(a, dict)}
        for n in batch:
            q = (by_id.get(n["id"]) or "").strip()
            if not q.endswith("?"):
                print(f"   skipped (no usable question): {n['title'][:50]}")
                continue
            print(f"   {n['title'][:44]:46} {q[:70]}")
            if args.dry_run:
                continue
            api(f"https://api.notion.com/v1/pages/{n['id']}", "PATCH",
                {"properties": {PROP: {"rich_text": [{"text": {"content": q[:1900]}}]}}})
            written += 1
            time.sleep(0.34)                        # Notion allows ~3 req/sec

    print(f"\n{written} question(s) written.\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
