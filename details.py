#!/usr/bin/env python3
"""Structured details for real-life saves — what the Afterscroll app needs.

A knowledge note is read; a real-life save is *used*: a place goes on a map, an
event on a date, a recipe into cook mode, a workout into a routine. Those
screens need fields, not prose, so the model fills a `details` object for the
five real-life categories (folders.REAL_LIFE) and nothing for the rest.

One flat object for every category, because OpenAI strict mode needs a single
fixed schema; each category simply uses its own subset (FIELDS). It is stored
on the Notion page as compact JSON in the "Details" column, which the app reads.

Same pattern as folders.py and topics.py: RULES go into the prompt, SCHEMA into
the strict backend, clean() guards whatever comes back.
"""

import json
import re

import folders

PLACE_KINDS = ["cafe", "restaurant", "bar", "shop", "gym", "park", "viewpoint", "beach",
               "hotel", "museum", "neighbourhood", "city", "other"]
BODY_AREAS = ["full body", "hips", "spine", "shoulders", "legs", "core", "arms", "neck", "feet"]
PURPOSES = ["mobility", "strength", "warm-up", "cardio", "skill", "recovery"]

FIELDS = {
    folders.VISIT: ("name", "kind", "address", "city", "country", "why"),
    folders.ATTEND: ("name", "date", "time", "venue", "city", "country", "url", "why"),
    folders.BUY: ("name", "brand", "price", "url", "why"),
    folders.COOK: ("name", "minutes", "servings", "ingredients"),
    folders.MOVE: ("name", "body_area", "purpose", "minutes", "moves"),
}

RULES = f"""\
## Details (only for {", ".join(folders.REAL_LIFE)})

If `folder` is a real-life category, fill `details` with exactly what that
screen of the app needs; otherwise set every field in it to null / [].
Never guess: an unknown field is null. Read the caption, the on-screen text and
the speech — addresses and dates are often only on screen.

- **{folders.VISIT}** — `name` (the place itself, e.g. "Sightglass Coffee"), `kind`
  ({"|".join(PLACE_KINDS)}), `address` if shown, `city`, `country`, `why` (one line:
  what to get or do there). A reel about several places → the best one in
  `name`, and list the others in `items` as type "resource".
- **{folders.ATTEND}** — `name`, `date` (YYYY-MM-DD, use today's date to resolve
  "this Saturday"), `time` (HH:MM, 24h), `venue`, `city`, `country`, `url` (tickets or
  event page if verified), `why`.
- **{folders.BUY}** — `name`, `brand`, `price` (as written, with currency), `url`
  (official product page if verified), `why`.
- **{folders.COOK}** — `name`, `minutes` (total), `servings`, `ingredients` (each with
  its amount, e.g. "200 g chickpeas"). The method goes in the normal `steps`.
- **{folders.MOVE}** — `name` (a short routine name, e.g. "Hip opener flow"),
  `body_area` ({"|".join(BODY_AREAS)}), `purpose` ({"|".join(PURPOSES)}), `minutes`
  (total), `moves`: every exercise in order as `{{name, dose, cues}}` — `dose` like
  "8 reps", "30 s", "3 × 10 each side"; `cues` one short form tip.
"""

_MOVE = {
    "type": "object",
    "properties": {"name": {"type": "string"}, "dose": {"type": ["string", "null"]},
                   "cues": {"type": ["string", "null"]}},
    "required": ["name", "dose", "cues"],
    "additionalProperties": False,
}
_STR = {"type": ["string", "null"]}
SCHEMA = {
    "type": "object",
    "properties": {
        "name": _STR, "kind": _STR, "address": _STR, "city": _STR, "country": _STR,
        "why": _STR, "date": _STR, "time": _STR, "venue": _STR, "url": _STR,
        "brand": _STR, "price": _STR, "minutes": {"type": ["integer", "null"]},
        "servings": {"type": ["integer", "null"]},
        "ingredients": {"type": "array", "items": {"type": "string"}},
        "body_area": _STR, "purpose": _STR,
        "moves": {"type": "array", "items": _MOVE},
    },
    "required": ["name", "kind", "address", "city", "country", "why", "date", "time", "venue",
                 "url", "brand", "price", "minutes", "servings", "ingredients", "body_area",
                 "purpose", "moves"],
    "additionalProperties": False,
}

_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_JUNK_DOSE = {"not specified", "unspecified", "n/a", "na", "none", "unknown", "-", "?",
              "hold", "reps", "reps each side", "hold / reps", "varies"}
_TIME = re.compile(r"^\d{1,2}:\d{2}$")


def _s(v) -> str:
    return str(v).strip() if isinstance(v, str | int | float) and str(v).strip() else ""


def _int(v) -> int | None:
    try:
        n = int(v)
    except (TypeError, ValueError):
        return None
    return n if 0 < n < 10_000 else None


def clean(category: str, raw) -> dict:
    """Keep only the fields this category uses, in the shapes the app expects.
    Returns {} for knowledge categories or when nothing usable came back."""
    fields = FIELDS.get(folders.normalize(category))
    if not fields or not isinstance(raw, dict):
        return {}
    out: dict = {}
    for f in fields:
        v = raw.get(f)
        if f in ("minutes", "servings"):
            n = _int(v)
            if n:
                out[f] = n
        elif f == "ingredients":
            items = [_s(x) for x in v] if isinstance(v, list) else []
            if any(items):
                out[f] = [x for x in items if x]
        elif f == "moves":
            moves = []
            for m in v if isinstance(v, list) else []:
                if isinstance(m, dict) and _s(m.get("name")):
                    mv = {k: _s(m.get(k)) for k in ("name", "dose", "cues") if _s(m.get(k))}
                    if mv.get("dose", "").lower() in _JUNK_DOSE:
                        mv.pop("dose")  # the model saying it doesn't know is not a dose
                    moves.append(mv)
                elif _s(m):
                    moves.append({"name": _s(m)})
            if moves:
                out[f] = moves
        elif f == "date":
            if _DATE.match(_s(v)):
                out[f] = _s(v)
        elif f == "time":
            if _TIME.match(_s(v)):
                out[f] = _s(v)
        elif f == "url":
            if _s(v).lower().startswith(("http://", "https://")):
                out[f] = _s(v)
        elif f in ("kind", "body_area", "purpose"):
            allowed = {"kind": PLACE_KINDS, "body_area": BODY_AREAS, "purpose": PURPOSES}[f]
            low = _s(v).lower()
            if low in allowed:
                out[f] = low
            elif low:
                out[f] = "other" if f == "kind" else low
        elif _s(v):
            out[f] = _s(v)
    return out


def to_json(d: dict) -> str:
    """Compact JSON for the Notion "Details" column (rich text caps at 2000
    characters). Long lists are trimmed from the end rather than producing
    JSON the app cannot parse."""
    d = dict(d)
    while True:
        s = json.dumps(d, ensure_ascii=False, separators=(",", ":"))
        if len(s) <= 2000:
            return s
        for key in ("ingredients", "moves"):
            if d.get(key):
                d[key] = d[key][:-1]
                break
        else:
            d.pop("why", None)
            d.pop("address", None)
            return json.dumps(d, ensure_ascii=False, separators=(",", ":"))[:2000]
