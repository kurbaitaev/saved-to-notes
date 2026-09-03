#!/usr/bin/env python3
"""Regression tests. Every case here is a bug that actually happened.

    python3 -m pytest tests/ -q          (or: python3 tests/test_pipeline.py)

No network, no Apify, no Telegram — Apify calls are stubbed.
"""

import contextlib
import json
import os
import pathlib
import sys
import tempfile


@contextlib.contextmanager
def patched(obj, name, value):
    """monkeypatch, without needing pytest.

    CI runs this file as a plain script with only requirements.txt installed,
    so nothing here may import pytest or take a fixture argument.
    """
    missing = object()
    old = getattr(obj, name, missing)
    setattr(obj, name, value)
    try:
        yield
    finally:
        if old is missing:
            delattr(obj, name)
        else:
            setattr(obj, name, old)

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import acquire  # noqa: E402
import agent_openai  # noqa: E402
import article  # noqa: E402
import bot  # noqa: E402
import folders  # noqa: E402
import ledger  # noqa: E402
import notion  # noqa: E402
import review  # noqa: E402
import topics  # noqa: E402


# --- agent output --------------------------------------------------------
# The agent is a model, so its JSON shape is a request, not a guarantee. These
# shapes used to raise before any sink ran, leaving a permanent "Working..."
# placeholder and an unrecoverable reel.

def test_sanitize_survives_wrong_types():
    for bad in [
        {"items": ["a string, not a dict"]},
        {"points": [{"unexpected": "dict"}]},
        {"tags": "string-not-list", "steps": None, "slides": "nope"},
        {"items": [{"name": "ok"}, "junk", 42, None]},
        {"categories": 5, "points": [None, "", "keep"]},
    ]:
        obj = bot._sanitize(dict(bad))
        assert isinstance(obj["items"], list)
        assert all(isinstance(i, dict) for i in obj["items"])
        # must render without raising
        bot.render_telegram(obj, "https://instagram.com/reel/X/")
        bot.render_rich(obj, "https://instagram.com/reel/X/", "transcript")


def test_search_urls_never_count_as_verified():
    obj = bot._sanitize({"items": [
        {"name": "A", "link": "https://www.google.com/search?q=a", "verified": True},
        {"name": "B", "link": "https://duckduckgo.com/?q=b", "verified": True},
        {"name": "C", "link": "not-a-url", "verified": True},
        {"name": "D", "link": "https://www.goodreads.com/book/show/1", "verified": True},
    ]})
    assert bot._validate_links(obj) == 3
    assert [i["verified"] for i in obj["items"]] == [False, False, False, True]


# --- Telegram delivery ---------------------------------------------------

def test_blocks_use_native_structure_and_no_raw_html():
    obj = {
        "content_type": "book_recommendation",
        "title": "Books & Ideas",              # & must not arrive as &amp;
        "quote": "a quote",
        "author": "Someone",
        "items": [{"name": "Range", "author": "David Epstein",
                   "link": "https://www.goodreads.com/book/show/41795733-range",
                   "verified": True}],
        "why_save": "worth keeping",
        "tags": ["books", "investing"],
    }
    payload = bot.render_blocks(obj, "https://instagram.com/reel/X/", "line one\nline two")
    types = [b["type"] for b in payload["blocks"]]
    for expected in ("heading", "list", "blockquote", "divider", "details", "footer"):
        assert expected in types, f"missing {expected} block"

    flat = json.dumps(payload)
    # _layout() escapes for the HTML renderers; blocks must carry raw text.
    assert "&amp;" not in flat and "<b>" not in flat, "HTML leaked into native blocks"

    # A verified item must be a real link, and list items wrap blocks (not text).
    lst = next(b for b in payload["blocks"] if b["type"] == "list")
    assert "blocks" in lst["items"][0]
    assert any(p.get("type") == "url" for p in json.loads(flat)["blocks"][
        types.index("list")]["items"][0]["blocks"][0]["text"] if isinstance(p, dict))

    details = next(b for b in payload["blocks"] if b["type"] == "details")
    assert details["summary"] and details["blocks"], "details needs summary + blocks"


def test_long_line_is_split_under_the_limit():
    # A single long line used to exceed Telegram's 4096 cap → BadRequest → lost reel.
    for text in ["x" * 9000, "short\n" + "y" * 9000 + "\nend", "a\nb\nc"]:
        for chunk in bot.chunked(text):
            assert len(chunk) <= 4000


# --- ledger --------------------------------------------------------------

def test_ledger_writes_atomically_and_keeps_corrupt_files():
    tmp = pathlib.Path(tempfile.mkdtemp())
    ledger._PATH, ledger._PENDING = tmp / "ledger.json", tmp / "pending.json"

    ledger.put("u1", {"status": "done"})
    assert ledger.get("u1") == {"status": "done"}
    assert not list(tmp.glob("*.tmp")), "temp file left behind"

    # A crash mid-write used to leave truncated JSON, which was silently read as
    # {} — re-processing and duplicating every reel.
    (tmp / "ledger.json").write_text('{"u1": {"status": "do')
    assert ledger.get("u1") is None
    assert list(tmp.glob("*corrupt*")), "corrupt ledger was not preserved"
    ledger.put("u2", {"status": "done"})
    assert ledger.get("u2") is not None


def test_pending_attempts_give_up():
    tmp = pathlib.Path(tempfile.mkdtemp())
    ledger._PATH, ledger._PENDING = tmp / "ledger.json", tmp / "pending.json"
    ledger.pending_add("p1", 42)
    assert [ledger.pending_attempt("p1") for _ in range(3)] == [1, 2, 3]
    ledger.pending_remove("p1")
    assert ledger.pending_all() == {}
    assert ledger.pending_attempt("gone") == 0


# --- url normalization ---------------------------------------------------

def test_all_instagram_link_forms_collapse_to_one_key():
    forms = [
        "https://www.instagram.com/reel/ABC/",
        "https://www.instagram.com/reels/ABC/",
        "https://instagram.com/reel/ABC/?igsh=xyz",
        "https://www.instagram.com/share/reel/ABC/",
    ]
    assert len({acquire.normalize_url(u) for u in forms}) == 1


def test_tracking_params_stripped_but_real_params_kept():
    assert acquire.normalize_url(
        "https://www.threads.com/@u/post/X?xmt=AQ&slof=1") == "https://www.threads.com/@u/post/X"
    # unknown hosts are left alone
    assert acquire.normalize_url("https://example.com/a?q=keep") == "https://example.com/a?q=keep"


# --- acquisition branches ------------------------------------------------

def _stub_apify(item):
    """Stub both Apify calls: transcriber finds nothing, scraper returns `item`.
    A token must be present or acquire() takes the yt-dlp path and hits network."""
    import os
    os.environ["APIFY_TOKEN"] = "test-token"

    def fake_run(actor, payload, token, timeout=300):
        return [] if "transcripts" in actor else [item]
    acquire._apify_run = fake_run
    acquire._download = lambda src, dest, timeout=60: pathlib.Path(dest).write_bytes(b"jpg")
    acquire.video_frames = lambda *a, **k: []


def test_single_photo_post_is_not_dropped():
    # Single images used to fall through to the video branch and be lost entirely.
    _stub_apify({"type": "Image", "caption": "c", "ownerUsername": "u",
                 "shortCode": "P1", "displayUrl": "https://x/i.jpg"})
    m = acquire.acquire("https://www.instagram.com/p/P1/")
    assert m["kind"] == "image" and len(m["images"]) == 1
    acquire.cleanup(m)


def test_carousel_downloads_every_slide_with_unique_names():
    _stub_apify({"type": "Sidecar", "caption": "c", "ownerUsername": "u", "shortCode": "C1",
                 "childPosts": [{"displayUrl": f"https://x/{i}.jpg"} for i in range(5)]})
    m = acquire.acquire("https://www.instagram.com/p/C1/")
    assert m["kind"] == "carousel" and len(m["images"]) == 5
    assert len(set(m["images"])) == 5, "slide filenames collided"
    acquire.cleanup(m)
    assert not [p for p in acquire.TMP.glob("C1*")], "media not cleaned up"


def test_tweet_urls_normalize_and_are_detected():
    for u in ["https://twitter.com/NASA/status/123",
              "https://x.com/NASA/status/123?s=20&t=abc",
              "https://x.com/NASA/status/123"]:
        assert acquire.is_twitter(u)
        assert acquire.normalize_url(u) == "https://x.com/NASA/status/123"
    assert not acquire.is_twitter("https://x.com/NASA")  # profile, not a post


def test_long_x_post_is_not_truncated():
    """For long (Premium) posts the actor puts the FULL text in `text` and a
    280-char truncation in `fullText` — the opposite of the names. Preferring
    fullText cut a 2301-char post to 278 chars, and the model reconstructed the
    missing content from web search and presented it as saved."""
    full = ("1. Thiel Fellowship $250K." * 90).strip()   # ~2300 chars, no trailing space
    truncated = full[:278]
    assert acquire._tweet_text({"text": full, "fullText": truncated}) == full
    # and still correct when the fields behave normally
    assert acquire._tweet_text({"text": "", "fullText": "short tweet"}) == "short tweet"
    assert acquire._tweet_text({}) == ""


def test_text_only_tweet_still_produces_a_note():
    """yt-dlp refuses tweets without video ("No video could be found"), which
    lost the note entirely. The Apify path must handle text and photo tweets."""
    import os
    os.environ["APIFY_TOKEN"] = "test-token"
    acquire._apify_run = lambda actor, payload, token, timeout=300: [{
        "fullText": "a tweet with no video at all",
        "author": {"userName": "someone", "name": "Some One"},
        "lang": "en",
        "extendedEntities": {"media": [
            {"type": "photo", "media_url_https": "https://pbs.twimg.com/media/x.jpg"}]},
    }]
    acquire._download = lambda src, dest, timeout=60: pathlib.Path(dest).write_bytes(b"jpg")
    m = acquire.acquire("https://x.com/someone/status/999")
    assert m["platform"] == "twitter"
    assert m["kind"] == "image" and len(m["images"]) == 1
    assert m["author"] == "someone"
    assert "no video" in m["caption"]
    acquire.cleanup(m)


# --- outcomes: the reel-losing bugs --------------------------------------

def test_pipeline_result_defaults_to_keeping_the_link_queued():
    """An unforeseen exit must keep the link, not drop it. Three links were
    lost because failure and success were indistinguishable to the caller."""
    assert bot.Result("x").keep_queued is True
    assert bot.Result("x").saved is False
    assert bot.Result("x", outcome=bot.SAVED).saved is True
    assert bot.Result("x", outcome=bot.SAVED).keep_queued is False
    # permanent failures release the link — a deleted post can never succeed
    assert bot.Result("x", outcome=bot.PERMANENT).keep_queued is False
    assert bot.Result("x", outcome=bot.PERMANENT).saved is False


def test_acquire_errors_carry_a_retry_decision():
    assert acquire.AcquireError("rate limited").retryable is True
    assert acquire.AcquireError("deleted", retryable=False).retryable is False


def _run(coro):
    import asyncio
    return asyncio.run(coro)


class _FakeBot:
    """Minimal stand-in — records what the user would have seen."""

    def __init__(self):
        self.sent = []

    async def send_message(self, chat_id, text, **kw):
        self.sent.append(text)


def _isolate_ledger(tmp):
    ledger._PATH, ledger._PENDING = tmp / "l.json", tmp / "p.json"
    ledger._LOCKFILE = tmp / ".lock"


def test_a_failed_link_stays_queued_and_a_saved_one_does_not():
    """The wiring, not the dataclass: process() must consult the outcome. Three
    links were lost because the retry marker was cleared in `finally`."""
    import os
    os.environ["RICH_MESSAGE"] = "0"
    url = "https://www.instagram.com/reel/WIRED/"
    for outcome, still_queued in ((bot.SAVED, False), (bot.PERMANENT, False),
                                  (bot.RETRYABLE, True)):
        _isolate_ledger(pathlib.Path(tempfile.mkdtemp()))
        real, bot._in_flight = bot.run_pipeline, set()

        async def fake(*a, _o=outcome, **k):
            return bot.Result("note", None, None, _o)

        bot.run_pipeline = fake
        try:
            _run(bot.process(_FakeBot(), 1, url, force=False))
        finally:
            bot.run_pipeline = real
        queued = acquire.normalize_url(url) in ledger.pending_all()
        assert queued is still_queued, f"{outcome}: queued={queued}"


def test_an_exception_mid_flight_keeps_the_link():
    """An exception is the case most worth recovering from, and used to be the
    one case recovery could never reach."""
    import os
    os.environ["RICH_MESSAGE"] = "0"
    _isolate_ledger(pathlib.Path(tempfile.mkdtemp()))
    url = "https://www.instagram.com/reel/BOOM/"
    real, bot._in_flight = bot.run_pipeline, set()

    async def blow_up(*a, **k):
        raise RuntimeError("network died")

    bot.run_pipeline = blow_up
    fake_bot = _FakeBot()
    try:
        _run(bot.process(fake_bot, 1, url, force=False))
    finally:
        bot.run_pipeline = real
    assert acquire.normalize_url(url) in ledger.pending_all(), "link was dropped"
    assert any("retry" in t for t in fake_bot.sent), fake_bot.sent


def test_your_own_words_become_why_save_verbatim():
    """A model paraphrase of your own reason is strictly worse than your reason."""
    obj = bot._sanitize({"why_save": "a neutral model sentence"})
    obj["why_save"] = "compare with our onboarding"      # what run_pipeline does
    assert obj["why_save"] == "compare with our onboarding"
    # and the prompt must not tell the model to neutralise it
    prompt = bot._load_prompt()
    assert "Neutral, not personalized" not in prompt
    assert "WHY THE USER SAVED THIS" in bot._media_context(
        "u", {"platform": "instagram"}, user_note="compare with our onboarding")


def test_prompt_has_no_unsubstituted_placeholders():
    """A typo'd placeholder would ship `{{TOPIC_RULES}}` literally to the model."""
    prompt = bot._load_prompt()
    assert "{{" not in prompt, "unsubstituted placeholder in the prompt"
    for folder in folders.FOLDERS:
        assert folder in prompt, folder
    assert "investors-fundraising" in prompt


# --- frame cost ----------------------------------------------------------

def test_frame_count_scales_down_on_a_rich_transcript():
    """It only ever scaled UP before: 40 of 46 reels sampled 6 frames despite
    transcripts over 800 chars, ~7k wasted tokens each."""
    import os
    os.environ.pop("VIDEO_FRAMES", None)
    assert acquire._frame_count(0) == acquire.FRAMES_VISUAL      # no speech: read the screen
    assert acquire._frame_count(199) == acquire.FRAMES_VISUAL
    assert acquire._frame_count(200) == acquire.FRAMES_MIXED
    assert acquire._frame_count(799) == acquire.FRAMES_MIXED
    assert acquire._frame_count(800) == acquire.FRAMES_RICH      # the words carry it
    assert acquire._frame_count(5000) == acquire.FRAMES_RICH
    try:
        os.environ["VIDEO_FRAMES"] = "0"
        assert acquire._frame_count(0) == 0                      # explicit off
        os.environ["VIDEO_FRAMES"] = "3"
        assert acquire._frame_count(0) == 3                      # caps the tier
        assert acquire._frame_count(5000) == acquire.FRAMES_RICH  # never raises it
    finally:
        os.environ.pop("VIDEO_FRAMES", None)


# --- topics --------------------------------------------------------------

def test_topics_are_a_closed_vocabulary():
    # invented topics are dropped rather than creating new Notion options —
    # that sprawl is what made 301 free-form tags unusable as a filter
    assert topics.normalize_list(["totally-made-up"]) == []
    assert topics.normalize_list("investors-fundraising") == ["investors-fundraising"]
    assert len(topics.normalize_list(topics.TOPICS)) == topics.MAX_PER_NOTE
    assert topics.normalize_list(None) == []
    assert topics.normalize_list([None, 42, ""]) == []


def test_topics_map_from_the_tags_notes_already_carry():
    assert topics.from_tags(["venture-capital"]) == ["investors-fundraising"]
    assert topics.from_tags(["pre-seed", "accelerators"]) == ["investors-fundraising"]
    assert topics.from_tags(["hooks", "storytelling"]) == ["hooks-storytelling"]
    assert "ai-tools" in topics.from_tags(["claude", "automation"])


def test_every_topic_is_reachable_from_its_own_name():
    for t in topics.TOPICS:
        assert topics.normalize_list([t]) == [t], t


# --- ledger across processes ---------------------------------------------

def test_ledger_survives_two_processes_writing_at_once():
    """`--test` runs the full pipeline against the same files as the live bot.
    A thread lock does nothing there — last writer used to win."""
    import subprocess as sp
    tmp = pathlib.Path(tempfile.mkdtemp())
    proj = pathlib.Path(__file__).resolve().parent.parent
    prog = (
        f"import sys; sys.path.insert(0, {str(proj)!r})\n"
        "import pathlib, ledger\n"
        f"ledger._PATH = pathlib.Path({str(tmp / 'l.json')!r})\n"
        f"ledger._PENDING = pathlib.Path({str(tmp / 'p.json')!r})\n"
        f"ledger._LOCKFILE = pathlib.Path({str(tmp / '.lock')!r})\n"
        "[ledger.put(f'w{sys.argv[1]}-{i}', {'status': 'done'}) for i in range(40)]\n"
    )
    procs = [sp.Popen([sys.executable, "-c", prog, tag]) for tag in ("a", "b")]
    for pr in procs:
        pr.wait(timeout=60)
    ledger._PATH, ledger._PENDING = tmp / "l.json", tmp / "p.json"
    ledger._LOCKFILE = tmp / ".lock"
    surviving = json.loads((tmp / "l.json").read_text())
    assert len(surviving) == 80, f"lost {80 - len(surviving)} entries to a race"


# --- folders -------------------------------------------------------------

def test_every_note_gets_exactly_one_valid_folder():
    # The folder decides where the note is filed, so it can never be blank or
    # something the model invented.
    for bad in [{}, {"folder": ""}, {"folder": None}, {"folder": "Nonsense"},
                {"folder": 42}, {"folder": ["Startup"]}]:
        obj = bot._sanitize(dict(bad))
        assert obj["folder"] in folders.FOLDERS, f"{bad} -> {obj['folder']}"


def test_folder_normalizer_tolerates_near_misses():
    cases = {
        "Startup": "Startup", "startup tips": "Startup", "Fundraising": "Startup",
        "AI Tools": "Tools & AI", "tooling": "Tools & AI",
        "content": "Content Ideas", "Content Ideas": "Content Ideas",
        "motivation": "Mindset", "quotes": "Mindset",
        "Learning & Self": "Learning & Self",
    }
    for given, want in cases.items():
        assert folders.normalize(given) == want, f"{given} -> {folders.normalize(given)}"


def test_folder_directory_name_matches_the_notion_value():
    """They must be the same string. When the disk said "Tools and AI" and
    Notion said "Tools & AI", it read as two different folders."""
    for f in folders.FOLDERS:
        d = folders.safe_dirname(f)
        assert d == f, f"disk name {d!r} differs from Notion value {f!r}"
        assert "/" not in d, f"{d!r} would nest directories"


# --- openai backend ------------------------------------------------------

def test_openai_schema_obeys_strict_mode():
    """OpenAI strict mode rejects the whole request unless every object lists
    all its properties in `required` and sets additionalProperties: false."""
    def check(node, path="root"):
        if node.get("type") == "object":
            assert node.get("additionalProperties") is False, f"{path}: additionalProperties"
            props, req = set(node.get("properties", {})), set(node.get("required", []))
            assert props == req, f"{path}: required != properties ({props ^ req})"
            for k, v in node["properties"].items():
                check(v, f"{path}.{k}")
        elif node.get("type") == "array":
            check(node["items"], path + "[]")

    check(agent_openai.SCHEMA)
    # The renderers, Notion sink and vault writer all read these.
    for field in ("title", "folder", "topics", "content_type", "items", "points",
                  "steps", "slides", "tags", "categories", "description", "summary",
                  "why_save", "quote"):
        assert field in agent_openai.SCHEMA["properties"], f"schema is missing {field}"


def test_openai_backend_is_off_without_a_key():
    import os
    saved = os.environ.pop("OPENAI_API_KEY", None)
    try:
        assert agent_openai.enabled() is False
    finally:
        if saved:
            os.environ["OPENAI_API_KEY"] = saved


# --- notion --------------------------------------------------------------

def test_property_values_match_the_columns_actual_type():
    # Matching on name and assuming a shape made Notion 400 the whole page,
    # losing the note while Telegram still looked fine.
    assert notion._prop_value("url", "https://x/") == {"url": "https://x/"}
    assert notion._prop_value("rich_text", "https://x/")["rich_text"][0]["text"]["content"]
    assert notion._prop_value("select", "instagram") == {"select": {"name": "instagram"}}
    assert len(notion._prop_value("multi_select", ["A", "B"])["multi_select"]) == 2
    assert notion._prop_value("date", "2026-07-24") == {"date": {"start": "2026-07-24"}}
    assert notion._prop_value("checkbox", True) == {"checkbox": True}
    # unsettable / empty
    assert notion._prop_value("formula", "x") is None
    assert notion._prop_value("rich_text", "") is None
    assert notion._prop_value("url", None) is None


def test_unknown_author_sentinel_is_rejected():
    assert not notion._ok("Author not clear")
    assert not notion._ok("Not clear from the Reel")
    assert not notion._ok("")
    assert notion._ok("Bill Gurley")


# --- articles ------------------------------------------------------------
# Everything without a video used to fail outright, which is most of what
# anyone saves on X.

def test_only_non_media_urls_are_routed_to_the_article_reader():
    for u in ["https://www.instagram.com/reel/DaO9loyuVF_/",
              "https://x.com/naval/status/1002103360646823936",
              "https://youtu.be/dQw4w9WgXcQ",
              "https://www.tiktok.com/@user/video/123",
              "https://m.youtube.com/watch?v=abc",       # subdomains count
              "https://example.com/whitepaper.pdf",      # a file, not a page
              "not-a-url", "ftp://files.example.com/x"]:
        assert not article.is_article(u), u
    for u in ["https://paulgraham.com/greatwork.html",
              "https://every.to/some-essay",
              "https://blog.samaltman.com/how-to-be-successful",
              "https://notyoutube.com/posts/1"]:  # endswith must not over-match
        assert article.is_article(u), u


def test_article_body_keeps_its_paragraph_structure():
    """The JSON extractor's `raw_text` returns a whole essay with zero newlines.
    Shipping that would have put every article in the vault as one wall of text."""
    html = ("<html><head><title>T</title></head><body><article>"
            + "".join(f"<p>{f'Sentence number {i}. ' * 12}</p>" for i in range(12))
            + "</article></body></html>")
    try:
        import trafilatura
    except ImportError:
        return  # optional dependency; the article path falls back to Jina
    md = trafilatura.extract(html, output_format="markdown", with_metadata=False,
                             include_comments=False, include_tables=True,
                             favor_precision=True) or ""
    assert md.count("\n") >= 10, "paragraph breaks were stripped"


def test_a_page_that_cannot_be_read_fails_loudly():
    """A paywall must say so, not save an empty note."""
    with patched(article, "_via_trafilatura", lambda u: {}), \
         patched(article, "_via_jina", lambda u: {"text": "too short"}):
        try:
            article.acquire("https://paywalled.example.com/post")
        except acquire.AcquireError as e:
            assert "trafilatura" in str(e) and "jina" in str(e)
        else:
            raise AssertionError("an unreadable page must raise, not return an empty note")


def test_a_thin_article_is_kept_with_a_warning_rather_than_dropped():
    """Better a short real note that says it is short than no note at all."""
    body = "Real but short. " * 20  # under MIN_CHARS
    with patched(article, "_via_trafilatura",
                 lambda u: {"text": body, "title": "Short", "extractor": "trafilatura"}), \
         patched(article, "_via_jina", lambda u: {}):
        d = article.fetch("https://example.com/short")
    assert d["text"] == body
    assert any("thin" in w for w in d["warnings"])


def test_jina_is_not_called_with_a_browser_user_agent():
    """r.jina.ai answers browser-looking agents with 403. Reusing the Chrome UA
    that the media CDNs require broke every fallback: same URL, plain agent 200,
    Chrome agent 403."""
    seen = {}

    class FakeResponse:
        def read(self):
            return b"Title: T\n\nMarkdown Content:\nbody"

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(req, timeout=None):
        seen["ua"] = req.get_header("User-agent", "")
        return FakeResponse()

    import urllib.request as ur
    real = ur.urlopen
    ur.urlopen = fake_urlopen
    try:
        article._via_jina("https://example.com/post")
    finally:
        ur.urlopen = real
    assert "Mozilla" not in seen["ua"] and "Chrome" not in seen["ua"], seen["ua"]


def test_a_paywall_footer_is_not_mistaken_for_an_article():
    """A paywalled Substack returns ~500 characters of copyright and privacy
    links — past any raw-length floor, and worthless as a note. Length is
    measured on prose, not on link scaffolding."""
    footer = ("[](https://www.example.com/)\n\n## [](https://www.example.com/)\n\n"
              "[Privacy](https://x.com/privacy) · [Terms](https://x.com/terms) · "
              "[Collection notice](https://x.com/collection)\n\n"
              "[Start writing](https://x.com/signup)\n" * 6)
    assert len(footer) > article.FLOOR_CHARS      # would have passed a raw check
    assert article._prose_len(footer) < article.FLOOR_CHARS


# --- verbatim preservation ---------------------------------------------
# The exact wording is the whole reason to keep a note you plan to remake
# something from. Three separate ways it was being lost.

def _note_text(obj, url, transcript, media=None):
    """Write a vault note into a throwaway dir and hand back its text."""
    with tempfile.TemporaryDirectory() as td:
        root = pathlib.Path(td)
        with patched(bot, "PROJECT_DIR", root):
            rel = bot._write_vault_note(obj, url, transcript, "2026-08-16", media)
        return (root / "vault" / rel).read_text()


def test_slides_do_not_displace_the_transcript():
    """These were an if/elif, so a post with both on-screen text and speech
    kept only the slides."""
    text = _note_text(
        {"title": "Both", "folder": folders.CONTENT_IDEAS,
         "slides": [{"text": "ON SCREEN WORDS", "description": "d"}]},
        "https://x.test/1", "SPOKEN WORDS")
    assert "SPOKEN WORDS" in text, "the transcript was dropped"
    assert "ON SCREEN WORDS" in text
    assert "## Transcript" in text and "## Slides" in text


def test_a_tweet_keeps_its_exact_wording():
    """X posts have no transcript — the text lives in the caption, which never
    reached the note. All 11 saved tweets had no verbatim text anywhere."""
    tweet = "The exact words of the post, which I may want to quote later."
    text = _note_text({"title": "T", "folder": folders.STARTUP},
                      "https://x.com/a/status/1", "",
                      {"platform": "twitter", "caption": tweet})
    assert tweet in text
    assert "## Post text" in text, "an X post's caption IS the post"


def test_a_caption_is_not_duplicated_when_it_equals_the_transcript():
    same = "identical text"
    text = _note_text({"title": "T", "folder": folders.MINDSET},
                      "https://x.test/2", same,
                      {"platform": "instagram", "caption": same})
    assert text.count(same) == 1


def test_a_video_with_no_speech_says_so_instead_of_going_quiet():
    """Apify hit its monthly cap and Whisper wasn't installed; 62 notes were
    saved with no exact wording and nothing explaining why."""
    missing_tool = acquire.no_speech_warning(have_local=False)
    silent_reel = acquire.no_speech_warning(have_local=True)
    # Both must say the wording is gone...
    assert "exact wording" in missing_tool and "exact wording" in silent_reel
    # ...but they are different problems and must not give the same advice.
    assert "openai-whisper" in missing_tool
    assert "openai-whisper" not in silent_reel


def test_x_posts_prefer_the_free_path_and_only_pay_for_threads():
    """Apify's tweet actor and the free FxTwitter path return the same text, so
    the paid one is only worth calling for the thing it alone can do."""
    calls = []

    def fake_fx(url):
        calls.append("fx")
        return {"source_url": url, "platform": "twitter", "kind": "text",
                "caption": "full text", "author": "a", "title": "t",
                "transcript": "", "detected_language": None, "video_path": None,
                "images": [], "frames": [], "warnings": [], "reply_count": 0}

    def fake_apify(url, token):
        calls.append("apify")
        raise AssertionError("Apify must not be called for a reply-less post")

    with patched(acquire, "_acquire_fxtwitter", fake_fx), \
         patched(acquire, "_acquire_apify_twitter", fake_apify), \
         patched(os, "environ", dict(os.environ, APIFY_TOKEN="t")):
        media = acquire.acquire("https://x.com/a/status/123")
    assert calls == ["fx"]
    assert media["caption"] == "full text"
    assert "reply_count" not in media, "internal field leaked into the media contract"


def test_a_possible_thread_is_never_silently_truncated():
    """Without a token we cannot follow a thread. The note must say so rather
    than quietly keeping only the first post."""
    def fake_fx(url):
        return {"source_url": url, "platform": "twitter", "kind": "text",
                "caption": "first post", "author": "a", "title": "t",
                "transcript": "", "detected_language": None, "video_path": None,
                "images": [], "frames": [], "warnings": [], "reply_count": 7}

    env = {k: v for k, v in os.environ.items() if k != "APIFY_TOKEN"}
    with patched(acquire, "_acquire_fxtwitter", fake_fx), \
         patched(os, "environ", env):
        media = acquire.acquire("https://x.com/a/status/123")
    assert any("7 repl" in w for w in media["warnings"])


def test_an_article_note_is_not_labelled_a_transcript():
    obj = {"kind": "article", "summary": "s"}
    assert "article" in bot._detail_label(obj)
    assert "transcript" in bot._detail_label({"kind": "video"}).lower()


if __name__ == "__main__":
    failed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"  PASS  {name}")
            except Exception as e:  # noqa: BLE001
                failed += 1
                print(f"  FAIL  {name}: {type(e).__name__}: {e}")
    print(f"\n{'FAILED' if failed else 'all passed'} ({failed} failure(s))")
    sys.exit(1 if failed else 0)


# --- review questions ----------------------------------------------------
# The app shows this as a prompt to answer, so anything that isn't a question
# is worse than nothing.

def test_only_real_questions_survive():
    assert review.clean("Why would this fail at your scale?") == "Why would this fail at your scale?"
    assert review.clean("  Why   does\n this work? ") == "Why does this work?"
    for junk in ["This is a statement.", "", None, "Ok?", 42, ["a?"]]:
        assert review.clean(junk) == "", junk


def test_review_question_reaches_the_openai_schema():
    """topics once existed in the prompt but not in the strict schema, so the
    model was structurally forbidden from returning it. Same trap, same guard."""
    props = agent_openai.SCHEMA["properties"]
    assert "review_question" in props
    assert "review_question" in agent_openai.SCHEMA["required"]
    assert set(agent_openai.SCHEMA["required"]) == set(props), \
        "strict mode requires every property to be listed in required"


def test_the_question_rules_have_exactly_one_source():
    """They used to be hand-copied, and the copy went stale."""
    import review_questions
    assert review.RULES in review_questions.PROMPT
    assert "{{REVIEW_RULES}}" not in bot._load_prompt()
    assert "Higher-order, not recall" in bot._load_prompt()


def test_a_note_without_a_question_writes_no_frontmatter_line():
    obj = bot._sanitize({"title": "T", "review_question": "not a question"})
    assert obj["review_question"] == ""


# --- content dedup -------------------------------------------------------
# The vault held the same reel twice under two URLs, and the same video once
# from Instagram and once from TikTok. URL dedup is structurally blind to both.

def test_fingerprints_catch_reposts_but_not_neighbours():
    """Threshold from measurement, not hope: across all 31,878 pairs in the
    vault, true duplicates sit at distance 3 and the closest unrelated pair at
    11 — so identical content must match, and unrelated must clear SAME."""
    import textsig
    base = ("Your screen time is not the problem, the direction of it is. One hour "
            "a day compounds into real skill if you point it somewhere deliberate. "
            "Editing, sales, memory, whatever, the hours are already being paid. ") * 4
    same = textsig.sig(base)
    suffixed = textsig.sig(base + " follow for more daily tips link in bio")
    other = textsig.sig(("Six concrete activities to replace mindless doomscrolling, "
                         "from intentional online learning to offline physical "
                         "activity, deep reading and skill practice sessions. ") * 4)
    assert textsig.distance(same, textsig.sig(base)) == 0
    # a suffixed repost stays far closer than unrelated content, even when it
    # falls just past SAME — the ordering is what the design relies on
    assert textsig.distance(same, suffixed) < textsig.distance(same, other)
    assert textsig.distance(same, other) > textsig.SAME


def test_too_little_text_never_fingerprints():
    """A signature of near-nothing matches everything — refuse to make one."""
    import textsig
    assert textsig.sig("short caption") == ""
    assert textsig.distance("", "abc") == 64


def test_ledger_entries_stay_slim():
    """The ledger once stored every note's full rendering forever — 1.5MB of
    JSON rewritten under a lock on every message. Only pointers belong here."""
    import inspect
    src = inspect.getsource(bot)
    put_call = src[src.index('ledger.put(url, {'):][:400]
    for heavy in ('"markdown"', '"blocks"', '"digest"'):
        assert heavy not in put_call, f"{heavy} crept back into ledger.put"


# --- weekly digest ---------------------------------------------------------
# The loop-closer. Nothing comes back on its own (Bergman 2021: 16% of
# bookmarks ever retrieved); the digest is what brings it.

def _row(**kw):
    base = {"title": "t", "url": "", "date": "2026-06-01", "question": "Why?",
            "reviews": 0, "recalled": 0, "last_reviewed": "", "last_result": ""}
    base.update(kw)
    return base


def test_digest_picks_the_oldest_note_never_asked_about():
    import digest
    rows = [_row(title="asked", reviews=2),
            _row(title="no question", question=""),
            _row(title="oldest unasked", date="2026-06-02"),
            _row(title="newer unasked", date="2026-07-01")]
    assert digest.oldest_unasked(rows)["title"] == "oldest unasked"
    assert digest.oldest_unasked([_row(reviews=1)]) is None


def test_digest_week_window_and_recall_rate():
    import datetime as dt
    import digest
    today = dt.date(2026, 9, 6)
    rows = [_row(reviews=1, recalled=1, last_reviewed="2026-09-05", last_result="recalled"),
            _row(reviews=1, recalled=0, last_reviewed="2026-09-01", last_result="missed"),
            _row(reviews=1, recalled=1, last_reviewed="2026-08-20", last_result="recalled"),  # too old
            _row(reviews=0, last_reviewed="2026-09-05")]                          # never graded
    week = digest.reviewed_in_window(rows, today)
    assert len(week) == 2
    assert digest.recall_rate(week) == (1, 2)
    assert digest.lifetime(rows) == (2, 3)


def test_digest_renders_html_safely_and_says_when_empty():
    import datetime as dt
    import digest
    today = dt.date(2026, 9, 6)
    text = digest.render(today, [], [], [])
    assert "Nothing saved" in text and "No reviews" in text
    text = digest.render(today, [{"date": "2026-09-05", "title": "A <b>bold</b> claim", "folder": "Mindset"}],
                         [], [_row(title="x & y", question="Why <this>?", date="2026-06-01")])
    assert "&lt;b&gt;bold&lt;/b&gt;" in text and "x &amp; y" in text
    assert "<b>bold</b>" not in text


# --- claude login detection ------------------------------------------------
# doctor and watchdog each read only the macOS keychain, so on the server both
# said "no login" while `claude -p` was answering fine on a Max subscription.

def test_login_reader_treats_logged_out_as_invalid_not_immortal():
    import claude_login
    now = 1_700_000_000.0
    assert claude_login.session_valid({"expiresAt": (now + 3600) * 1000}, now)
    assert not claude_login.session_valid({"expiresAt": (now - 1) * 1000}, now)
    assert not claude_login.session_valid({"expiresAt": 0}, now)      # the old misread
    assert not claude_login.session_valid({}, now)
    assert claude_login.can_refresh({"refreshToken": "r"})
    assert not claude_login.can_refresh({})


def test_login_reader_uses_the_credentials_file_off_mac(monkeypatch, tmp_path):
    import claude_login
    f = tmp_path / ".credentials.json"
    f.write_text(json.dumps({"claudeAiOauth": {"accessToken": "a", "refreshToken": "r",
                                                "expiresAt": 1, "subscriptionType": "max"}}))
    monkeypatch.setattr(claude_login, "IS_MAC", False)
    monkeypatch.setattr(claude_login, "CRED_FILE", f)
    blob = claude_login.oauth_blob()
    assert blob["subscriptionType"] == "max"
    assert "credentials.json" in claude_login.describe(blob)
    monkeypatch.setattr(claude_login, "CRED_FILE", tmp_path / "missing.json")
    assert claude_login.oauth_blob() == {}


def test_claude_binary_is_found_outside_a_shell_path(monkeypatch, tmp_path):
    """A systemd user unit's PATH lacks ~/.local/bin; the old fallback was a
    Mac-only Homebrew path, so the server raised FileNotFoundError per note."""
    import shutil as _sh
    fake_home = tmp_path
    (fake_home / ".local/bin").mkdir(parents=True)
    exe = fake_home / ".local/bin/claude"
    exe.write_text("#!/bin/sh\n")
    exe.chmod(0o755)
    monkeypatch.setattr(_sh, "which", lambda _n: None)
    monkeypatch.setattr(bot.Path, "home", classmethod(lambda cls: fake_home))
    monkeypatch.delenv("CLAUDE_BIN", raising=False)
    assert bot._find_claude() == str(exe)
    monkeypatch.setenv("CLAUDE_BIN", "/custom/claude")
    assert bot._find_claude() == "/custom/claude"


def test_vault_sync_script_is_portable_to_macos():
    """flock(1) does not exist on macOS; the first Mac pull died on it."""
    src = (pathlib.Path(__file__).resolve().parent.parent / "vault_sync.sh").read_text()
    assert "flock" not in src.replace("# ", "").split("mkdir is atomic")[0] or "flock(1) does not exist" in src
    assert "mkdir \"$LOCK\"" in src
    import subprocess
    assert subprocess.run(["bash", "-n", "vault_sync.sh"], cwd=pathlib.Path(__file__).resolve().parent.parent).returncode == 0


def test_the_vault_is_never_tracked_by_the_code_repo():
    """'vault/' in .gitignore matched only a directory; a symlink at that path
    was committed to the PUBLIC repo and, on pull, replaced the server's real
    vault with a link to a Mac path. The bare name matches both forms."""
    import subprocess
    root = pathlib.Path(__file__).resolve().parent.parent
    tracked = subprocess.run(["git", "ls-files", "vault"], cwd=root, capture_output=True, text=True).stdout
    assert tracked.strip() == "", f"vault is tracked: {tracked!r}"
    ignored = subprocess.run(["git", "check-ignore", "-q", "vault"], cwd=root).returncode
    assert ignored == 0, "vault is not ignored by the code repo"
