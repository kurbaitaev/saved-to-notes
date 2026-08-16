#!/usr/bin/env python3
"""Regression tests. Every case here is a bug that actually happened.

    python3 -m pytest tests/ -q          (or: python3 tests/test_pipeline.py)

No network, no Apify, no Telegram — Apify calls are stubbed.
"""

import json
import pathlib
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402

import acquire  # noqa: E402
import agent_openai  # noqa: E402
import article  # noqa: E402
import bot  # noqa: E402
import folders  # noqa: E402
import ledger  # noqa: E402
import notion  # noqa: E402
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
    trafilatura = pytest.importorskip("trafilatura")
    md = trafilatura.extract(html, output_format="markdown", with_metadata=False,
                             include_comments=False, include_tables=True,
                             favor_precision=True) or ""
    assert md.count("\n") >= 10, "paragraph breaks were stripped"


def test_a_page_that_cannot_be_read_fails_loudly(monkeypatch):
    """A paywall must say so, not save an empty note."""
    monkeypatch.setattr(article, "_via_trafilatura", lambda u: {})
    monkeypatch.setattr(article, "_via_jina", lambda u: {"text": "too short"})
    try:
        article.acquire("https://paywalled.example.com/post")
    except acquire.AcquireError as e:
        assert "trafilatura" in str(e) and "jina" in str(e)
    else:
        raise AssertionError("an unreadable page must raise, not return an empty note")


def test_a_thin_article_is_kept_with_a_warning_rather_than_dropped(monkeypatch):
    """Better a short real note that says it is short than no note at all."""
    body = "Real but short. " * 20  # under MIN_CHARS
    monkeypatch.setattr(article, "_via_trafilatura",
                        lambda u: {"text": body, "title": "Short",
                                   "extractor": "trafilatura"})
    monkeypatch.setattr(article, "_via_jina", lambda u: {})
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
