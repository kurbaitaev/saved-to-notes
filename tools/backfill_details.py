#!/usr/bin/env python3
"""One-off: give real-life saves made before details.py existed their Details
(and, for workouts, their looping Clip), so they work in the Afterscroll app.

    python3 tools/backfill_details.py --dry-run
    python3 tools/backfill_details.py

Finds Notion pages whose Category is a real-life one and whose Details or Clip
is empty, reads the matching vault note (it holds the verbatim transcript), asks
the model for the details object, validates it with details.clean, and writes
it. Idempotent: pages that already have both are skipped.
"""

import argparse
import json
import os
import pathlib
import re
import subprocess
import sys

PROJ = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJ))
sys.path.insert(0, str(PROJ / "tools"))

from recategorize import load_env  # noqa: E402

import clips  # noqa: E402
import details  # noqa: E402
import folders  # noqa: E402
import notion  # noqa: E402

VAULT = PROJ / "vault"


def pages(token: str, db: str) -> list[dict]:
    out, cursor = [], None
    while True:
        body = {"page_size": 100, "filter": {"or": [
            {"property": "Category", "select": {"equals": c}} for c in folders.REAL_LIFE]}}
        if cursor:
            body["start_cursor"] = cursor
        d = notion._api(f"https://api.notion.com/v1/databases/{db}/query", token, "POST", body)
        out += d.get("results", [])
        if not d.get("has_more"):
            return out
        cursor = d.get("next_cursor")


def note_text(source: str) -> str:
    for p in VAULT.glob("*/*.md"):
        t = p.read_text()
        if re.search(rf"^source: {re.escape(source)}\s*$", t, re.M):
            return t[:14000]
    return ""


def extract(category: str, text: str) -> dict:
    prompt = (details.RULES + f"\n\nThis saved note's category is **{category}**. Fill the "
              "details object for it from the note below. Reply with ONLY the JSON object.\n\n"
              + text)
    args = ["claude", "-p", prompt, "--max-turns", "1"]
    if os.environ.get("CLAUDE_MODEL", "").strip():
        args += ["--model", os.environ["CLAUDE_MODEL"].strip()]
    r = subprocess.run(args, capture_output=True, text=True, timeout=600)
    m = re.search(r"\{.*\}", r.stdout or "", re.S)
    if not m:
        raise RuntimeError(f"no JSON: {(r.stdout or r.stderr)[:200]}")
    return details.clean(category, json.loads(m.group(0)))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    load_env()
    token, db = os.environ["NOTION_TOKEN"], os.environ["NOTION_DATABASE_ID"]
    for pg in pages(token, db):
        props = pg["properties"]
        cat = (props["Category"].get("select") or {}).get("name", "")
        title = "".join(t["plain_text"] for t in props["Name"]["title"])
        source = props.get("Source", {}).get("url") or ""
        has_details = bool(props.get("Details", {}).get("rich_text"))
        has_clip = bool(props.get("Clip", {}).get("files"))
        line = f"{cat:<7} {title[:50]:<50}"
        if not has_details:
            text = note_text(source)
            if not text:
                print(line, "no vault note found")
                continue
            try:
                d = extract(cat, text)
            except Exception as e:  # noqa: BLE001
                print(line, f"extract failed: {e}")
                continue
            line += " details " + details.to_json(d)[:90]
            if not args.dry_run and d:
                notion._api(f"https://api.notion.com/v1/pages/{pg['id']}", token, "PATCH",
                            {"properties": {"Details": {"rich_text": [
                                {"text": {"content": details.to_json(d)}}]}}})
        if cat == folders.MOVE and not has_clip and source:
            if args.dry_run:
                line += " · would make clip"
            else:
                try:
                    line += " · " + clips.clip_for_page(source, pg["id"])
                except Exception as e:  # noqa: BLE001
                    line += f" · clip failed: {e}"
        print(line, flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
