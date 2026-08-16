#!/usr/bin/env python3
"""Recover the exact wording for notes that were saved without it.

    python3 backfill_verbatim.py --dry-run     # what's missing, and why
    python3 backfill_verbatim.py --limit 5     # try five
    python3 backfill_verbatim.py               # all of them

Three things went wrong at once and produced notes with no verbatim text:

1. Apify hit its monthly spend cap on 2026-08-13 and started answering 403, so
   the paid transcript stopped arriving.
2. `openai-whisper` was never installed, so the free local fallback silently
   returned nothing.
3. Nothing warned about either, because a missing transcript wasn't treated as
   a problem worth reporting.

The pipeline is fixed. This recovers what was already lost.

It deliberately does NOT re-run the reasoning agent: the notes themselves are
fine, only the verbatim section is missing. Re-acquiring costs seconds and
nothing, where a full re-process costs minutes and model usage per note. The
note is left exactly as it was apart from the appended section.
"""

import argparse
import os
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import acquire  # noqa: E402

PROJ = pathlib.Path(__file__).resolve().parent
VAULT = PROJ / "vault"
# Slides count: for a carousel the on-screen text IS the exact wording, and
# there is nothing else to recover. Leaving them out of this list made the
# first run re-fetch 20 carousels that were never missing anything.
HAS_VERBATIM = re.compile(
    r"^## (Transcript|Full article|Post text|Caption|Slides)", re.M)
SOURCE = re.compile(r"^source:\s*(\S+)", re.M)


def load_env() -> None:
    f = PROJ / ".env"
    if not f.exists():
        return
    for line in f.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def needs_backfill(text: str) -> bool:
    return not HAS_VERBATIM.search(text)


def find_targets() -> list[tuple[pathlib.Path, str]]:
    out = []
    for f in sorted(VAULT.rglob("*.md")):
        text = f.read_text()
        m = SOURCE.search(text)
        if m and needs_backfill(text):
            out.append((f, m.group(1)))
    return out


def sections_for(media: dict) -> list[str]:
    """The verbatim blocks this media can contribute, in note order."""
    blocks = []
    transcript = (media.get("transcript") or "").strip()
    caption = (media.get("caption") or "").strip()
    if transcript:
        head = "Full article" if media.get("kind") == "article" else "Transcript"
        blocks.append(f"\n## {head}\n\n{transcript}\n")
    if caption and caption != transcript:
        head = "Post text" if media.get("platform") == "twitter" else "Caption"
        blocks.append(f"\n## {head}\n\n{caption}\n")
    return blocks


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()
    load_env()

    targets = find_targets()
    if args.limit:
        targets = targets[: args.limit]
    print(f"\n{len(targets)} note(s) with no verbatim text\n")
    if args.dry_run:
        for f, url in targets:
            print(f"  {url[:70]}\n    {f.name}")
        print("\nRe-run without --dry-run to recover them.\n")
        return 0

    fixed = failed = empty = 0
    for i, (f, url) in enumerate(targets, 1):
        print(f"[{i}/{len(targets)}] {url[:66]}")
        try:
            media = acquire.acquire(url)
        except Exception as e:  # noqa: BLE001 — a dead link is expected, not fatal
            print(f"    could not re-fetch: {str(e)[:110]}")
            failed += 1
            continue
        blocks = sections_for(media)
        if not blocks:
            why = "; ".join(media.get("warnings") or []) or "nothing to recover"
            print(f"    no verbatim available — {why[:100]}")
            empty += 1
            continue
        text = f.read_text().rstrip("\n")
        f.write_text(text + "\n" + "".join(blocks))
        got = ", ".join(b.splitlines()[1].removeprefix("## ") for b in blocks)
        print(f"    recovered: {got} "
              f"({sum(len(b) for b in blocks)} chars)")
        fixed += 1
        acquire.cleanup(media)

    print(f"\n{fixed} recovered, {empty} had nothing to recover, {failed} failed to fetch\n")
    if empty or failed:
        print("Notes that stay empty are usually music-only reels with nothing "
              "spoken, or posts that no longer fetch at all (deleted, private, "
              "or removed by the platform).\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
