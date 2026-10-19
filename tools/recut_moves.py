#!/usr/bin/env python3
"""Re-cut every workout in the app store (or the ones whose title matches).

    python3 tools/recut_moves.py              # all Move saves
    python3 tools/recut_moves.py "hip"        # only titles containing "hip"

Uses the note's own move list as hints for Gemini (clips.find_moves), so the
cuts and the note name the same exercises. Each re-cut bumps the clip version,
so phones fetch the new videos instead of showing cached old ones.
"""

import pathlib
import sys

PROJ = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJ))
sys.path.insert(0, str(PROJ / "tools"))

from recategorize import load_env  # noqa: E402

import appdb  # noqa: E402
import clips  # noqa: E402
import folders  # noqa: E402


def main() -> int:
    load_env()
    # Show clips.py's warnings (failed calls, fallbacks) instead of a silent "cut 0".
    import logging
    logging.basicConfig(level=logging.WARNING, format="  %(levelname)s %(message)s")
    needle = (sys.argv[1] if len(sys.argv) > 1 else "").lower()
    for s in appdb.all_saves():
        if s["category"] != folders.MOVE or needle not in s["title"].lower():
            continue
        # Hints come from the ORIGINAL note list when we still have it; after a
        # first re-cut the list is the clips' own names, which is fine too.
        hints = [str(m.get("name")) for m in s["details"].get("moves") or [] if m.get("name")]
        try:
            made = clips.make_for_save(s["url"], s["id"], hints=hints)
            appdb.set_clips(s["id"], made)
            if len(made) > 1:
                appdb.set_moves(s["id"], clips.as_detail_moves(made, s["details"].get("moves")))
            print(f"{s['title'][:44]:<44} noted {len(hints):>2} -> cut {len(made) - 1:>2}: "
                  + ", ".join(c["name"] for c in made[1:]), flush=True)
        except Exception as e:  # noqa: BLE001
            print(f"{s['title'][:44]:<44} failed: {e}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
