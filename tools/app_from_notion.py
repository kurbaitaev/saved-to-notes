#!/usr/bin/env python3
"""One-off: fill the Afterscroll app store (appdb) from the real-life saves that
were made while the app still read Notion, and cut their clips.

    python3 tools/app_from_notion.py            # all real-life saves
    python3 tools/app_from_notion.py --no-clips # store only, skip video work

Safe to re-run: saves are upserted by URL and a workout's clips are rebuilt.
"""

import argparse
import json
import os
import pathlib
import sys

PROJ = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJ))
sys.path.insert(0, str(PROJ / "tools"))

from recategorize import load_env  # noqa: E402

import appdb  # noqa: E402
import clips  # noqa: E402
import folders  # noqa: E402
import notion  # noqa: E402


def _text(prop: dict | None, key: str = "rich_text") -> str:
    return "".join(x.get("plain_text", "") for x in (prop or {}).get(key, []) or [])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-clips", action="store_true")
    args = ap.parse_args()
    load_env()
    token, db = os.environ["NOTION_TOKEN"], os.environ["NOTION_DATABASE_ID"]
    rows = notion._api(f"https://api.notion.com/v1/databases/{db}/query", token, "POST", {
        "page_size": 100,
        "filter": {"or": [{"property": "Category", "select": {"equals": c}} for c in folders.REAL_LIFE]},
    })["results"]
    for pg in rows:
        pr = pg["properties"]
        cat = pr["Category"]["select"]["name"]
        url = (pr.get("Source") or {}).get("url") or ""
        if not url:
            continue
        title = _text(pr.get("Name"), "title")
        sid = appdb.upsert(
            url, cat, title, _text(pr.get("Author")),
            _text(pr.get("Hook / key idea")) or _text(pr.get("Summary")),
            json.loads(_text(pr.get("Details")) or "{}"),
            ((pr.get("Date") or {}).get("date") or {}).get("start", ""))
        line = f"{cat:<6} {sid} {title[:44]}"
        if cat == folders.MOVE and not args.no_clips:
            try:
                made = clips.make_for_save(url, sid)
                appdb.set_clips(sid, made)
                line += " | " + "; ".join(f"{c['name']} {c['start']}-{c['end']}s" for c in made[1:])
            except Exception as e:  # noqa: BLE001
                line += f" | clips failed: {e}"
        print(line, flush=True)
    print(f"{len(appdb.all_saves())} save(s) in the app store")
    return 0


if __name__ == "__main__":
    sys.exit(main())
