#!/usr/bin/env python3
"""Audit every workout's clips — run after changing how moves are detected.

    python3 tools/eval_cuts.py

Per workout: shots in the source video vs clips made, clips that cross a cut
(must be 0), clips with no cue, duplicate names next to each other, and the
move list vs the clips (must match). Exits 1 if any hard check fails.
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
    bad = 0
    for s in appdb.all_saves():
        if s["category"] != folders.MOVE:
            continue
        files = sorted((appdb.CLIPS / s["id"]).glob("move*.mp4"),
                       key=lambda p: int(p.stem.removeprefix("move")))
        crossing = [p.stem for p in files if clips.check_clip(p) is not None]
        names = [m["name"] for m in s["moves"]]
        listed = [m.get("name") for m in s["details"].get("moves") or []]
        no_cue = sum(1 for m in s["details"].get("moves") or [] if not m.get("cues"))
        repeats = sum(1 for a, b in zip(names, names[1:], strict=False) if a.lower() == b.lower())
        mismatch = listed != names
        hard = bool(crossing) or mismatch or len(files) != len(names)
        bad += hard
        print(f"{'FAIL' if hard else 'ok  '} {s['title'][:40]:<40} clips {len(files):>2} "
              f"| crossing {crossing or 0} | list==clips {not mismatch} "
              f"| no cue {no_cue} | adjacent repeats {repeats}")
    print(f"\n{bad} workout(s) failed a hard check")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
