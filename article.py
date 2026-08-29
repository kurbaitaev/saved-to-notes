#!/usr/bin/env python3
"""Articles, newsletters and blog posts — the half of a bookmark folder that
had no path through this tool at all.

Until now anything without a video failed: the acquirers all start by
downloading media, and a Substack post has none. But a large share of what
anyone saves on X is a link out to an essay, so "turn your saves into notes"
was only ever half true.

Two extractors, in order:

1. **Trafilatura** — a heuristic HTML-to-text pipeline, no browser, no model,
   no network beyond fetching the page. It posts an F1 of 0.945 on the
   ScrapingHub article-extraction benchmark, ahead of readability. This is the
   default because it costs nothing and leaks nothing.
2. **Jina Reader** (`r.jina.ai`) — a hosted renderer, free and keyless. It runs
   a real browser, so it gets JavaScript-rendered pages that Trafilatura sees as
   empty. Used only when Trafilatura comes back thin.

Note the tradeoff in that order: Trafilatura fetches the URL from this machine,
Jina fetches it from theirs. Falling back to Jina tells a third party which
page was saved. That is why it is second rather than first.
"""

import json
import logging
import os
import re
import urllib.parse
import urllib.request

from errors import AcquireError

log = logging.getLogger("saved-to-notes.article")

# Anything below this is a cookie wall, a paywall stub or a failed render
# rather than a real article, and is worth retrying with the other extractor.
MIN_CHARS = 600
# ...but if BOTH extractors come back thin, a genuinely short post is still
# worth keeping. Below this floor it is not a short article, it is a consent
# banner or an error page, and turning it into a note is worse than failing.
FLOOR_CHARS = 200
# The whole text is kept in the note (that is the point — the article outlives
# the link), but a runaway page shouldn't blow up the vault or Notion.
MAX_CHARS = 60000

_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/128.0 Safari/537.36")

# Hosts that already have a real acquirer. Everything else is treated as a page
# of text. Listed explicitly rather than inferred, so a new social platform
# fails loudly instead of being silently scraped as an article.
MEDIA_HOSTS = (
    "instagram.com", "x.com", "twitter.com", "tiktok.com", "youtube.com",
    "youtu.be", "threads.com", "threads.net", "facebook.com", "fb.watch",
    "vimeo.com", "twitch.tv", "reddit.com", "linkedin.com", "soundcloud.com",
    "spotify.com", "podcasts.apple.com", "dailymotion.com", "rumble.com",
)


def _host(url: str) -> str:
    try:
        return urllib.parse.urlsplit(url).netloc.lower().split(":")[0]
    except ValueError:
        return ""


def is_article(url: str) -> bool:
    """True when no media acquirer claims this URL, so it's a page to read.

    Deliberately permissive: a link that is neither a known media host nor an
    obvious binary is assumed to be readable text. Being wrong here costs one
    failed extraction; being too strict costs the whole feature.
    """
    try:
        parts = urllib.parse.urlsplit(url)
    except ValueError:
        return False
    if parts.scheme not in ("http", "https") or not parts.netloc:
        return False
    host = _host(url)
    if any(host == h or host.endswith("." + h) for h in MEDIA_HOSTS):
        return False
    # A direct file link is not an article. PDFs are excluded on purpose:
    # extracting them is a different job, and a half-read PDF is worse than
    # an honest failure.
    return not re.search(r"\.(pdf|mp4|mp3|zip|dmg|pkg|jpg|jpeg|png|gif|webp)$",
                         parts.path, re.I)


# A line that is nothing but a link, a heading marker wrapping a link, or
# punctuation: site navigation, cookie footers, "Skip to content", share bars.
_CHROME_LINE = re.compile(r"^\s*[#*>\-\s]*(?:\[[^\]]*\]\([^)]*\)|[\W_])*\s*$")


def _strip_chrome(text: str) -> str:
    """Drop navigation and footer lines that carry no prose.

    Jina renders the whole page, so its output starts with 'Skip to content',
    a search link and a sign-in link. Left in, they become the first thing the
    note quotes.
    """
    return "\n".join(ln for ln in text.splitlines() if not _CHROME_LINE.match(ln))


def _prose_len(text: str) -> int:
    """Length of the actual writing, ignoring link scaffolding.

    This is what MIN_CHARS and FLOOR_CHARS are measured against. A paywalled
    Substack post returns ~538 characters of copyright footer and privacy
    links — over any raw-length floor, and worth nothing as a note.
    """
    stripped = _strip_chrome(text)
    stripped = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", stripped)  # keep link text
    return len(re.sub(r"\s+", " ", stripped).strip())


def _clean(text: str) -> str:
    """Collapse the blank-line spam that both extractors leave behind."""
    text = _strip_chrome(text or "")
    text = re.sub(r"\n{3,}", "\n\n", text.strip())
    return text[:MAX_CHARS]


def _via_trafilatura(url: str) -> dict:
    import trafilatura  # optional dependency — caller handles ImportError

    html = trafilatura.fetch_url(url)
    if not html:
        return {}
    opts = dict(include_comments=False, include_tables=True, favor_precision=True)
    # Markdown for the body, JSON for the metadata — two passes over HTML already
    # in memory, no second network call. The body has to be markdown: the JSON
    # form's `raw_text` returns the whole article with every paragraph break
    # stripped (19,345 characters and zero newlines on a real essay), and its
    # `text` still drops headings and list structure.
    text = trafilatura.extract(html, output_format="markdown",
                               with_metadata=False, **opts) or ""
    meta_raw = trafilatura.extract(html, output_format="json",
                                   with_metadata=True, **opts)
    d = json.loads(meta_raw) if meta_raw else {}
    return {
        "text": _clean(text),
        "title": (d.get("title") or "").strip(),
        "author": (d.get("author") or "").strip(),
        "date": (d.get("date") or "").strip(),
        "language": (d.get("language") or "").strip(),
        "sitename": (d.get("sitename") or d.get("hostname") or "").strip(),
        "extractor": "trafilatura",
    }


_JINA_TITLE = re.compile(r"^Title:\s*(.+)$", re.M)
_JINA_BODY = re.compile(r"^Markdown Content:\s*$", re.M)


def _via_jina(url: str) -> dict:
    """r.jina.ai renders the page and returns markdown. Free and keyless;
    JINA_API_KEY only raises the rate limit, so it stays optional."""
    # Do NOT send a browser User-Agent here. r.jina.ai answers browser-looking
    # agents with 403 — it wants to be called as an API, not rendered. Copying
    # the Chrome UA used for media CDNs broke every fallback until this was
    # measured: identical URL, plain agent 200, Chrome agent 403.
    headers = {"User-Agent": "saved-to-notes/1.0", "Accept": "text/plain"}
    key = os.environ.get("JINA_API_KEY", "").strip()
    if key:
        headers["Authorization"] = f"Bearer {key}"
    req = urllib.request.Request("https://r.jina.ai/" + url, headers=headers)
    with urllib.request.urlopen(req, timeout=60) as r:
        body = r.read().decode("utf-8", "replace")

    title = ""
    m = _JINA_TITLE.search(body)
    if m:
        title = m.group(1).strip()
    # Everything before "Markdown Content:" is Jina's own header block.
    b = _JINA_BODY.search(body)
    text = body[b.end():] if b else body
    # Inline image placeholders ("![Image 3: caption](url)") are noise in a note.
    text = re.sub(r"!\[Image \d+[^\]]*\]\([^)]*\)", "", text)
    return {
        "text": _clean(text),
        "title": title,
        "author": "",
        "date": "",
        "sitename": _host(url),
        "extractor": "jina",
    }


def fetch(url: str) -> dict:
    """Return the article as a dict, or {} if neither extractor got real text.

    Never raises for a page-level problem: a paywall, a cookie wall or a dead
    link all come back as {} so the caller can report it plainly. Only a
    programming error should escape.
    """
    warnings = []
    best: dict = {}

    for name, fn in (("trafilatura", _via_trafilatura), ("jina", _via_jina)):
        try:
            got = fn(url)
        except ImportError:
            warnings.append("trafilatura is not installed (pip install trafilatura)")
            continue
        except Exception as e:  # noqa: BLE001 — any extractor failure is just a miss
            log.warning("%s failed for %s: %s", name, url, e)
            warnings.append(f"{name} could not read the page ({type(e).__name__})")
            continue
        prose = _prose_len(got.get("text", "")) if got else 0
        if prose >= MIN_CHARS:
            got["warnings"] = warnings
            return got
        # Keep the thin result: if the other extractor also comes back thin,
        # a short-but-real article still beats returning nothing.
        if got and prose > _prose_len(best.get("text", "")):
            best = got
        warnings.append(
            f"{name} found only {prose} characters of text" if got
            else f"{name} could not fetch the page (blocked, or not HTML)")

    if _prose_len(best.get("text", "")) >= FLOOR_CHARS:
        best["warnings"] = warnings + [
            "The page extracted thin — it may be paywalled or mostly images. "
            "The note is built from what was readable."]
        return best
    return {"warnings": warnings}


def acquire(url: str) -> dict:
    """Article path in the same shape every other acquirer returns.

    The body goes in `transcript` on purpose. That is the field the vault note
    and the Notion sync already preserve verbatim, so an article saved here
    survives the original going behind a paywall — which is most of the reason
    to save an article at all.
    """
    got = fetch(url)
    text = got.get("text", "")
    if not text:
        why = "; ".join(got.get("warnings") or []) or "no readable text found"
        raise AcquireError(
            f"Couldn't read this page as an article ({why}). Paywalls, cookie "
            "walls and JavaScript-only pages are the usual causes.")

    return {
        "source_url": url,
        "platform": got.get("sitename") or _host(url),
        "kind": "article",
        "caption": "",
        "author": got.get("author") or "",
        "title": got.get("title") or _host(url),
        "transcript": text,
        "published": got.get("date") or "",
        "detected_language": got.get("language") or None,
        "video_path": None,
        "images": [],
        "frames": [],
        "warnings": got.get("warnings") or [],
    }
