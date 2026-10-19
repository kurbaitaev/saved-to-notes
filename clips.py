#!/usr/bin/env python3
"""Looping clips for workout saves (category Move) — the Afterscroll Move screen.

A Move save gets:
- a whole-reel loop (silent, 480 px), the tile on the Move grid, and
- one short loop PER EXERCISE, with that exercise's name, form cue and dose,
  so the player shows exactly the move being done.

How the exercises are found — and why, from what broke:

1. The video's own CUTS are the boundaries (shots.py). Workout reels cut to a
   new shot per exercise; ffmpeg finds those cuts exactly. When Gemini guessed
   timestamps instead, one igor.system "move" clip showed 2-3 exercises.
2. Gemini only DESCRIBES each shot: name, cue, dose. A shot of 5 s or more may
   hold several moves (Mr. Fine films three stretches in one 11.8 s take); its
   sub-ranges are clamped inside the shot, so a clip can never cross a cut.
3. The video is the single source of truth for which moves exist. The note's
   move list (written from sampled frames) only lends names, doses and cues
   where they match; the result is written back to the save, so the app never
   reconciles two disagreeing lists again (5 noted vs 2 cut; 8 vs 15).
4. Every answer is validated, a failed Gemini call is retried once, and if it
   still fails the shots alone become "Move 1..n" — clips are never guessed.
5. Each finished clip is checked for a cut inside it; one that spans a cut is
   trimmed back to its first shot.

Files land in appdb.CLIPS/<save id>/ and are served by api.py. Best-effort: a
missing clip never fails the save.
"""

import base64
import json
import logging
import os
import pathlib
import re
import shutil
import subprocess
import time
import urllib.request
import uuid

import appdb
import details
import shots

log = logging.getLogger("saved-to-notes")

TMP = pathlib.Path("/tmp/saved-to-notes/clips")
MAX_SECONDS = 45          # the whole-reel loop is trimmed to this
MAX_MOVE = 8.0            # one exercise clip is at most this long
SPLIT_MIN = 5.0           # only a shot this long may hold more than one exercise
EDGE = 0.1                # seconds kept clear of each shot edge
GEMINI_MODEL = "gemini-2.5-flash"

_SHOT_PROMPT = (
    "This exercise video is edited as separate shots, listed below as time ranges. "
    "For EACH range, list the exercises demonstrated in it, in order. A range under "
    f"{SPLIT_MIN:.0f} s shows exactly ONE exercise. A longer range filmed in one take may "
    "show several — then give each its own start and end (seconds, one decimal) INSIDE "
    "that range. Skip ranges with no exercise (talking, title card).\n"
    "For each exercise give: `name` (short, what is actually shown), `cue` (one short "
    "form tip, from the speech or on-screen text if there is one, else from what you "
    "see), `dose` (reps or time ONLY if said or shown, e.g. \"20 reps\", \"1 min each "
    "side\"; else \"\").\n"
    "Reply with ONLY JSON: "
    '[{{"range": 1, "name": "...", "cue": "...", "dose": "", "start": 0.0, "end": 0.0}}]\n'
    "Ranges (seconds):\n{ranges}")

_TAKE_PROMPT = (
    "This is an exercise video filmed in one continuous take. List every distinct "
    "exercise or stretch DEMONSTRATED, in order. For each give the time range in seconds "
    "(one decimal) of the cleanest 2-5 seconds of clear demonstration — skip intro talk "
    "and transitions. One exercise is ONE entry: both sides, several reps or a second "
    "angle of the same move are not new exercises. Also give `cue` (one short form tip) "
    "and `dose` (reps or time only if said or shown, else \"\").\n"
    'Reply with ONLY JSON: [{"name": "...", "cue": "...", "dose": "", "start": 0.0, "end": 0.0}]')

_HINT = (
    "\nThe written note for this video lists these exercises:\n{moves}\n"
    "Reuse one of these names ONLY when the clip clearly shows that exact exercise; "
    "otherwise give a short name of your own for what is actually shown. A wrong "
    "name is worse than a new one.")


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


def duration(path) -> float:
    return shots.duration(path)


def cut(src: pathlib.Path, out: pathlib.Path, start: float = 0.0, end: float | None = None,
        width: int = 480, crf: int = 30) -> pathlib.Path:
    """Silent H.264 loop at the source's own aspect ratio (never cropped), plus
    a still of its first frame for the app to show while the video downloads."""
    args = ["ffmpeg", "-nostdin", "-loglevel", "error", "-y", "-ss", f"{start:.2f}", "-i", str(src)]
    args += ["-t", f"{(end - start):.2f}"] if end else ["-t", str(MAX_SECONDS)]
    args += ["-an", "-vf", f"scale={width}:-2,fps=24", "-c:v", "libx264", "-preset", "veryfast",
             "-crf", str(crf), "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(out)]
    _run(args)
    _run(["ffmpeg", "-nostdin", "-loglevel", "error", "-y", "-ss", "0.3", "-i", str(out),
          "-frames:v", "1", "-q:v", "6", str(out.with_suffix(".jpg"))])
    return out


# --- asking Gemini ---------------------------------------------------------

def _ask_gemini(src: pathlib.Path, work: pathlib.Path, prompt: str, tries: int = 2) -> list | None:
    """Send a small full-length proxy of the video plus a prompt; return the
    JSON array it answers with, or None (no key, or still failing after a
    retry) — the caller then falls back to something that is never a guess."""
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not key:
        return None
    proxy = work / "proxy.mp4"
    if not proxy.exists():
        _run(["ffmpeg", "-nostdin", "-loglevel", "error", "-y", "-i", str(src), "-t", "180", "-an",
              "-vf", "scale=360:-2,fps=12", "-c:v", "libx264", "-preset", "veryfast", "-crf", "34",
              "-pix_fmt", "yuv420p", str(proxy)])
    body = json.dumps({"contents": [{"parts": [
        {"inline_data": {"mime_type": "video/mp4", "data": base64.b64encode(proxy.read_bytes()).decode()}},
        {"text": prompt}]}],
        "generationConfig": {"responseMimeType": "application/json", "temperature": 0}}).encode()
    for attempt in range(1, tries + 1):
        try:
            req = urllib.request.Request(
                f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent",
                data=body, method="POST",
                headers={"Content-Type": "application/json", "x-goog-api-key": key})
            with urllib.request.urlopen(req, timeout=180) as r:
                reply = json.load(r)
            text = "".join(p.get("text", "") for p in
                           reply.get("candidates", [{}])[0].get("content", {}).get("parts", []))
            m = re.search(r"\[.*\]", text, re.S)
            data = json.loads(m.group(0)) if m else None
            if isinstance(data, list):
                return data
            log.warning("gemini answered without a JSON list (attempt %d)", attempt)
        except Exception as e:  # noqa: BLE001
            log.warning("gemini call failed (attempt %d): %s", attempt, e)
        time.sleep(2 * attempt)
    return None


def _hint(hints: list[str] | None) -> str:
    return _HINT.format(moves="\n".join(f"{i}. {h}" for i, h in enumerate(hints, 1))) if hints else ""


def _text(v) -> str:
    return str(v).strip() if isinstance(v, str | int | float) else ""


def _dose(v) -> str:
    d = _text(v)
    return "" if d.lower() in details._JUNK_DOSE else d


# --- turning answers into moves -----------------------------------------------

def per_shot(raw: list, spans: list[tuple[float, float]]) -> list[dict]:
    """Gemini's per-range answers, each clamped inside its own shot. A short
    shot keeps only its first exercise, over the whole shot."""
    out: list[dict] = []
    for e in raw if isinstance(raw, list) else []:
        if not isinstance(e, dict):
            continue
        try:
            i = int(e["range"]) - 1
        except (KeyError, TypeError, ValueError):
            continue
        name = _text(e.get("name"))
        if not (0 <= i < len(spans)) or not name or name.lower() in ("none", "n/a"):
            continue
        lo, hi = spans[i]
        a, b = lo, hi
        if hi - lo >= SPLIT_MIN:
            try:
                a, b = float(e.get("start", lo)), float(e.get("end", hi))
            except (TypeError, ValueError):
                a, b = lo, hi
            a, b = max(lo, min(a, hi)), max(lo, min(b, hi))
            if b - a < 0.8:
                a, b = lo, hi
        elif any(o["shot"] == i for o in out):
            continue  # a short shot is one exercise
        out.append({"name": name, "cue": _text(e.get("cue")), "dose": _dose(e.get("dose")),
                    "start": a, "end": b, "shot": i})
    return out


def moves_from_shots(found: list[dict]) -> list[dict]:
    """Order by time, drop overlaps, merge a move that continues into the next
    shot under the same name, and keep clear of shot edges so no frame of a
    neighbour leaks in. Clips are capped at MAX_MOVE seconds."""
    out: list[dict] = []
    for f in sorted(found, key=lambda f: f["start"]):
        if out and f["start"] < out[-1]["end"] - 0.05:
            continue
        if (out and out[-1]["name"].lower() == f["name"].lower()
                and f["shot"] == out[-1]["shot"] + 1 and abs(f["start"] - out[-1]["end"]) < 0.3):
            out[-1]["end"], out[-1]["shot"] = f["end"], f["shot"]
            continue
        out.append(dict(f))
    moves = []
    for m in out:
        a, b = m["start"] + EDGE, min(m["end"] - EDGE, m["start"] + EDGE + MAX_MOVE)
        if b - a >= 0.6:
            moves.append({"name": m["name"], "cue": m.get("cue", ""), "dose": m.get("dose", ""),
                          "start": round(a, 2), "end": round(b, 2)})
    return moves


def validate(raw, total: float) -> list[dict]:
    """One-take answers: drop anything that can't be a real cut — outside the
    video, under 0.8 s, overlapping the previous move, or unnamed."""
    out, last_end = [], 0.0
    for m in raw if isinstance(raw, list) else []:
        try:
            name, a, b = _text(m["name"]), float(m["start"]), float(m["end"])
        except (KeyError, TypeError, ValueError):
            continue
        if total:
            b = min(b, total)
        b = min(b, a + MAX_MOVE)
        if not name or a < 0 or b - a < 0.8 or a < last_end - 0.2:
            continue
        out.append({"name": name, "cue": _text(m.get("cue")), "dose": _dose(m.get("dose")),
                    "start": round(a, 1), "end": round(b, 1)})
        last_end = b
    return out


def detect(src: pathlib.Path, work: pathlib.Path, hints: list[str] | None = None) -> list[dict]:
    """The exercises in a video: [{name, cue, dose, start, end}] in video order."""
    spans = shots.shots(src)
    if len(spans) >= 2:
        ranges = "\n".join(f"{i}. {a:.1f}-{b:.1f} ({b - a:.1f} s)" for i, (a, b) in enumerate(spans, 1))
        raw = _ask_gemini(src, work, _SHOT_PROMPT.format(ranges=ranges) + _hint(hints))
        if raw is None:
            # No Gemini: the shots alone are still exact clips, just unnamed.
            found = [{"name": f"Move {i}", "cue": "", "dose": "", "start": a, "end": b, "shot": i - 1}
                     for i, (a, b) in enumerate(spans, 1)]
        else:
            found = per_shot(raw, spans)
        return moves_from_shots(found)
    raw = _ask_gemini(src, work, _TAKE_PROMPT + _hint(hints))
    return validate(raw or [], shots.duration(src))


def check_clip(path: pathlib.Path) -> float | None:
    """Where a finished clip cuts to another shot, or None if it is one shot.
    Cuts within 0.2 s of either end are encoder noise, not a second exercise."""
    total = shots.duration(path)
    inner = [c for c in shots.cuts(path) if 0.2 < c < total - 0.2]
    return inner[0] if inner else None


def as_detail_moves(made: list[dict], noted: list[dict] | None) -> list[dict]:
    """The save's move list, rebuilt from the clips (video order): each clip's
    cue and dose, falling back to the note's where the names match."""
    noted = [m for m in noted or [] if isinstance(m, dict) and m.get("name")]
    by_name = {str(m["name"]).strip().lower(): m for m in noted}
    out = []
    for c in made[1:]:
        n = by_name.get(c["name"].strip().lower(), {})
        mv = {"name": c["name"]}
        dose = c.get("dose") or _dose(n.get("dose"))
        cue = c.get("cue") or _text(n.get("cues"))
        if dose:
            mv["dose"] = dose
        if cue:
            mv["cues"] = cue
        out.append(mv)
    return out


def make_for_save(url: str, sid: str, video_path: str | None = None,
                  hints: list[str] | None = None) -> list[dict]:
    """Build the whole loop + per-move loops for one save. Returns the clip list
    for appdb.set_clips (index 0 = whole loop; others carry cue and dose)."""
    work = TMP / uuid.uuid4().hex[:10]
    work.mkdir(parents=True, exist_ok=True)
    dest = appdb.CLIPS / sid
    try:
        src = pathlib.Path(video_path) if video_path and pathlib.Path(video_path).exists() \
            else _fetch(url, work)
        staged = work / "out"
        staged.mkdir()
        made = [{"name": "Whole reel", "file": f"{sid}/loop.mp4", "start": 0.0, "end": None}]
        cut(src, staged / "loop.mp4")
        try:
            moves = detect(src, work, hints)
        except Exception as e:  # noqa: BLE001
            log.warning("move detection failed for %s: %s", url, e)
            moves = []
        for i, m in enumerate(moves, 1):
            out = staged / f"move{i}.mp4"
            cut(src, out, m["start"], m["end"], crf=28)
            inner = check_clip(out)
            if inner is not None:
                # Spans a cut after all (a split inside a long take): keep only
                # the first shot rather than show two exercises under one name.
                log.warning("clip %d of %s crosses a cut at %.1fs — trimmed", i, url, inner)
                m["end"] = round(m["start"] + inner - EDGE, 2)
                cut(src, out, m["start"], m["end"], crf=28)
            made.append({"name": m["name"], "file": f"{sid}/move{i}.mp4", "start": m["start"],
                         "end": m["end"], "cue": m.get("cue", ""), "dose": m.get("dose", "")})
        # Swap in the new set only when it is complete.
        if dest.exists():
            shutil.rmtree(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(staged), str(dest))
        return made
    finally:
        shutil.rmtree(work, ignore_errors=True)
