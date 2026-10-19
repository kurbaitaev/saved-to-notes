#!/usr/bin/env python3
"""How full is each column of the Bookmarks database? And optionally remove
columns — only ones that are empty on every row unless --force is given.

    python3 tools/notion_columns.py                       # report
    python3 tools/notion_columns.py --drop Stage Progress # remove (if empty)
"""

import argparse
import os
import pathlib
import sys

PROJ = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJ))
sys.path.insert(0, str(PROJ / "tools"))

from recategorize import load_env  # noqa: E402

import notion  # noqa: E402


def _filled(p: dict) -> bool:
    t = p.get("type")
    v = p.get(t)
    if t in ("title", "rich_text", "multi_select", "files", "relation", "people"):
        return bool(v)
    if t in ("select", "status", "date", "url", "number", "email", "phone_number"):
        return v is not None
    if t == "checkbox":
        return bool(v)
    return False  # formulas, rollups, created_time … are computed, not data


def rows(token: str, db: str) -> list[dict]:
    out, cursor = [], None
    while True:
        body = {"page_size": 100, **({"start_cursor": cursor} if cursor else {})}
        d = notion._api(f"https://api.notion.com/v1/databases/{db}/query", token, "POST", body)
        out += d["results"]
        if not d.get("has_more"):
            return out
        cursor = d["next_cursor"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--drop", nargs="*", default=[])
    ap.add_argument("--force", action="store_true", help="drop even columns that hold data")
    args = ap.parse_args()
    load_env()
    token, db = os.environ["NOTION_TOKEN"], os.environ["NOTION_DATABASE_ID"]
    schema = notion._api(f"https://api.notion.com/v1/databases/{db}", token)["properties"]
    all_rows = rows(token, db)
    counts = {name: sum(_filled(r["properties"].get(name, {})) for r in all_rows) for name in schema}
    print(f"{len(all_rows)} rows")
    for name, n in sorted(counts.items(), key=lambda kv: kv[1]):
        print(f"  {n:>4}  {name:<22} {schema[name]['type']}")
    if args.drop:
        gone = {}
        for name in args.drop:
            if name not in schema:
                print(f"skip {name}: no such column")
            elif counts[name] and not args.force:
                print(f"skip {name}: holds data on {counts[name]} row(s) (use --force)")
            else:
                gone[name] = None
        if gone:
            notion._api(f"https://api.notion.com/v1/databases/{db}", token, "PATCH", {"properties": gone})
            print("removed:", ", ".join(gone))
    return 0


if __name__ == "__main__":
    sys.exit(main())
