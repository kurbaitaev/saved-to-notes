#!/usr/bin/env python3
"""The remake pipeline, between a ticked bookmark and the views it earned.

    python3 content.py drafts              # new "Worth remaking" ticks → Russian draft rows
    python3 content.py drafts --backfill   # also draft every ticked bookmark still without a row
    python3 content.py stats               # posted reels → views on their Content rows
    python3 content.py stats --force       # run even if the last pass was under 3 days ago

drafts (timer, every 15 min): a bookmark ticked "Worth remaking" that has no row
in 💡 Content Ideas gets one — status Inbox, a Russian script close to the
original, laid out like the scripts already there (big lines, read while filming).

stats (timer, every 3 days): one Apify call lists the recent reels of both
accounts, trial reels included. Variants of one video share a caption, so they
are grouped; each group is matched to its Content row (by a link already on the
row, else by the model comparing caption and script) and the row gets total
views, likes, comments, the best variant's link and status Published. The views
also land on the source bookmark ("Remake views"), so the saved reel shows what
its remake did. Nothing is written when the scrape fails or comes back empty.
"""

import argparse
import datetime as dt
import json
import logging
import os
import pathlib
import re
import subprocess
import sys

PROJ = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(PROJ))

import acquire  # noqa: E402
import notion  # noqa: E402

log = logging.getLogger("saved-to-notes.content")

NOTION = "https://api.notion.com/v1"
CONTENT_DB = os.environ.get("CONTENT_DATABASE_ID", "821c50bb18f14c7ca1ae9f350376a77b")
STATE = PROJ / "logs" / "content_state.json"
REEL_ACTOR = "apify~instagram-reel-scraper"
STATS_EVERY = dt.timedelta(days=3)
NEW_ROW_WINDOW = dt.timedelta(days=7)  # unmatched reels younger than this get a row of their own
MATCHABLE = {"Inbox", "ideas", "Researching", "Editing", "Scheduled", "Published", None}

# Columns the stats pass owns. Created on first run; never touched otherwise.
CONTENT_COLUMNS = {
    "Posted": {"url": {}},
    "Posted on": {"date": {}},
    "Views": {"number": {"format": "number_with_commas"}},
    "Likes": {"number": {"format": "number_with_commas"}},
    "Comments": {"number": {"format": "number_with_commas"}},
    "Variants": {"number": {}},
    "Stats updated": {"date": {}},
}
BOOKMARK_COLUMNS = {"Remake views": {"number": {"format": "number_with_commas"}}}


# --- plumbing -------------------------------------------------------------------

def load_env() -> None:
    f = PROJ / ".env"
    if f.exists():
        for line in f.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def _tok() -> str:
    return os.environ["NOTION_TOKEN"]


def api(path: str, method: str = "GET", body: dict | None = None) -> dict:
    return notion._api(f"{NOTION}/{path}", _tok(), method, body)


def query(db: str, flt: dict | None = None) -> list[dict]:
    out, cursor = [], None
    while True:
        body = {"page_size": 100, **({"filter": flt} if flt else {}),
                **({"start_cursor": cursor} if cursor else {})}
        d = api(f"databases/{db}/query", "POST", body)
        out += d["results"]
        if not d.get("has_more"):
            return out
        cursor = d["next_cursor"]


def load_state() -> dict:
    try:
        return json.loads(STATE.read_text())
    except (OSError, ValueError):
        return {}


def save_state(s: dict) -> None:
    STATE.parent.mkdir(exist_ok=True)
    tmp = STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps(s, ensure_ascii=False, indent=1))
    tmp.replace(STATE)


def ensure_columns(db: str, wanted: dict) -> None:
    have = api(f"databases/{db}")["properties"]
    missing = {k: v for k, v in wanted.items() if k not in have}
    if missing:
        api(f"databases/{db}", "PATCH", {"properties": missing})
        log.info("added columns to %s: %s", db, ", ".join(missing))


def text_of(prop: dict) -> str:
    t = prop.get("type")
    return "".join(x.get("plain_text", "") for x in prop.get(t) or []) if t in (
        "title", "rich_text") else ""


def status_of(row: dict) -> str | None:
    return ((row["properties"].get("Status") or {}).get("status") or {}).get("name")


def rt(s: str) -> list:
    # Notion caps one text run at 2000 chars.
    return [{"type": "text", "text": {"content": s[i:i + 2000]}} for i in range(0, len(s), 2000)] or []


def page_text(page_id: str, limit: int = 1500) -> str:
    out = []
    for b in api(f"blocks/{page_id}/children?page_size=100").get("results", []):
        body = b.get(b["type"]) or {}
        out.append("".join(x.get("plain_text", "") for x in body.get("rich_text") or []))
        if sum(map(len, out)) > limit:
            break
    return "\n".join(x for x in out if x).strip()[:limit]


def claude_bin() -> str:
    """Same lookup as the bot: a user unit's PATH omits ~/.local/bin."""
    import shutil
    for cand in (os.environ.get("CLAUDE_BIN", "").strip(), shutil.which("claude"),
                 str(pathlib.Path.home() / ".local/bin/claude")):
        if cand and pathlib.Path(cand).exists():
            return cand
    return "claude"


def ask_claude(prompt: str, timeout: int = 600) -> dict:
    """Run the headless Claude CLI and parse the JSON object it answers with."""
    args = [claude_bin(), "-p", prompt, "--max-turns", "3"]
    model = os.environ.get("CLAUDE_MODEL", "").strip()
    if model:
        args += ["--model", model]
    r = subprocess.run(args, cwd=PROJ, capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError(f"claude failed ({r.returncode}): {(r.stderr or r.stdout)[-500:]}")
    m = re.search(r"\{.*\}", r.stdout, re.S)
    if not m:
        raise RuntimeError(f"claude gave no JSON: {r.stdout[-300:]}")
    return json.loads(m.group(0))


def tell(text: str) -> None:
    import digest
    try:
        digest.send(text)
    except SystemExit as e:  # digest.send exits on a refusal; a message isn't worth dying for
        log.warning("telegram: %s", e)


def esc(s: str) -> str:
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def nid(s: str) -> str:
    """Bare 32-hex Notion id out of an id or URL ('' when there is none)."""
    m = re.search(r"([0-9a-f]{32})", (s or "").replace("-", ""))
    return m.group(1) if m else ""


# --- drafts ----------------------------------------------------------------------

DRAFT_PROMPT = """You are adapting someone else's Instagram reel into a Russian script that \
Magomed will film himself (talking head). His audience speaks Russian.

Rules:
- Stay CLOSE to the original: same order, same examples, same argument, same ending. \
Do not add ideas, statistics or advice that are not in the original. Do not summarise — \
cover the whole transcript.
- Natural spoken Russian, the way a person talks to camera: short sentences, "ты", no \
bureaucratic or translated-sounding phrasing. Read it back as a native speaker would and \
rewrite anything that sounds like machine translation.
- No emojis, no hashtags, no stage directions.
- Break it into beats: each beat is 1–4 short lines that are read in one breath.

Answer with ONE JSON object and nothing else:
{{"title": "<2–5 word Russian title>", "hook": "<the opening line, as in the script>", \
"beats": [["line", "line"], ["line"], ...]}}

Original author: {author}
Original title: {title}

ORIGINAL (verbatim):
{source}
"""


def vault_note(url: str) -> pathlib.Path | None:
    key = acquire.normalize_url(url)
    code = acquire._shortcode(key)
    for p in (PROJ / "vault").rglob("*.md"):
        head = p.read_text(errors="replace")[:600]
        m = re.search(r"^source:\s*(\S+)", head, re.M)
        if m and (acquire.normalize_url(m.group(1)) == key or (code and code in m.group(1))):
            return p
    return None


def note_source(p: pathlib.Path) -> tuple[str, str, str]:
    """(title, author, verbatim text) — the transcript, else slides, else the whole note."""
    t = p.read_text(errors="replace")
    title = (re.search(r"^# (.+)$", t, re.M) or [None, p.stem])[1]
    author = (re.search(r"^> — (.+)$", t, re.M) or [None, ""])[1]
    for h in ("## Transcript", "## Slides", "## Caption", "## Post"):
        i = t.find(h)
        if i >= 0:
            return title, author, t[i + len(h):].strip()[:12000]
    return title, author, t.split("---", 2)[-1].strip()[:12000]


def covered_keys(rows: list[dict]) -> set[str]:
    """Every source a Content row already points at — reel links and bookmark page ids."""
    keys = set()
    for r in rows:
        src = (r["properties"].get("Source") or {}).get("url") or ""
        if src:
            keys.add(acquire.normalize_url(src))
            if "notion" in src and nid(src):
                keys.add(nid(src))
    return keys


def beat_blocks(beats: list[list[str]]) -> list[dict]:
    out = []
    for beat in beats:
        lines = [str(x).strip() for x in beat if str(x).strip()]
        if not lines:
            continue
        out.append({"type": "heading_2", "heading_2": {"rich_text": rt("\n".join(lines))}})
        out.append({"type": "paragraph", "paragraph": {"rich_text": []}})
    return out


def make_draft(bm: dict, dry: bool) -> str | None:
    p = bm["properties"]
    src = (p.get("Source") or {}).get("url") or ""
    note = vault_note(src) if src else None
    if not note:
        log.warning("no vault note for %s — skipped", src or bm["id"])
        return None
    title, author, verbatim = note_source(note)
    author = author or text_of(p.get("Author") or {})
    d = ask_claude(DRAFT_PROMPT.format(author=author or "?", title=title, source=verbatim))
    beats = d.get("beats") or []
    if not beats:
        raise RuntimeError("draft came back without beats")
    name = f"{(d.get('title') or title).strip()} · сценарий для съёмки"
    if dry:
        print(name, "\n", "\n\n".join("\n".join(b) for b in beats))
        return None
    bm_url = f"https://www.notion.so/{bm['id'].replace('-', '')}"
    notes = [
        {"type": "paragraph", "paragraph": {"rich_text": rt(
            "Черновик бота по транскрипту оригинала. Проверь текст перед съёмкой.")}},
        {"type": "paragraph", "paragraph": {"rich_text": rt(f"Оригинал: {author} — {title}")}},
        {"type": "paragraph", "paragraph": {"rich_text": [
            {"type": "text", "text": {"content": "Исходный ролик", "link": {"url": src}}}]}},
        {"type": "paragraph", "paragraph": {"rich_text": [
            {"type": "text", "text": {"content": "Закладка", "link": {"url": bm_url}}}]}},
    ]
    children = beat_blocks(beats) + [
        {"type": "divider", "divider": {}},
        {"type": "toggle", "toggle": {"rich_text": rt("Источник и заметки"), "children": notes}},
    ]
    page = api("pages", "POST", {
        "parent": {"database_id": CONTENT_DB},
        "icon": {"type": "emoji", "emoji": "🎙️"},
        "properties": {
            "Idea": {"title": rt(name)},
            "Status": {"status": {"name": "Inbox"}},
            "Content type": {"select": {"name": "Video"}},
            "Platform": {"select": {"name": "Instagram"}},
            "Archive status": {"select": {"name": "Active"}},
            "Source": {"url": src},
            "Author": {"rich_text": rt(author)},
            "Hook / key idea": {"rich_text": rt(d.get("hook") or beats[0][0])},
            "Notes": {"rich_text": rt("Черновик бота — проверь перед съёмкой.")},
        },
        "children": children[:100],
    })
    return page.get("url")


def cmd_drafts(backfill: bool, dry: bool) -> int:
    state = load_state()
    ticked = query(os.environ["NOTION_DATABASE_ID"],
                   {"property": "Worth remaking", "checkbox": {"equals": True}})
    covered = covered_keys(query(CONTENT_DB))
    seen = set(state.get("seen_ticks", []))
    first_run = "seen_ticks" not in state
    todo = []
    for bm in ticked:
        src = (bm["properties"].get("Source") or {}).get("url") or ""
        done = acquire.normalize_url(src) in covered or nid(bm["id"]) in covered
        if done:
            seen.add(bm["id"])
        elif bm["id"] not in seen and (backfill or not first_run):
            todo.append(bm)
        elif first_run:
            seen.add(bm["id"])  # the backlog waits for --backfill; only new ticks draft by themselves
    made = 0
    for bm in todo:
        name = text_of(bm["properties"].get("Name") or {})
        try:
            url = make_draft(bm, dry)
        except Exception as e:  # noqa: BLE001
            log.error("draft failed for %s: %s", name, e)
            continue  # not marked seen: the next run tries again
        if dry:
            continue
        seen.add(bm["id"])
        state["seen_ticks"] = sorted(seen)
        save_state(state)
        if url:
            made += 1
            tell(f"🎙️ Черновик готов: <b>{esc(name)}</b>\n{url}")
    if not dry:
        state["seen_ticks"] = sorted(seen)
        save_state(state)
    print(f"{len(ticked)} ticked, {len(todo)} to draft, {made} drafted")
    return 0


# --- stats ------------------------------------------------------------------------

MATCH_PROMPT = """Match Magomed's posted Instagram reels to the Content rows they were made from.

Each REEL group is one video (possibly posted as several variants). Each ROW is a planned \
video with its script. A reel matches a row only when it is clearly the same video — same \
topic and the caption reflects that script. Different language versions of the same script \
(Russian vs English) DO match the same row. When unsure, answer null.

Answer with ONE JSON object and nothing else: {{"<group id>": "<row id or null>", ...}}

REELS:
{reels}

ROWS:
{rows}
"""


def caption_key(it: dict) -> str:
    return re.sub(r"\W+", " ", (it.get("caption") or "").lower()).strip()[:160] or it["shortCode"]


def scrape(handles: list[str], days: int) -> list[dict]:
    token = os.environ.get("APIFY_TOKEN", "").strip()
    if not token:
        raise RuntimeError("APIFY_TOKEN missing")
    items = acquire._apify_run(REEL_ACTOR, {
        "username": handles, "resultsLimit": 60, "onlyPostsNewerThan": f"{days} days",
        "skipTrialReels": False}, token)
    reels = [i for i in items if i.get("shortCode") and not i.get("error")]
    if not reels:
        raise RuntimeError(f"scrape returned no reels ({len(items)} item(s))")
    return reels


def group_reels(reels: list[dict]) -> dict[str, list[dict]]:
    groups: dict[str, list[dict]] = {}
    for it in reels:
        groups.setdefault(f"{it.get('ownerUsername')}:{caption_key(it)}", []).append(it)
    return groups


def totals(variants: list[dict]) -> dict:
    best = max(variants, key=lambda v: v.get("videoPlayCount") or 0)
    return {
        "views": sum(v.get("videoPlayCount") or v.get("videoViewCount") or 0 for v in variants),
        "likes": sum(max(v.get("likesCount") or 0, 0) for v in variants),
        "comments": sum(v.get("commentsCount") or 0 for v in variants),
        "variants": len(variants),
        "best": f"https://www.instagram.com/reel/{best['shortCode']}/",
        "first": min(v["timestamp"] for v in variants)[:10],
    }


def bookmark_for(src: str, bookmarks: dict[str, dict], by_source: dict[str, str]) -> str | None:
    if not src:
        return None
    if "notion" in src and nid(src) in bookmarks:
        return nid(src)
    return by_source.get(acquire.normalize_url(src))


def cmd_stats(force: bool, dry: bool, days: int) -> int:
    state = load_state()
    last = state.get("stats_at")
    now = dt.datetime.now(dt.timezone.utc)
    if last and not force and now - dt.datetime.fromisoformat(last) < STATS_EVERY - dt.timedelta(hours=6):
        print(f"last pass {last} — under 3 days ago, skipping (use --force)")
        return 0
    handles = [h.strip() for h in os.environ.get("IG_HANDLES", "kurbaitaev,kurbaiitaev").split(",") if h.strip()]
    reels = scrape(handles, days)
    groups = group_reels(reels)
    log.info("%d reels in %d videos from %s", len(reels), len(groups), ", ".join(handles))

    if not dry:
        ensure_columns(CONTENT_DB, CONTENT_COLUMNS)
        ensure_columns(os.environ["NOTION_DATABASE_ID"], BOOKMARK_COLUMNS)
    rows = {r["id"]: r for r in query(CONTENT_DB)}
    assign: dict[str, str | None] = state.setdefault("assign", {})  # group key → row id / None

    # 1) a reel link already on a row decides it
    for gid, variants in groups.items():
        codes = {v["shortCode"] for v in variants}
        for rid, r in rows.items():
            for col in ("Posted", "Source"):
                u = (r["properties"].get(col) or {}).get("url") or ""
                if any(c in u for c in codes):
                    assign[gid] = rid

    # 2) the model matches what is left (once per group: a "no match" is remembered)
    open_groups = [g for g in groups if g not in assign]
    if open_groups:
        cands = [r for r in rows.values() if status_of(r) in MATCHABLE]
        reel_txt = "\n".join(
            f"[{i}] @{groups[g][0].get('ownerUsername')} {groups[g][0]['timestamp'][:10]}: "
            f"{(groups[g][0].get('caption') or '')[:400]!r}" for i, g in enumerate(open_groups))
        row_txt = "\n".join(
            f"[{r['id']}] {text_of(r['properties']['Idea'])} ({status_of(r)}): "
            f"{page_text(r['id'], 500)!r}" for r in cands)
        ans = ask_claude(MATCH_PROMPT.format(reels=reel_txt, rows=row_txt))
        for i, g in enumerate(open_groups):
            rid = ans.get(str(i))
            assign[g] = rid if rid in rows else None

    # 3) a brand-new reel with no row gets one, so its views are not lost
    for g in open_groups:
        if assign.get(g) is None and not dry:
            first = min(groups[g], key=lambda v: v["timestamp"])
            if now - dt.datetime.fromisoformat(first["timestamp"].replace("Z", "+00:00")) < NEW_ROW_WINDOW:
                title = ((first.get("caption") or "").strip().splitlines() or [first["shortCode"]])[0][:90]
                page = api("pages", "POST", {"parent": {"database_id": CONTENT_DB},
                                             "properties": {"Idea": {"title": rt(title)},
                                                            "Status": {"status": {"name": "Published"}},
                                                            "Content type": {"select": {"name": "Video"}},
                                                            "Platform": {"select": {"name": "Instagram"}},
                                                            "Notes": {"rich_text": rt("Добавлено ботом: опубликованный ролик без строки в Content.")}}})
                rows[page["id"]] = page
                assign[g] = page["id"]

    # 4) write each row's totals across all its groups
    per_row: dict[str, list[dict]] = {}
    for g, variants in groups.items():
        if assign.get(g):
            per_row.setdefault(assign[g], []).extend(variants)
    bookmarks = {nid(b["id"]): b for b in query(os.environ["NOTION_DATABASE_ID"],
                                                 {"property": "Worth remaking", "checkbox": {"equals": True}})}
    by_source = {acquire.normalize_url((b["properties"].get("Source") or {}).get("url") or ""): k
                 for k, b in bookmarks.items()}
    prev = state.get("views", {})
    report = []
    today = now.date().isoformat()
    for rid, variants in per_row.items():
        t = totals(variants)
        name = text_of(rows[rid]["properties"]["Idea"]).replace(" · сценарий для съёмки", "")
        report.append((t["views"], t["views"] - prev.get(rid, 0), name, t))
        if dry:
            continue
        props = {"Posted": {"url": t["best"]}, "Posted on": {"date": {"start": t["first"]}},
                 "Views": {"number": t["views"]}, "Likes": {"number": t["likes"]},
                 "Comments": {"number": t["comments"]}, "Variants": {"number": t["variants"]},
                 "Stats updated": {"date": {"start": today}}}
        if status_of(rows[rid]) != "Published":
            props["Status"] = {"status": {"name": "Published"}}
        api(f"pages/{rid}", "PATCH", {"properties": props})
        bm = bookmark_for((rows[rid]["properties"].get("Source") or {}).get("url") or "", bookmarks, by_source)
        if bm:
            api(f"pages/{bm}", "PATCH", {"properties": {"Remake views": {"number": t["views"]}}})
        prev[rid] = t["views"]

    report.sort(key=lambda x: -x[0])
    lines = [f"{v:>7,}  (+{d:,})  {n}" for v, d, n, _ in report]
    print("\n".join(lines) or "no posted reels matched a Content row")
    unmatched = [g for g in groups if not assign.get(g)]
    if unmatched:
        print(f"{len(unmatched)} video(s) without a Content row (older than {NEW_ROW_WINDOW.days} days)")
    if dry:
        return 0
    state["views"] = prev
    state["stats_at"] = now.isoformat()
    save_state(state)
    if report:
        top = "\n".join(f"• <b>{v:,}</b> (+{d:,}) — {esc(n)}" for v, d, n, _ in report[:10])
        tell(f"📊 Просмотры за 3 дня — {len(report)} ролик(ов)\n{top}")
    return 0


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["drafts", "stats"])
    ap.add_argument("--backfill", action="store_true")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--days", type=int, default=60)
    a = ap.parse_args()
    load_env()
    if a.cmd == "drafts":
        return cmd_drafts(a.backfill, a.dry_run)
    return cmd_stats(a.force, a.dry_run, a.days)


if __name__ == "__main__":
    sys.exit(main())
