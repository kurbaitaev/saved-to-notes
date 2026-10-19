#!/usr/bin/env python3
"""Where a video cuts from one shot to the next — exact and free (ffmpeg).

Shared by acquire.py (one frame per shot for the note-writer) and clips.py
(one clip per exercise). Workout reels are edited as one shot per exercise;
treating the cuts as ground truth is what made the exercise clips reliable:

- the note-writer used to see 8 evenly spaced frames of a 22 s reel with 12
  exercises and listed 8 of them;
- Gemini, asked for timestamps, put 2-3 exercises into one clip.
"""

import re
import subprocess

SCENE = 0.2        # scene-change score that counts as a cut. 0.3 missed a soft cut on
                   # an igor.system reel; 0.1-0.2 found the same set on every test reel.
MIN_SHOT = 0.8     # shorter "shots" are flashes or transitions, merged into a neighbour


def duration(path) -> float:
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                        "-of", "csv=p=0", str(path)], capture_output=True, text=True, timeout=30)
    try:
        return float(r.stdout.strip())
    except ValueError:
        return 0.0


def cuts(path, threshold: float = SCENE) -> list[float]:
    r = subprocess.run(["ffmpeg", "-nostdin", "-hide_banner", "-i", str(path), "-an",
                        "-vf", f"select='gt(scene,{threshold})',showinfo", "-f", "null", "-"],
                       capture_output=True, text=True, timeout=300)
    return [float(x) for x in re.findall(r"pts_time:([0-9.]+)", r.stderr)]


def shots(path) -> list[tuple[float, float]]:
    """[(start, end)] of each shot; flashes shorter than MIN_SHOT are merged."""
    total = duration(path)
    if total <= 0:
        return []
    edges = [0.0] + [c for c in cuts(path) if 0 < c < total] + [total]
    merged: list[list[float]] = []
    for a, b in zip(edges, edges[1:], strict=False):
        if b <= a:
            continue
        if merged and (b - a < MIN_SHOT or merged[-1][1] - merged[-1][0] < MIN_SHOT):
            merged[-1][1] = b
        else:
            merged.append([a, b])
    return [(round(a, 2), round(b, 2)) for a, b in merged]
