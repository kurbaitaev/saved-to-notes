#!/usr/bin/env python3
"""One-off: move every existing note from the old subject folders into the new
categories (folders.py, Oct 2026).

    python3 tools/recategorize.py --propose     # classify, write the proposal, change nothing
    python3 tools/recategorize.py --apply       # apply EXACTLY the proposal file

Two steps on purpose. --propose writes logs/recategorize-proposal.tsv, which is
what gets reviewed (and can be hand-edited: change the category column). --apply
never asks the model again, so what was reviewed is what happens.

--apply, per note: move vault/<old>/<file> to vault/<Category>/<file>, replace
the frontmatter `folder:`/`categories:` lines with `category:` + `area:`, and set
the Notion Category and Area columns (found by Source URL). It first adds those
two select columns to the database if they are missing. The old Folder column is
left alone. Idempotent: a note already in its target folder with the new
frontmatter is skipped.

Runs where the vault's source of truth lives (the server); the 10-minute vault
sync carries the moves to the Mac.
"""

import argparse
import csv
import json
import os
import pathlib
import re
import subprocess
import sys
import time

PROJ = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJ))

import folders  # noqa: E402
import notion  # noqa: E402
import topics  # noqa: E402

VAULT = PROJ / "vault"
PROPOSAL = PROJ / "logs" / "recategorize-proposal.tsv"
BATCH = 25
COLS = ["path", "title", "old_folder", "content_type", "category", "area", "source"]

# Notion select colours, so the board reads at a glance: knowledge in cool and
# neutral tones, real life (the app's side) in warm ones.
COLORS = {
    folders.IDEA: "yellow", folders.EXPLAINER: "blue", folders.HOW_TO: "green",
    folders.CRAFT: "pink", folders.TOOL: "gray", folders.PROMPT_BUILD: "purple",
    folders.READ_WATCH: "brown", folders.QUOTE: "default", folders.OPPORTUNITY: "red",
    folders.NEWS: "gray", folders.BUY: "orange", folders.VISIT: "orange",
    folders.ATTEND: "orange", folders.COOK: "orange", folders.MOVE: "orange",
}


def load_env() -> None:
    f = PROJ / ".env"
    if not f.exists():
        return
    for line in f.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def _front(text: str) -> dict:
    fm = re.search(r"^---\n(.*?)\n---", text, re.S)
    meta = {}
    for line in (fm.group(1).splitlines() if fm else []):
        if ":" in line:
            k, _, v = line.partition(":")
            meta[k.strip()] = v.strip()
    return meta


def read_note(p: pathlib.Path) -> dict:
    t = p.read_text()
    meta = _front(t)
    m = re.search(r"^# (.+)$", t, re.M)
    title = m.group(1).strip() if m else re.sub(
        r"^\d{4}-\d{2}-\d{2}\s*|\s*\[[0-9a-f]{6}\]$", "", p.stem).strip()
    body = re.sub(r"^---\n.*?\n---\n", "", t, flags=re.S)
    body = re.sub(r"^# .+$", "", body, flags=re.M)
    # The transcript is long and adds nothing the summary lines don't say.
    body = body.split("## Transcript")[0]
    return {
        "path": p, "title": title, "meta": meta,
        "old_folder": p.parent.name,
        "content_type": meta.get("content_type", ""),
        "topics": [t.strip() for t in meta.get("topics", "").strip("[]").split(",") if t.strip()],
        "source": meta.get("source", ""),
        "blurb": " ".join(body.split())[:600],
    }


def classify(batch: list[dict]) -> dict:
    """One category per note. Returns {index: category}."""
    listing = "\n".join(
        f'{i}. TITLE: {n["title"]}\n   SHAPE: {n["content_type"]}\n   NOTE: {n["blurb"]}'
        for i, n in enumerate(batch))
    prompt = (
        folders.RULES
        + "\n\nFile each saved note below into exactly one category.\n"
          "Reply with ONLY a JSON object mapping the number to the category name, "
          'e.g. {"0": "Idea", "1": "Read & Watch"}. No prose.\n\n' + listing)
    model = os.environ.get("CLAUDE_MODEL", "").strip()
    args = ["claude", "-p", prompt, "--max-turns", "1"]
    if model:
        args += ["--model", model]
    r = subprocess.run(args, capture_output=True, text=True, timeout=900)
    out = (r.stdout or "").strip()
    m = re.search(r"\{.*\}", out, re.S)
    if not m:
        raise RuntimeError(f"classifier returned no JSON: {out[:200] or r.stderr[:200]}")
    return {int(k): folders.normalize(v) for k, v in json.loads(m.group(0)).items()}


def all_notes() -> list[dict]:
    return [read_note(p) for p in sorted(VAULT.glob("*/*.md"))]


def _read_proposal() -> list[dict]:
    if not PROPOSAL.exists():
        return []
    with PROPOSAL.open() as f:
        return list(csv.DictReader(f, delimiter="\t"))


def propose(limit: int) -> int:
    """Classify every note not yet in the proposal. Rows are appended after each
    batch, so a run that dies (it did, on batch 13 of 13) resumes instead of
    starting over and nothing already paid for is lost."""
    done = {r["path"] for r in _read_proposal()}
    notes = [n for n in all_notes() if str(n["path"].relative_to(VAULT)) not in done]
    notes = notes[: limit or None]
    print(f"{len(done)} already proposed, {len(notes)} note(s) to classify", flush=True)
    PROPOSAL.parent.mkdir(exist_ok=True)
    new_file = not PROPOSAL.exists()
    failed = 0
    with PROPOSAL.open("a", newline="") as f:
        w = csv.DictWriter(f, COLS, delimiter="\t")
        if new_file:
            w.writeheader()
        for start in range(0, len(notes), BATCH):
            batch = notes[start:start + BATCH]
            print(f"-- {start + 1}-{start + len(batch)} …", flush=True)
            try:
                mapping = classify(batch)
            except Exception as e:  # noqa: BLE001
                # Left out rather than guessed: a missing row is visible and
                # gets retried on the next run, a silently defaulted one is not.
                print(f"   batch failed ({e}); will retry next run", flush=True)
                failed += len(batch)
                continue
            for i, n in enumerate(batch):
                if i not in mapping:
                    failed += 1
                    continue
                w.writerow({"path": str(n["path"].relative_to(VAULT)), "title": n["title"],
                            "old_folder": n["old_folder"], "content_type": n["content_type"],
                            "category": mapping[i], "area": topics.area_of(n["topics"]),
                            "source": n["source"]})
            f.flush()
    rows = _read_proposal()
    counts = {}
    for r in rows:
        counts[r["category"]] = counts.get(r["category"], 0) + 1
    print(f"\nproposed {len(rows)} in total, unclassified {failed} -> {PROPOSAL}")
    for c in folders.FOLDERS:
        print(f"  {counts.get(c, 0):>4}  {c}")
    return 1 if failed else 0


def _rewrite_front(text: str, category: str, area: str) -> str:
    head, sep, rest = text.partition("\n---\n")
    lines = [ln for ln in head.splitlines()
             if not re.match(r"(folder|categories|category|area):", ln)]
    # Keep category/area right after the type line, where folder used to be.
    at = next((i + 1 for i, ln in enumerate(lines) if ln.startswith("type:")), 1)
    lines[at:at] = [f"category: {category}", f"area: {area}"]
    return "\n".join(lines) + sep + rest


def ensure_columns(token: str, db: str) -> None:
    have = notion._db_props(token, db)
    props = {}
    if have.get("Category") != "select":
        props["Category"] = {"select": {"options": [
            {"name": c, "color": COLORS[c]} for c in folders.FOLDERS]}}
    if have.get("Area") != "select":
        props["Area"] = {"select": {"options": [{"name": a} for a in topics.AREAS]}}
    # The app's real-life screens read these two.
    if "Details" not in have:
        props["Details"] = {"rich_text": {}}
    if "Clip" not in have:
        props["Clip"] = {"files": {}}
    if props:
        notion._api(f"https://api.notion.com/v1/databases/{db}", token, "PATCH",
                    {"properties": props})
        print(f"added Notion column(s): {', '.join(props)}")


def set_notion(token: str, db: str, source: str, category: str, area: str) -> bool:
    data = notion._api(f"https://api.notion.com/v1/databases/{db}/query", token, "POST",
                       {"filter": {"property": "Source", "url": {"equals": source}},
                        "page_size": 5})
    rows = data.get("results", [])
    for row in rows:
        props = {"Category": {"select": {"name": category}}}
        props["Area"] = {"select": {"name": area}} if area else {"select": None}
        notion._api(f"https://api.notion.com/v1/pages/{row['id']}", token, "PATCH",
                    {"properties": props})
        time.sleep(0.35)  # Notion allows ~3 requests/second
    return bool(rows)


def apply() -> int:
    rows = _read_proposal()
    if not rows:
        print("no proposal yet — run --propose first")
        return 1
    token = os.environ.get("NOTION_TOKEN", "").strip()
    db = os.environ.get("NOTION_DATABASE_ID", "").strip()
    if token and db:
        ensure_columns(token, db)
    moved = skipped = notion_ok = notion_miss = 0
    for r in rows:
        category = folders.normalize(r["category"])
        src = VAULT / r["path"]
        dest = VAULT / folders.safe_dirname(category) / src.name
        if not src.exists():
            if dest.exists():
                src = dest  # already moved by an earlier run
            else:
                print(f"   missing: {r['path']}")
                continue
        text = src.read_text()
        new = _rewrite_front(text, category, r["area"])
        if src == dest and new == text:
            skipped += 1
        else:
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(new)
            if src != dest:
                src.unlink()
            moved += 1
        if token and db and r["source"]:
            try:
                if set_notion(token, db, r["source"], category, r["area"]):
                    notion_ok += 1
                else:
                    notion_miss += 1
            except Exception as e:  # noqa: BLE001
                notion_miss += 1
                print(f"   notion failed for {r['source'][:60]}: {e}")
    for d in VAULT.iterdir():
        if d.is_dir() and not d.name.startswith(".") and not any(d.iterdir()):
            d.rmdir()
            print(f"removed empty folder: {d.name}")
    print(f"\nvault: {moved} moved/updated, {skipped} already done; "
          f"notion: {notion_ok} set, {notion_miss} not found or failed")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--propose", action="store_true")
    g.add_argument("--apply", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()
    load_env()
    return propose(args.limit) if args.propose else apply()


if __name__ == "__main__":
    sys.exit(main())
