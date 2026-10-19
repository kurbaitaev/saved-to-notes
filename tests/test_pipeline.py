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
        "Idea": "Idea", "idea": "Idea", "thoughts": "Idea",
        "How to": "How-to", "how-to": "How-to", "tutorial": "How-to",
        "Prompt and Build": "Prompt & Build", "prompts": "Prompt & Build",
        "AI Tools": "Tool", "tooling": "Tool", "websites": "Tool",
        "reading list": "Read & Watch", "books": "Read & Watch",
        "investors": "Opportunity", "Fundraising": "Opportunity",
        "content": "Craft", "hooks": "Craft",
        "quotes": "Quote", "recipe": "Cook", "workout": "Move",
        "coffee place": "Visit", "meetup": "Attend", "gadget": "Buy",
    }
    for given, want in cases.items():
        assert folders.normalize(given) == want, f"{given} -> {folders.normalize(given)}"


def test_crossover_rules_are_in_the_prompt():
    """The crossover decisions are the point of the taxonomy (books are never
    Buy, a list is filed by what is in it, real life wins). If they drift out
    of the prompt the model falls back to filing by subject again."""
    prompt = bot._load_prompt()
    for phrase in ("Real life wins", "A list is not a category", "Books are"):
        assert phrase in folders.RULES and phrase in prompt, phrase
    assert set(folders.REAL_LIFE) | set(folders.KNOWLEDGE) == set(folders.FOLDERS)
    assert not set(folders.REAL_LIFE) & set(folders.KNOWLEDGE)


def test_area_is_derived_from_topics_and_covers_every_topic():
    """Area is computed, never chosen, so it can't contradict the topics — and
    a topic with no area would leave its notes ungrouped in Notion."""
    for t in topics.TOPICS:
        assert topics.area_of([t]), f"topic {t} has no area"
    assert topics.area_of(["investors-fundraising", "books-reading"]) == "Startup & Money"
    assert topics.area_of(["made-up"]) == "" and topics.area_of(None) == ""


def test_the_vault_note_records_category_and_area():
    text = _note_text({"title": "T", "folder": folders.TOOL, "topics": ["ai-tools"]},
                      "https://x.test/3", "words")
    assert "category: Tool" in text and "area: AI & Building" in text
    assert "categories:" not in text, "the retired label must not come back"


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
                  "steps", "slides", "tags", "description", "summary",
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
        {"title": "Both", "folder": folders.CRAFT,
         "slides": [{"text": "ON SCREEN WORDS", "description": "d"}]},
        "https://x.test/1", "SPOKEN WORDS")
    assert "SPOKEN WORDS" in text, "the transcript was dropped"
    assert "ON SCREEN WORDS" in text
    assert "## Transcript" in text and "## Slides" in text


def test_a_tweet_keeps_its_exact_wording():
    """X posts have no transcript — the text lives in the caption, which never
    reached the note. All 11 saved tweets had no verbatim text anywhere."""
    tweet = "The exact words of the post, which I may want to quote later."
    text = _note_text({"title": "T", "folder": folders.OPPORTUNITY},
                      "https://x.com/a/status/1", "",
                      {"platform": "twitter", "caption": tweet})
    assert tweet in text
    assert "## Post text" in text, "an X post's caption IS the post"


def test_a_caption_is_not_duplicated_when_it_equals_the_transcript():
    same = "identical text"
    text = _note_text({"title": "T", "folder": folders.IDEA},
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


# --- single active instance + retries that actually happen ---------------
# Oct 1-9: a laptop login reloaded a second bot, Telegram split every link
# between a working server and a laptop with a dead login, and the server's
# queued links waited 36 days for a restart that never came.

def test_queued_links_are_retried_without_a_restart(monkeypatch):
    import asyncio
    sent, processed = [], []

    class FakeBot:
        async def send_message(self, chat_id, text):
            sent.append(text)

    async def fake_process(bot_, chat_id, url, force, user_note=""):
        processed.append(url)

    pend = {"https://a/": {"chat_id": 1}, "https://busy/": {"chat_id": 1}}
    attempts = {}

    def fake_attempt(u):
        attempts[u] = attempts.get(u, 0) + 1
        return attempts[u]

    monkeypatch.setattr(bot.ledger, "pending_all", lambda: dict(pend))
    monkeypatch.setattr(bot.ledger, "pending_attempt", fake_attempt)
    monkeypatch.setattr(bot.ledger, "get", lambda u: None)
    monkeypatch.setattr(bot, "process", fake_process)
    monkeypatch.setattr(bot, "AUTH_FAILED_FLAG", pathlib.Path("/nonexistent/.auth_failed"))
    bot._in_flight.add("https://busy/")
    try:
        asyncio.run(bot._drain_pending(FakeBot()))
    finally:
        bot._in_flight.discard("https://busy/")
    assert processed == ["https://a/"]
    # a link being processed live must not burn one of its retry attempts
    assert "https://busy/" not in attempts


def test_auth_gate_reads_the_linux_login_file(monkeypatch):
    """It returned False on every non-Mac, so one transient auth failure on the
    server would have held every link forever."""
    import time as _t
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(bot.agent_openai, "enabled", lambda: False)
    live = {"expiresAt": (_t.time() + 3600) * 1000}
    monkeypatch.setattr(bot.claude_login, "oauth_blob", lambda: live)
    assert bot._auth_looks_ok()
    dead = {"expiresAt": 1, "refreshToken": "r", "refreshTokenExpiresAt": 1}
    monkeypatch.setattr(bot.claude_login, "oauth_blob", lambda: dead)
    assert not bot._auth_looks_ok()


def test_an_expired_refresh_token_cannot_refresh():
    import claude_login
    now = 1_700_000_000.0
    assert claude_login.can_refresh({"refreshToken": "r"}, now)
    assert claude_login.can_refresh({"refreshToken": "r", "refreshTokenExpiresAt": (now + 86400) * 1000}, now)
    assert not claude_login.can_refresh({"refreshToken": "r", "refreshTokenExpiresAt": (now - 1) * 1000}, now)
    assert round(claude_login.days_until_refresh_expiry({"refreshTokenExpiresAt": (now + 3 * 86400) * 1000}, now)) == 3


def test_a_reader_machine_never_starts_a_second_bot(monkeypatch):
    monkeypatch.setenv("RUN_BOT", "0")
    assert bot.bot_disabled_here()
    monkeypatch.setenv("RUN_BOT", "1")
    assert not bot.bot_disabled_here()
    tpl = (pathlib.Path(__file__).resolve().parent.parent / "launchd/bot.plist.template").read_text()
    assert "SuccessfulExit" in tpl, "a clean RUN_BOT=0 exit must not be respawned by launchd"


def test_no_personal_data_is_tracked_in_the_public_repo():
    """A blanket `git add -A` once committed a full vault backup and a ledger
    full of rendered notes to this public repo. Fail loudly if anything shaped
    like personal data is tracked again."""
    import subprocess
    root = pathlib.Path(__file__).resolve().parent.parent
    tracked = subprocess.run(["git", "ls-files"], cwd=root, capture_output=True, text=True).stdout.split("\n")
    bad = [f for f in tracked if f and (
        f.startswith(("vault/", "vault.")) or f.startswith("ledger.json") or
        (f.startswith("pending") and f.endswith(".json")) or ".backup" in f or f == ".env")]
    assert not bad, f"personal data tracked in the public repo: {bad[:5]}"


def test_a_setup_token_counts_as_a_login(monkeypatch):
    """The CLI honours CLAUDE_CODE_OAUTH_TOKEN ahead of the credentials file;
    every check that only reads the file would call a working bot logged out."""
    import datetime as _dt
    import claude_login
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "sk-ant-oat-test")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(bot.agent_openai, "enabled", lambda: False)
    monkeypatch.setattr(bot.claude_login, "oauth_blob", lambda: {})
    assert bot._auth_looks_ok()
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN_SET_AT", "2026-10-09")
    assert claude_login.token_days_left(_dt.date(2026, 10, 9)) == 365
    assert claude_login.token_days_left(_dt.date(2027, 9, 30)) == 9
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN_SET_AT", "garbage")
    assert claude_login.token_days_left() is None


# --- the Oct 17 reboot outage ---------------------------------------------
# A reboot emptied /tmp, the unit's ReadWritePaths pointed at /tmp/saved-to-notes,
# and the bot restart-looped on 226/NAMESPACE for 6.5 hours. The watchdog saw it
# five times but only ever said "restart FAILED", never why.

def test_the_bot_unit_starts_without_its_tmp_folder():
    unit = (pathlib.Path(__file__).resolve().parent.parent / "deploy" / "saved-to-notes.service").read_text()
    paths = [p for line in unit.splitlines() if line.startswith("ReadWritePaths=")
             for p in line.partition("=")[2].split()]
    assert paths, "the unit lost its ReadWritePaths line"
    for p in paths:
        if "/tmp" in p:
            assert p.startswith("-"), f"{p} must be optional: a reboot empties /tmp"


def test_a_failed_restart_alert_says_why(monkeypatch):
    import subprocess as _sp
    import watchdog
    journal = "\n".join([
        "saved-to-notes.service: Failed to set up mount namespacing: /tmp/saved-to-notes: No such file or directory",
        "saved-to-notes.service: Failed at step NAMESPACE spawning /home/m/.venv/bin/python: No such file or directory",
        "saved-to-notes.service: Main process exited, code=exited, status=226/NAMESPACE",
        "saved-to-notes.service: Failed with result 'exit-code'.",
    ])

    def fake_run(cmd, **_kw):
        out = "SubState=auto-restart\nNRestarts=121\n" if cmd[0] == "systemctl" else journal
        return _sp.CompletedProcess(cmd, 0, stdout=out, stderr="")

    monkeypatch.setattr(watchdog, "IS_MAC", False)
    monkeypatch.setattr(watchdog.subprocess, "run", fake_run)
    why = watchdog.service_failure()
    assert "auto-restart, 121 restarts" in why
    assert "namespacing: /tmp/saved-to-notes: No such file" in why  # the cause
    assert "python" not in why                  # not the misleading "Failed at step" line
    monkeypatch.setattr(watchdog, "IS_MAC", True)
    assert watchdog.service_failure() == ""


def test_ghost_detection_reads_full_command_lines_on_linux(monkeypatch):
    """procps' pgrep -l prints only "python" on Linux, so no ghost was ever found."""
    import subprocess as _sp
    import watchdog
    seen = {}

    def fake_run(cmd, **_kw):
        seen["cmd"] = cmd
        return _sp.CompletedProcess(cmd, 0, stdout="42 /venv/bin/python /gone/saved-to-notes/bot.py\n", stderr="")

    monkeypatch.setattr(watchdog, "IS_MAC", False)
    monkeypatch.setattr(watchdog.subprocess, "run", fake_run)
    assert watchdog.ghost_bot_paths() == ["/gone/saved-to-notes/bot.py"]
    assert "-fa" in seen["cmd"]


# --- real-life details (Afterscroll app) ---------------------------------

import details  # noqa: E402


def test_details_keep_only_what_the_category_uses():
    raw = {"name": "Sightglass", "kind": "Cafe", "city": "SF", "date": "2026-11-01",
           "moves": [{"name": "x"}], "ingredients": ["salt"], "minutes": "12"}
    assert details.clean(folders.VISIT, raw) == {"name": "Sightglass", "kind": "cafe", "city": "SF"}
    assert details.clean(folders.IDEA, raw) == {}, "knowledge notes carry no details"
    assert details.clean(folders.MOVE, raw) == {"name": "Sightglass", "minutes": 12,
                                                "moves": [{"name": "x"}]}


def test_details_reject_malformed_dates_urls_and_moves():
    d = details.clean(folders.ATTEND, {"name": "UFC", "date": "next Saturday", "time": "7pm",
                                       "url": "ufc.com/tickets"})
    assert d == {"name": "UFC"}, "the app parses date/time/url — junk must not reach it"
    m = details.clean(folders.MOVE, {"moves": ["Cat-cow", {"dose": "8"}, {"name": "Squat", "dose": "8 reps"}]})
    assert m["moves"] == [{"name": "Cat-cow"}, {"name": "Squat", "dose": "8 reps"}]
    assert details.clean(folders.VISIT, None) == {}


def test_details_json_always_fits_a_notion_cell_and_parses():
    import json
    big = {"name": "Stew", "ingredients": [f"{i} g of something long enough" for i in range(200)]}
    s = details.to_json(big)
    assert len(s) <= 2000
    assert json.loads(s)["name"] == "Stew"


def test_details_are_wired_into_prompt_schema_and_sanitize():
    assert details.RULES in bot._load_prompt()
    assert agent_openai.SCHEMA["properties"]["details"] is details.SCHEMA
    obj = bot._sanitize({"folder": "Visit", "details": {"name": "Tartine", "city": "SF"}})
    assert obj["details"] == {"name": "Tartine", "city": "SF"}
    assert bot._sanitize({"folder": "Idea", "details": {"name": "x"}})["details"] == {}


def test_shortcut_inbox_claims_each_row_once_and_skips_junk():
    """Rows are archived before they're returned, so a slow run can't be picked
    up again by the next minute's poll; a row without a usable link is still
    archived (otherwise it would be re-read forever) but not processed."""
    import os
    calls = []

    def fake_api(url, token, method="GET", body=None):
        calls.append((method, url, body))
        if url.endswith("/query"):
            return {"results": [
                {"id": "p1", "properties": {"Source": {"url": "https://instagram.com/reel/A/"},
                                            "Why": {"rich_text": [{"plain_text": "for Sunday"}]}}},
                {"id": "p2", "properties": {"Source": {"url": None}}}]}
        return {}

    saved = {k: os.environ.get(k) for k in ("NOTION_TOKEN", "NOTION_DATABASE_ID")}
    os.environ.update(NOTION_TOKEN="t", NOTION_DATABASE_ID="db")
    try:
        with patched(notion, "_api", fake_api), \
             patched(notion, "_db_props", lambda t, d: {"Queued": "checkbox"}):
            got = notion.inbox_take()
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    assert got == [("https://instagram.com/reel/A/", "for Sunday")]
    archived = [u for m, u, b in calls if m == "PATCH" and b == {"archived": True}]
    assert len(archived) == 2


# --- Afterscroll app store + API -----------------------------------------

import appdb  # noqa: E402
import clips  # noqa: E402


def _tmp_appdb(tmp):
    return [patched(appdb, "ROOT", tmp), patched(appdb, "DB", tmp / "app.db"),
            patched(appdb, "CLIPS", tmp / "clips"), patched(appdb, "INBOX", tmp / "inbox")]


def test_app_store_keeps_only_real_life_and_drops_refiled_saves(tmp_path):
    with contextlib.ExitStack() as st:
        for p in _tmp_appdb(tmp_path):
            st.enter_context(p)
        sid = appdb.upsert("https://x/1", "Move", "Hips", "Mr. Fine", "", {"minutes": 8})
        assert appdb.upsert("https://x/2", "Idea", "A thought") is None
        appdb.set_clips(sid, [{"name": "Whole reel", "file": f"{sid}/loop.mp4"},
                              {"name": "Pigeon", "file": f"{sid}/move1.mp4", "start": 3.3, "end": 5.6}])
        [s] = appdb.all_saves()
        assert s["category"] == "Move" and s["details"] == {"minutes": 8}
        assert s["loop"].split("?")[0].endswith("/loop.mp4") and [m["name"] for m in s["moves"]] == ["Pigeon"]
        # Re-filed out of a real-life category (the judo saves) → gone from the app.
        appdb.upsert("https://x/1", "How-to", "Hips")
        assert appdb.all_saves() == []


def test_app_inbox_is_claimed_once_and_skips_junk(tmp_path):
    with contextlib.ExitStack() as st:
        for p in _tmp_appdb(tmp_path):
            st.enter_context(p)
        appdb.enqueue("https://www.instagram.com/reel/A/", "for Sunday")
        appdb.enqueue("not a link")
        assert appdb.take_inbox() == [("https://www.instagram.com/reel/A/", "for Sunday")]
        assert appdb.take_inbox() == []


def test_move_cuts_are_validated_before_cutting():
    raw = [{"name": "Hip flexor", "start": 0.5, "end": 2.5},
           {"name": "Too short", "start": 3.0, "end": 3.2},
           {"name": "Pigeon", "start": 3.3, "end": 40},          # capped at 8 s
           {"name": "Overlaps", "start": 4.0, "end": 6.0},
           {"name": "", "start": 12, "end": 14},
           {"name": "Past the end", "start": 29, "end": 31}, "junk"]
    got = clips.validate(raw, total=27.9)
    assert [m["name"] for m in got] == ["Hip flexor", "Pigeon"]
    assert got[1]["end"] == 11.3


def test_api_requires_the_token_and_queues_shared_links(tmp_path):
    import http.client
    import os
    import threading
    from http.server import ThreadingHTTPServer

    import api
    with contextlib.ExitStack() as st:
        for p in _tmp_appdb(tmp_path):
            st.enter_context(p)
        os.environ["APP_TOKEN"] = "secret-test"
        srv = ThreadingHTTPServer(("127.0.0.1", 0), api.Handler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            def call(method, path, body=None, token="secret-test", headers=None):
                c = http.client.HTTPConnection("127.0.0.1", srv.server_port, timeout=5)
                h = {"Authorization": f"Bearer {token}", **(headers or {})}
                c.request(method, path, body=body, headers=h)
                r = c.getresponse()
                return r.status, r.read()
            assert call("GET", "/v1/health", token="")[0] == 200
            assert call("GET", "/v1/saves", token="wrong")[0] == 401
            code, _ = call("POST", "/v1/save", json.dumps({"url": "Look https://instagram.com/reel/B/ wow"}))
            assert code == 202 and appdb.take_inbox() == [("https://instagram.com/reel/B/", "")]
            assert call("POST", "/v1/save", json.dumps({"url": "no link"}))[0] == 400
            sid = "0123456789ab"
            (appdb.CLIPS / sid).mkdir(parents=True)
            (appdb.CLIPS / sid / "loop.mp4").write_bytes(b"0123456789")
            code, body = call("GET", f"/v1/clips/{sid}/loop.mp4", headers={"Range": "bytes=2-5"})
            assert code == 206 and body == b"2345", "AVPlayer streams with Range requests"
            assert call("GET", f"/v1/clips/{sid}/../app.db")[0] == 404
        finally:
            srv.shutdown()
            os.environ.pop("APP_TOKEN", None)


def test_api_falls_back_to_the_clipboard_and_survives_broken_json(tmp_path):
    """Instagram gives shortcuts an empty input; the shortcut then sends the
    clipboard, spliced raw into its JSON — quotes in a caption must not lose
    the link."""
    import http.client
    import os
    import threading
    from http.server import ThreadingHTTPServer

    import api
    with contextlib.ExitStack() as st:
        for p in _tmp_appdb(tmp_path):
            st.enter_context(p)
        os.environ["APP_TOKEN"] = "t"
        srv = ThreadingHTTPServer(("127.0.0.1", 0), api.Handler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            def post(body):
                c = http.client.HTTPConnection("127.0.0.1", srv.server_port, timeout=5)
                c.request("POST", "/v1/save", body=body.encode(), headers={"Authorization": "Bearer t"})
                return c.getresponse().status
            assert post('{"url": "", "clip": "https://www.instagram.com/reel/C/?igsh=x"}') == 202
            assert appdb.take_inbox()[0][0] == "https://www.instagram.com/reel/C/?igsh=x"
            assert post('{"url": "", "clip": "he said "wow"\nhttps://www.instagram.com/reel/D/"}') == 202
            assert appdb.take_inbox()[0][0] == "https://www.instagram.com/reel/D/"
            assert post('{"url": "", "clip": "nothing here"}') == 400
        finally:
            srv.shutdown()
            os.environ.pop("APP_TOKEN", None)


def test_links_shared_to_the_app_lean_real_life():
    """Sharing to Afterscroll is itself the signal: the first mobility reel sent
    that way was filed as an Explainer. The hint reaches both prompt paths;
    a Telegram save (no flag) gets none."""
    media = {"platform": "instagram", "kind": "video", "via_app": True}
    assert folders.APP_HINT in bot.build_prompt("https://x/1", media)
    assert folders.APP_HINT in bot._media_context("https://x/1", media)
    assert folders.APP_HINT not in bot.build_prompt("https://x/1", {"platform": "instagram"})
    assert folders.MOVE in folders.APP_HINT


def test_recut_clips_get_new_urls_and_shares_report_where_they_went(tmp_path):
    """A re-cut workout must not reuse the old URLs (the phone caches by URL and
    kept showing the previous cut), and a share that became a Notion note must
    say so instead of vanishing."""
    with contextlib.ExitStack() as st:
        for p in _tmp_appdb(tmp_path):
            st.enter_context(p)
        sid = appdb.upsert("https://x/9", "Move", "Hips")
        appdb.set_clips(sid, [{"name": "Whole reel", "file": f"{sid}/loop.mp4"}])
        first = appdb.all_saves()[0]["loop"]
        assert first.endswith("?v=" + first.split("?v=")[1]) and appdb.all_saves()[0]["poster"].split("?")[0].endswith("loop.jpg")
        with patched(appdb.time, "time", lambda: 9_999_999_999.0):
            appdb.set_clips(sid, [{"name": "Whole reel", "file": f"{sid}/loop.mp4"}])
        assert appdb.all_saves()[0]["loop"] != first
        appdb.share_started("https://x/tip")
        appdb.share_done("https://x/tip", "notion", "Explainer", "Why hips matter")
        [r] = appdb.recent_shares(hours=24 * 365 * 400)
        assert (r["status"], r["category"], r["title"]) == ("notion", "Explainer", "Why hips matter")


def test_move_hints_reach_gemini_prompt():
    assert "{moves}" in clips._HINT and "Use exactly these names" in clips._HINT


def test_moves_come_from_shots_one_exercise_each():
    """igor.system's reels cut to a new shot per exercise; a clip must cover
    exactly one shot (it showed 2-3 exercises when Gemini guessed timestamps).
    Same-named neighbours merge, talking-head shots drop, edges are trimmed."""
    spans = [(0.0, 1.9), (1.9, 3.8), (3.8, 5.6), (5.6, 7.3), (7.3, 9.2)]
    names = ["none", "Pigeon", "Pigeon", "Deep squat", "Frog"]
    got = clips.moves_from_shots(spans, names)
    assert [m["name"] for m in got] == ["Pigeon", "Deep squat", "Frog"]
    assert got[0]["start"] == 2.0 and got[0]["end"] == 5.5, "two Pigeon shots merge"
    assert all(a["end"] <= b["start"] for a, b in zip(got, got[1:], strict=False)), "clips never overlap"
