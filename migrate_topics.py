#!/usr/bin/env python3
"""One-off migration: Motivation → Mindset, and add topics to every note.

    python3 migrate_topics.py --dry-run    # show what would change
    python3 migrate_topics.py              # apply

Two jobs, because they touch the same rows and must not be done in two passes:

1. The folder was renamed to Mindset (the name already in use in Notion — the
   code was still writing "Motivation", so Notion ended up with both).
2. Notes written before topics existed get them derived from the free-form tags
   they already carry. No model call is needed: the tags ARE the raw material
   the vocabulary was built from.

Idempotent — notes that already carry `topics:` are skipped, so it can be
re-run safely after new notes arrive.
"""

import argparse
import collections
import os
import pathlib
import re
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import folders  # noqa: E402
import notion  # noqa: E402
import topics  # noqa: E402

PROJ = pathlib.Path(__file__).resolve().parent
VAULT = PROJ / "vault"
OLD_FOLDER, NEW_FOLDER = "Motivation", folders.MINDSET


def load_env() -> None:
    f = PROJ / ".env"
    if not f.exists():
        return
    for line in f.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def rename_folder(dry: bool) -> int:
    old, new = VAULT / OLD_FOLDER, VAULT / NEW_FOLDER
    if not old.is_dir():
        print(f"  vault/{OLD_FOLDER} — already renamed")
        return 0
    notes = list(old.glob("*.md"))
    if dry:
        print(f"  would move {len(notes)} note(s) → vault/{NEW_FOLDER}")
        return len(notes)
    new.mkdir(parents=True, exist_ok=True)
    for f in notes:
        f.rename(new / f.name)
    if not any(old.iterdir()):
        old.rmdir()
    print(f"  moved {len(notes)} note(s) → vault/{NEW_FOLDER}")
    return len(notes)


def note_topics(text: str) -> list[str]:
    """Derive topics from the tags and the folder already recorded in the note."""
    tags = re.findall(r"#([a-zA-Z0-9_-]{3,30})", text)
    found = topics.from_tags(tags)
    if found:
        return found
    # No usable tags — fall back to the folder, which is at least true.
    fallback = {
        folders.CONTENT_IDEAS: ["content-creation"],
        folders.MINDSET: ["mindset"],
        folders.STARTUP: ["startup-building"],
        folders.TOOLS_AI: ["ai-tools"],
        folders.LEARNING: ["learning-education"],
    }
    m = re.search(r"^folder:\s*(.+)$", text, re.M)
    return fallback.get(folders.normalize(m.group(1) if m else ""), [])


def backfill_vault(dry: bool) -> collections.Counter:
    counts: collections.Counter = collections.Counter()
    for folder_dir in sorted(p for p in VAULT.iterdir() if p.is_dir()):
        folder = folders.normalize(folder_dir.name)
        for f in sorted(folder_dir.glob("*.md")):
            text = f.read_text()
            if re.search(r"^topics:", text, re.M):
                counts["already done"] += 1
                continue
            found = note_topics(text)
            counts.update(found or ["(none derived)"])
            if dry:
                continue
            line = f"topics: [{', '.join(found)}]"
            if re.search(r"^folder:", text, re.M):
                text = re.sub(r"^folder:.*$", f"folder: {folder}\n{line}", text, count=1, flags=re.M)
            else:
                text = text.replace("---\n", f"---\nfolder: {folder}\n{line}\n", 1)
            f.write_text(text)
    return counts


def ensure_notion_property(dry: bool) -> bool:
    token = os.environ.get("NOTION_TOKEN", "").strip()
    db = os.environ.get("NOTION_DATABASE_ID", "").strip()
    if not (token and db):
        print("  Notion not configured — skipping")
        return False
    if "Topics" in notion._db_props(token, db):
        print("  Topics property already exists")
        return True
    if dry:
        print("  would create the Topics multi-select property")
        return True
    notion._api(f"https://api.notion.com/v1/databases/{db}", token, "PATCH",
                {"properties": {"Topics": {"multi_select": {
                    "options": [{"name": t} for t in topics.TOPICS]}}}})
    notion._db_props.cache_clear() if hasattr(notion._db_props, "cache_clear") else None
    print(f"  created Topics with {len(topics.TOPICS)} options")
    return True


def push_to_notion(dry: bool) -> tuple[int, int]:
    """Set Folder + Topics on every Notion row, matched by its vault note."""
    token = os.environ.get("NOTION_TOKEN", "").strip()
    db = os.environ.get("NOTION_DATABASE_ID", "").strip()
    if not (token and db):
        return 0, 0
    updated = missing = 0
    for f in sorted(VAULT.rglob("*.md")):
        text = f.read_text()
        src = re.search(r"^source:\s*(\S+)", text, re.M)
        if not src:
            continue
        tps = re.search(r"^topics:\s*\[(.*)\]", text, re.M)
        tps = topics.normalize_list([x.strip() for x in (tps.group(1) if tps else "").split(",")])
        folder = folders.normalize(f.parent.name)
        if dry:
            updated += 1
            continue
        try:
            d = notion._api(f"https://api.notion.com/v1/databases/{db}/query", token, "POST",
                            {"filter": {"property": "Source", "url": {"equals": src.group(1)}},
                             "page_size": 1})
            rows = d.get("results", [])
            if not rows:
                missing += 1
                continue
            props = {"Folder": {"select": {"name": folder}}}
            if tps:
                props["Topics"] = {"multi_select": [{"name": t} for t in tps]}
            notion._api(f"https://api.notion.com/v1/pages/{rows[0]['id']}", token, "PATCH",
                        {"properties": props})
            updated += 1
            time.sleep(0.34)  # Notion allows ~3 requests/second
        except Exception as e:  # noqa: BLE001
            print(f"    failed for {src.group(1)[:60]}: {e}")
            missing += 1
    return updated, missing


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    load_env()
    dry = args.dry_run
    print(f"\n{'DRY RUN — nothing will change' if dry else 'APPLYING'}\n")

    print(f"1. Folder rename {OLD_FOLDER} → {NEW_FOLDER}")
    rename_folder(dry)

    print("\n2. Topics in the vault")
    counts = backfill_vault(dry)
    for topic, n in counts.most_common():
        print(f"   {n:>4}  {topic}")

    print("\n3. Notion")
    if ensure_notion_property(dry):
        updated, missing = push_to_notion(dry)
        print(f"   {updated} row(s) updated" + (f", {missing} with no match" if missing else ""))

    print("\nDone." + ("  Re-run without --dry-run to apply.\n" if dry else "\n"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
