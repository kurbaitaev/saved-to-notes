#!/usr/bin/env python3
"""Looping clips for workout saves (category Move) — the Afterscroll Move screen.

A Move save gets:
- a whole-reel loop (silent, 480 px), the tile on the Move grid, and
- one short loop PER EXERCISE, so the routine player shows only the move being
  done and the By creator screen can lay a creator's moves out as a collage.

The transcript has no timestamps, so the cut points come from Gemini watching
the video (tested on the Hip Mobility reel: it found all 6 stretches where the
text-only notes listed 4, every cut on the right move). Without a Gemini key, or
if it answers nonsense, the save keeps just the whole loop — never a wrong cut.

Files land in appdb.CLIPS/<save id>/ and are served by api.py. The reel is
fetched again with yt-dlp because the acquire step deletes the video once it
has a transcript. Everything here is best-effort: a missing clip never fails
the save.
"""

import base64
import json
import logging
import os
import pathlib
import re
import shutil
import subprocess
import urllib.request
import uuid

import appdb

log = logging.getLogger("saved-to-notes")

TMP = pathlib.Path("/tmp/saved-to-notes/clips")
MAX_SECONDS = 45          # longer reels are trimmed for the whole-reel loop
GEMINI_MODEL = "gemini-2.5-flash"
_PROMPT = (
    "This is an exercise video. List every distinct exercise or stretch that is "
    "DEMONSTRATED on screen, in order. For each, give the time range in seconds "
    "(one decimal) of the cleanest 2-5 seconds of clear demonstration — skip intro "
    "talk and transitions. One exercise is ONE entry: both sides, several reps or a "
    "second camera angle of the same move are not new exercises. Reply with ONLY JSON: "
    '[{"name": "...", "start": 0.0, "end": 0.0}]')

# The note-writer and Gemini used to read each reel separately and disagreed:
# 5 noted moves vs 2 cuts on one reel, 8 vs 15 on another, so moves went
# missing and doses never attached. Giving Gemini the note's list makes both
# describe the same moves with the same names.
_HINT = (
    "\nThe written note for this video lists these exercises, in order:\n{moves}\n"
    "Use exactly these names for the ones you find, in this order. Skip a listed one "
    "only if it is never shown; add an unlisted one only if it is clearly a different "
    "exercise.")


class ClipError(Exception):
    pass


def _run(args: list[str], timeout: int = 300) -> None:
    subprocess.run(args, check=True, capture_output=True, text=True, timeout=timeout)


def _fetch(url: str, work: pathlib.Path) -> pathlib.Path:
    try:
        _run(["yt-dlp", "-q", "--no-playlist", "-f", "mp4/best",
              "-o", str(work / "src.%(ext)s"), url])
    except FileNotFoundError as e:
        raise ClipError("yt-dlp is not installed") from e
    except subprocess.CalledProcessError as e:
        raise ClipError(f"yt-dlp failed: {(e.stderr or '')[-300:]}") from e
    except subprocess.TimeoutExpired as e:
        raise ClipError("yt-dlp timed out") from e
    vids = [p for p in work.glob("src.*") if p.suffix in {".mp4", ".mkv", ".webm", ".mov"}]
    if not vids:
        raise ClipError("yt-dlp produced no video (photo post?)")
    return vids[0]


def duration(path: pathlib.Path) -> float:
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                        "-of", "csv=p=0", str(path)], capture_output=True, text=True, timeout=30)
    try:
        return float(r.stdout.strip())
    except ValueError:
        return 0.0


def cut(src: pathlib.Path, out: pathlib.Path, start: float = 0.0, end: float | None = None,
        width: int = 480, crf: int = 30) -> pathlib.Path:
    """Silent H.264 loop at the source's own aspect ratio (never cropped)."""
    args = ["ffmpeg", "-nostdin", "-loglevel", "error", "-y", "-ss", f"{start:.2f}", "-i", str(src)]
    args += ["-t", f"{(end - start):.2f}"] if end else ["-t", str(MAX_SECONDS)]
    args += ["-an", "-vf", f"scale={width}:-2,fps=24", "-c:v", "libx264", "-preset", "veryfast",
             "-crf", str(crf), "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(out)]
    _run(args)
    # A still for the tile, so the app shows a picture at once instead of a
    # grey placeholder while the video downloads.
    _run(["ffmpeg", "-nostdin", "-loglevel", "error", "-y", "-ss", "0.3", "-i", str(out),
          "-frames:v", "1", "-q:v", "6", str(out.with_suffix(".jpg"))])
    return out


def _ask_gemini(src: pathlib.Path, work: pathlib.Path, prompt: str) -> str:
    """Send a small full-length proxy of the video plus a prompt; return the
    text reply ("" without a key)."""
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not key:
        return ""
    # A small full-length proxy keeps the request well under the inline limit.
    proxy = work / "proxy.mp4"
    if not proxy.exists():
        _run(["ffmpeg", "-nostdin", "-loglevel", "error", "-y", "-i", str(src), "-t", "180", "-an",
              "-vf", "scale=360:-2,fps=12", "-c:v", "libx264", "-preset", "veryfast", "-crf", "34",
              "-pix_fmt", "yuv420p", str(proxy)])
    body = {"contents": [{"parts": [
        {"inline_data": {"mime_type": "video/mp4", "data": base64.b64encode(proxy.read_bytes()).decode()}},
        {"text": prompt}]}],
        "generationConfig": {"responseMimeType": "application/json", "temperature": 0}}
    req = urllib.request.Request(
        f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent",
        data=json.dumps(body).encode(), method="POST",
        headers={"Content-Type": "application/json", "x-goog-api-key": key})
    with urllib.request.urlopen(req, timeout=180) as r:
        reply = json.load(r)
    return "".join(p.get("text", "") for p in
                   reply.get("candidates", [{}])[0].get("content", {}).get("parts", []))


def _hint(hints: list[str] | None) -> str:
    return _HINT.format(moves="\n".join(f"{i}. {h}" for i, h in enumerate(hints, 1))) if hints else ""


def find_moves(src: pathlib.Path, work: pathlib.Path, hints: list[str] | None = None) -> list[dict]:
    """For a reel filmed in one take: ask Gemini where each exercise is.
    Returns validated [{name,start,end}]."""
    text = _ask_gemini(src, work, _PROMPT + _hint(hints))
    m = re.search(r"\[.*\]", text, re.S)
    raw = json.loads(m.group(0)) if m else []
    return validate(raw, duration(src))


# --- reels edited as one shot per exercise ---------------------------------
# Most workout reels (igor.system's, for one) cut to a new shot for every
# exercise. Asking Gemini for timestamps on those was loose — a "move" clip
# showed 2-3 exercises — while the cuts themselves are exact and free to find.
# So: find the cuts, and ask Gemini only to NAME what each shot shows.

SCENE = 0.3        # ffmpeg scene-change score that counts as a cut
MIN_SHOT = 0.8     # shorter shots are flashes/transitions, merged into a neighbour


def shots(src: pathlib.Path) -> list[tuple[float, float]]:
    """[(start, end)] of each shot, from ffmpeg's scene-change detection."""
    r = subprocess.run(["ffmpeg", "-nostdin", "-hide_banner", "-i", str(src), "-an",
                        "-vf", f"select='gt(scene,{SCENE})',showinfo", "-f", "null", "-"],
                       capture_output=True, text=True, timeout=300)
    cuts = [float(x) for x in re.findall(r"pts_time:([0-9.]+)", r.stderr)]
    total = duration(src)
    edges = [0.0] + [c for c in cuts if 0 < c < total] + [total]
    spans = [(a, b) for a, b in zip(edges, edges[1:], strict=False) if b > a]
    merged: list[list[float]] = []
    for a, b in spans:
        if merged and (b - a < MIN_SHOT or merged[-1][1] - merged[-1][0] < MIN_SHOT):
            merged[-1][1] = b
        else:
            merged.append([a, b])
    return [(round(a, 2), round(b, 2)) for a, b in merged]


_NAME_PROMPT = (
    "This exercise video is edited as separate shots, listed below as time ranges. "
    "For EACH range, list the exercises demonstrated in it, in order. Most ranges show one "
    "exercise; a long range filmed in one take may show several — then give each its own "
    "start and end (seconds, one decimal) INSIDE that range. Skip ranges that show no "
    "exercise (talking, title card). Reply with ONLY JSON: "
    '[{{"range": 1, "name": "...", "start": 0.0, "end": 0.0}}]\n'
    "Ranges (seconds):\n{ranges}")


def name_shots(src: pathlib.Path, work: pathlib.Path, spans: list[tuple[float, float]],
               hints: list[str] | None = None) -> list[dict]:
    """[{name, start, end}] with every entry clamped inside its own shot, so a
    clip can never cross a cut into the next exercise."""
    ranges = "\n".join(f"{i}. {a:.1f}-{b:.1f}" for i, (a, b) in enumerate(spans, 1))
    text = _ask_gemini(src, work, _NAME_PROMPT.format(ranges=ranges) + _hint(hints))
    m = re.search(r"\[.*\]", text, re.S)
    raw = json.loads(m.group(0)) if m else []
    out = []
    for e in raw if isinstance(raw, list) else []:
        try:
            i = int(e["range"]) - 1
            name = str(e["name"]).strip()
        except (KeyError, TypeError, ValueError):
            continue
        if not (0 <= i < len(spans)) or not name or name.lower() in ("none", "n/a"):
            continue
        lo, hi = spans[i]
        try:
            a, b = float(e.get("start", lo)), float(e.get("end", hi))
        except (TypeError, ValueError):
            a, b = lo, hi
        a, b = max(lo, min(a, hi)), max(lo, min(b, hi))
        if b - a < 0.8:          # a nonsense sub-range: take the whole shot
            a, b = lo, hi
        out.append({"name": name, "start": a, "end": b, "shot": i})
    return out


def moves_from_shots(found: list[dict]) -> list[dict]:
    """Order by time, drop overlaps, merge a move that continues into the next
    shot under the same name, and keep clear of shot edges so no frame of a
    neighbour leaks in. Clips are capped at 8 s."""
    out: list[dict] = []
    for f in sorted(found, key=lambda f: f["start"]):
        if out and f["start"] < out[-1]["end"] - 0.05:
            continue  # overlaps the previous move
        if (out and out[-1]["name"].lower() == f["name"].lower()
                and f["shot"] == out[-1]["shot"] + 1 and abs(f["start"] - out[-1]["end"]) < 0.3):
            out[-1]["end"], out[-1]["shot"] = f["end"], f["shot"]
            continue
        out.append(dict(f))
    moves = []
    for m in out:
        a, b = m["start"] + 0.1, min(m["end"] - 0.1, m["start"] + 8.1)
        if b - a >= 0.6:
            moves.append({"name": m["name"], "start": round(a, 2), "end": round(b, 2)})
    return moves


def validate(raw, total: float) -> list[dict]:
    """Drop anything that can't be a real cut: outside the video, under 0.8 s,
    overlapping the previous move, or unnamed. Long ranges are capped at 8 s."""
    out, last_end = [], 0.0
    for m in raw if isinstance(raw, list) else []:
        try:
            name, a, b = str(m["name"]).strip(), float(m["start"]), float(m["end"])
        except (KeyError, TypeError, ValueError):
            continue
        if total:
            b = min(b, total)
        b = min(b, a + 8)
        if not name or a < 0 or b - a < 0.8 or a < last_end - 0.2:
            continue
        out.append({"name": name, "start": round(a, 1), "end": round(b, 1)})
        last_end = b
    return out


def make_for_save(url: str, sid: str, video_path: str | None = None,
                  hints: list[str] | None = None) -> list[dict]:
    """Build the whole loop + per-move loops for one save. Returns the clip list
    for appdb.set_clips (index 0 = whole loop)."""
    work = TMP / uuid.uuid4().hex[:10]
    work.mkdir(parents=True, exist_ok=True)
    dest = appdb.CLIPS / sid
    try:
        src = pathlib.Path(video_path) if video_path and pathlib.Path(video_path).exists() \
            else _fetch(url, work)
        staged = work / "out"
        staged.mkdir()
        clips = [{"name": "Whole reel", "file": f"{sid}/loop.mp4", "start": 0.0, "end": None}]
        cut(src, staged / "loop.mp4")
        try:
            spans = shots(src)
            if len(spans) >= 2:
                moves = moves_from_shots(name_shots(src, work, spans, hints))
            else:
                moves = find_moves(src, work, hints)  # one continuous take
        except Exception as e:  # noqa: BLE001
            log.warning("move detection failed for %s: %s", url, e)
            moves = []
        for i, m in enumerate(moves, 1):
            cut(src, staged / f"move{i}.mp4", m["start"], m["end"], width=480, crf=28)
            clips.append({"name": m["name"], "file": f"{sid}/move{i}.mp4",
                          "start": m["start"], "end": m["end"]})
        # Swap in the new set only when it is complete.
        if dest.exists():
            shutil.rmtree(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(staged), str(dest))
        return clips
    finally:
        shutil.rmtree(work, ignore_errors=True)
