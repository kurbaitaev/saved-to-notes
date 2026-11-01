"""Cards: one next step per save (cards.py), its API and its Telegram side.

Runs under pytest or on its own: `python tests/test_cards.py`.
"""

import asyncio
import contextlib
import datetime as dt
import json
import pathlib
import sys
import tempfile
import threading
import time
import urllib.request
from http.server import ThreadingHTTPServer
from types import SimpleNamespace

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import api  # noqa: E402
import appdb  # noqa: E402
import cards  # noqa: E402
import tgcards  # noqa: E402

CONFIG = {
    "remake_topic": "content",
    "topics": [
        {"id": "content", "name": "Content", "emoji": "🎬", "projects": ["content", "editing"],
         "aliases": ["reels", "editing"]},
        {"id": "gameplan", "name": "Gameplan", "projects": ["gameplan"], "aliases": ["gameplan site"]},
        {"id": "lak", "name": "Lak", "projects": ["lak"], "aliases": ["lak"]},
    ],
    "destinations": [
        {"id": "music", "name": "ghost-editor › music", "topic": "content",
         "keywords": ["music", "музык"]},
    ],
}
TODAY = dt.date.today().isoformat()


def _setup(tmp: pathlib.Path, monkeypatch=None) -> None:
    appdb.ROOT, appdb.DB = tmp, tmp / "app.db"
    (tmp / "cards.json").write_text(json.dumps(CONFIG))
    cards.os.environ["ALLOWED_USER_IDS"] = "42"


def _item(n: int, project: str = "content", date: str = TODAY, **kw) -> dict:
    return {"url": f"https://www.instagram.com/reel/R{n}/", "title": f"Save {n}", "category": "Craft",
            "date": date, "project": project, "fit": 0.8, "asset": "tactic",
            "application": f"Use idea {n} in your next reel", "steps": ["Copy it", "Film it"]} | kw


def test_a_save_becomes_one_card_in_its_project_topic(tmp_path):
    _setup(tmp_path)
    assert cards.propose(_item(1, project="editing"))       # editing lives in Content
    assert cards.propose(_item(1, project="editing")) is None  # one card per save
    assert cards.propose(_item(2, category="Move")) is None  # real life lives in the app
    assert cards.propose(_item(3, project="hisense")) is None  # no topic, stays in Notion
    old = (dt.date.today() - dt.timedelta(days=20)).isoformat()
    assert cards.propose(_item(4, date=old)) is None         # old saves are reference now
    (c,) = cards.listing(status="queued")
    assert (c["topic"], c["kind"], c["status"]) == ("content", "step", "queued")


def test_your_note_and_a_library_decide_where_a_card_goes(tmp_path):
    _setup(tmp_path)
    url = _item(5)["url"]
    cards.remember_note(url, "for the gameplan site")
    c = cards.get(cards.propose(_item(5)))
    assert c["topic"] == "gameplan" and c["my_note"] == "for the gameplan site"
    add = cards.get(cards.propose(_item(6, project="gameplan", asset="list",
                                        title="Background Music for Short Form")))
    assert (add["kind"], add["destination"], add["topic"]) == ("add", "music", "content")
    videos = cards.get(cards.propose(_item(7, asset="list", title="7 Videos to Master Editing",
                                          application="Add the music cues from these videos")))
    assert videos["kind"] == "step"  # a step that mentions music doesn't make a music library


def test_three_open_cards_per_topic_newest_save_first(tmp_path):
    _setup(tmp_path)
    for n, days in enumerate([5, 1, 3, 2, 0]):
        cards.propose(_item(n, date=(dt.date.today() - dt.timedelta(days=days)).isoformat()))
    due = cards.due()
    assert [c["title"] for c in due] == ["Save 4", "Save 1", "Save 3"]
    for i, c in enumerate(due):
        cards.opened(c["id"], 7, 100 + i)
    assert cards.due() == []
    cards.act(due[0]["id"], "done")
    assert [c["title"] for c in cards.due()] == ["Save 2"]


def test_ignored_cards_expire_and_the_rate_counts_only_real_actions(tmp_path):
    _setup(tmp_path)
    a, b = (cards.propose(_item(n)) for n in (1, 2))
    cards.opened(a, None, 1)
    cards.opened(b, None, 2)
    cards.act(a, "remade")
    later = time.time() + 15 * 86400
    gone = cards.expire(now=later)
    assert [g["id"] for g in gone] == [b]
    st = cards.stats(now=later)
    assert (st["matured"], st["acted_in_14d"], st["rate"]) == (2, 1, 0.5)


def test_a_card_moves_when_you_say_it_belongs_elsewhere(tmp_path):
    _setup(tmp_path)
    cid = cards.propose(_item(1))
    cards.opened(cid, 7, 11)
    assert cards.topic_named_in("no, this is for Lak") == "lak"
    assert cards.topic_named_in("a lake trip") is None
    c = cards.move(cid, "lak")
    assert (c["topic"], c["status"], c["message_id"]) == ("lak", "queued", None)
    assert [e["action"] for e in cards.events()] == ["proposed", "sent", "moved"]


def test_the_api_takes_matches_and_actions(tmp_path):
    _setup(tmp_path)
    cards.os.environ["APP_TOKEN"] = "t"
    srv = ThreadingHTTPServer(("127.0.0.1", 0), api.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"

    def call(path, body=None):
        req = urllib.request.Request(base + path, data=json.dumps(body).encode() if body else None,
                                     headers={"Authorization": "Bearer t"})
        with urllib.request.urlopen(req) as r:
            return json.load(r)
    try:
        made = call("/v1/cards/propose", {"items": [_item(1), _item(2, category="Cook")]})["created"]
        assert len(made) == 1
        assert call("/v1/cards?status=queued")["cards"][0]["id"] == made[0]
        cards.opened(made[0], None, 9)
        assert call(f"/v1/cards/{made[0]}", {"action": "done", "via": "claude"})["status"] == "done"
        assert call("/v1/cards/events?actions=done")["events"][0]["text"] == "via claude"
    finally:
        srv.shutdown()


class _Calls:
    def __init__(self):
        self.made = []

    async def __call__(self, method, params):
        self.made.append((method, params))
        if method == "getMe":
            return {"ok": True, "result": {"has_topics_enabled": True}}
        if method == "createForumTopic":
            return {"ok": True, "result": {"message_thread_id": 77}}
        if method == "getForumTopicIconStickers":
            return {"ok": True, "result": [{"emoji": "🎬", "custom_emoji_id": "icon-film"}]}
        return {"ok": True, "result": {"message_id": 500 + len(self.made)}}


def test_telegram_sends_into_a_topic_and_a_tap_closes_the_card(tmp_path):
    _setup(tmp_path)
    calls = _Calls()
    tgcards.call, tgcards._topics_on = calls, None
    tgcards.notion.set_checkbox = lambda url, prop, value=True: prop == "Worth remaking"
    cid = cards.propose(_item(1))
    assert asyncio.run(tgcards.pump()) == 1
    sent = [p for m, p in calls.made if m == "sendMessage"][0]
    assert sent["message_thread_id"] == 77
    assert [b["text"] for b in sent["reply_markup"]["inline_keyboard"][0]] == ["🎬 Remake", "✅ Done",
                                                                               "Not now"]
    answered = []

    async def answer(text=None):
        answered.append(text)
    q = SimpleNamespace(data=f"c|{cid}|r", answer=answer)
    upd = SimpleNamespace(callback_query=q, effective_user=SimpleNamespace(id=42))
    asyncio.run(tgcards.on_callback(upd, None))
    assert cards.get(cid)["status"] == "remade" and answered == ["🎬 Remake"]
    edit = [p for m, p in calls.made if m == "editMessageText"][-1]
    assert "reply_markup" not in edit and "Content Ideas" in edit["text"]


def test_cards_wait_while_topics_are_off(tmp_path):
    _setup(tmp_path)
    calls = _Calls()

    async def off(method, params):
        return {"ok": True, "result": {"has_topics_enabled": False}} if method == "getMe" else await calls(method, params)
    tgcards.call, tgcards._topics_on = off, None
    cid = cards.propose(_item(1))
    assert asyncio.run(tgcards.pump()) == 0
    assert cards.get(cid)["status"] == "queued" and not calls.made


def test_a_topic_has_one_icon_and_no_emoji_in_its_name(tmp_path):
    _setup(tmp_path)
    calls = _Calls()
    tgcards.call, tgcards._topics_on, tgcards._icons = calls, None, None
    asyncio.run(tgcards.thread_for("content"))
    asyncio.run(tgcards.thread_for("lak"))  # no emoji in its config: Telegram draws its own
    content, lak = [p for m, p in calls.made if m == "createForumTopic"]
    assert content["name"] == "Content" and content["icon_custom_emoji_id"] == "icon-film"
    assert lak["name"] == "Lak" and "icon_custom_emoji_id" not in lak


def test_saturdays_line_adds_what_youre_studying_and_one_idea(tmp_path):
    _setup(tmp_path)
    calls = _Calls()
    tgcards.call = calls

    class Saturday(tgcards.dt.datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 11, 7, 19, 0)
    real, tgcards.dt.datetime = tgcards.dt.datetime, Saturday
    asked = []

    async def fake_ce(path, body=None):
        asked.append(path)
        return {"learn": {"title": "A <book>", "source": "https://x.com/a", "after_this": 2},
                "think": {"title": "An idea", "why": "It changes how you see it", "source": ""}}
    real_ce, tgcards.ce = tgcards.ce, fake_ce
    try:
        asyncio.run(tgcards.saturday())
        asyncio.run(tgcards.saturday())     # once a week
    finally:
        tgcards.dt.datetime, tgcards.ce = real, real_ce
    sent = [p for m, p in calls.made if m == "sendMessage"]
    assert len(sent) == 1 and asked == ["/api/picks"]
    text = sent[0]["text"]
    assert '📚 <b>Learning now:</b> <a href="https://x.com/a">A &lt;book&gt;</a>' in text
    assert "<b>An idea</b>" in text and "It changes how you see it" in text
    assert sent[0]["reply_markup"] == tgcards.LEARN_BUTTON


def test_saturdays_line_still_goes_out_when_the_engine_is_down(tmp_path):
    _setup(tmp_path)
    calls = _Calls()
    tgcards.call = calls

    class Saturday(tgcards.dt.datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 11, 14, 19, 0)
    real, tgcards.dt.datetime = tgcards.dt.datetime, Saturday

    def down(path, body=None):
        raise OSError("connection refused")
    real_call, tgcards._ce_call = tgcards._ce_call, down
    try:
        asyncio.run(tgcards.saturday())
    finally:
        tgcards.dt.datetime, tgcards._ce_call = real, real_call
    sent = [p for m, p in calls.made if m == "sendMessage"][0]
    assert "Nothing finished" in sent["text"] and "reply_markup" not in sent


def test_finishing_what_youre_studying_brings_the_next_one(tmp_path):
    _setup(tmp_path)
    calls = _Calls()
    tgcards.call = calls
    answered = []

    async def answer(text=None):
        answered.append(text)

    async def fake_ce(path, body=None):
        assert path == "/api/learn/done"
        return {"finished": "One", "next": {"title": "Two", "source": ""}}
    real_ce, tgcards.ce = tgcards.ce, fake_ce
    q = SimpleNamespace(answer=answer, message=SimpleNamespace(chat_id=42, message_id=9))
    upd = SimpleNamespace(callback_query=q, effective_user=SimpleNamespace(id=42))
    try:
        asyncio.run(tgcards.on_learn(upd, None))
    finally:
        tgcards.ce = real_ce
    assert answered == ["Finished"]
    assert any(m == "editMessageReplyMarkup" for m, _ in calls.made)
    sent = [p for m, p in calls.made if m == "sendMessage"][0]
    assert "<b>Two</b>" in sent["text"] and sent["reply_markup"] == tgcards.LEARN_BUTTON


def test_a_reply_naming_another_project_moves_the_card(tmp_path):
    _setup(tmp_path)
    calls = _Calls()
    tgcards.call, tgcards._topics_on = calls, None
    cid = cards.propose(_item(1))
    asyncio.run(tgcards.pump())
    replies = []

    async def reply_text(text):
        replies.append(text)
    msg = SimpleNamespace(text="this is for Lak", message_thread_id=77, reply_to_message=None,
                          reply_text=reply_text)
    assert asyncio.run(tgcards.on_text(SimpleNamespace(message=msg), None))
    c = cards.get(cid)
    assert c["topic"] == "lak" and c["status"] == "open"  # moved and sent again
    assert any(m == "createForumTopic" and p["name"] == "Lak" for m, p in calls.made)


def test_your_note_is_written_into_the_vault_note_apart_from_the_model(tmp_path):
    import bot
    import folders
    old = bot.PROJECT_DIR
    bot.PROJECT_DIR = tmp_path
    try:
        rel = bot._write_vault_note({"title": "Fonts", "folder": folders.CRAFT, "why_save": "for subs",
                                     "my_note": 'for "subs" on reels'},
                                    "https://x.com/a/status/1", "", "2026-11-01", {})
    finally:
        bot.PROJECT_DIR = old
    head = (tmp_path / "vault" / rel).read_text().split("\n---", 1)[0]
    assert 'my_note: "for \\"subs\\" on reels"' in head  # JSON-quoted, so YAML-safe



def _shortcut_body(note: str, shared: str, clip: str) -> str:
    """The body the generated shortcut sends: its text template with each slot
    filled the way Shortcuts fills it, the note run through its Replace Text
    steps (NSRegularExpression, translated to Python's re)."""
    import re

    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "tools"))
    import make_shortcut

    acts = [(a["WFWorkflowActionIdentifier"].rsplit(".", 1)[-1], a["WFWorkflowActionParameters"])
            for a in make_shortcut.build("https://example.test", "t")["WFWorkflowActions"]]
    out = {p["UUID"]: clip for kind, p in acts if kind == "getclipboard"}
    out |= {p["UUID"]: note for kind, p in acts if kind == "ask"}
    for kind, p in acts:
        if kind == "replace":
            find = p["WFReplaceTextFind"].replace(r"\p{Cc}", r"\x00-\x1f\x7f-\x9f")
            find = f"[{find[:-1]}]+" if find.endswith("+") and not find.startswith("[") else find
            tmpl = p["WFReplaceTextReplace"]

            def fill(m, tmpl=tmpl):  # template: "\x" is a literal x, "$n" is group n
                return re.sub(r"\\(.)|\$(\d)", lambda t: t.group(1) or m.group(int(t.group(2))), tmpl)
            out[p["UUID"]] = re.sub(find, fill, out[p["WFInput"]["Value"]["OutputUUID"]])
    [text] = [p["WFTextActionText"]["Value"] for kind, p in acts if kind == "gettext"]
    units = text["string"].encode("utf-16-le")
    spots = sorted(((int(k.strip("{}").split(",")[0]), v) for k, v in text["attachmentsByRange"].items()),
                   reverse=True)
    for at, v in spots:  # right to left, so earlier offsets stay put
        val = shared if v["Type"] == "ExtensionInput" else out[v["OutputUUID"]]
        units = units[:at * 2] + val.encode("utf-16-le") + units[at * 2 + 2:]
    return units.decode("utf-16-le")


def test_a_note_from_the_phone_reaches_the_bot_as_your_words(tmp_path):
    """The share button sends {"url", "note"}; the shortcut asks for the note and
    splices it, escaped, into a text body. Both arrive as the note, verbatim."""
    _setup(tmp_path)
    old_inbox, appdb.INBOX = appdb.INBOX, tmp_path / "inbox"
    cards.os.environ["APP_TOKEN"] = "t"
    srv = ThreadingHTTPServer(("127.0.0.1", 0), api.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    def post(body: str) -> int:
        req = urllib.request.Request(f"http://127.0.0.1:{srv.server_address[1]}/v1/save",
                                     data=body.encode(), headers={"Authorization": "Bearer t"})
        with urllib.request.urlopen(req) as r:
            return r.status
    reel = "https://www.instagram.com/reel/N1/"
    try:
        assert post(json.dumps({"url": reel, "note": "for the gameplan site"})) == 202
        assert appdb.take_inbox() == [(reel, "for the gameplan site", "app")]

        assert post(_shortcut_body('music lib: the "drop" at 0:12\\ok\tnow', reel, "")) == 202
        assert appdb.take_inbox() == [(reel, 'music lib: the "drop" at 0:12\\ok now', "app")]
        assert post(_shortcut_body("", "", reel)) == 202  # Done with nothing typed
        assert appdb.take_inbox() == [(reel, "", "app")]

        # A stale clipboard with quotes and a newline breaks the JSON; the note
        # still arrives, and a link inside it is not mistaken for the save.
        broken = _shortcut_body("like https://other.example/x", reel, 'he said "wow"\nhi')
        assert post(broken) == 202
        assert appdb.take_inbox() == [(reel, "like https://other.example/x", "app")]
    finally:
        srv.shutdown()
        appdb.INBOX = old_inbox


def test_the_shortcut_asks_for_one_optional_line(tmp_path):
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "tools"))
    import make_shortcut

    wf = make_shortcut.build("https://example.test/", "secret")
    [ask] = [a["WFWorkflowActionParameters"] for a in wf["WFWorkflowActions"]
             if a["WFWorkflowActionIdentifier"] == "is.workflow.actions.ask"]
    assert ask["WFInputType"] == "Text" and ask["WFAllowsMultilineText"] is False
    assert "optional" in ask["WFAskActionPrompt"].lower()
    [req] = [a["WFWorkflowActionParameters"] for a in wf["WFWorkflowActions"]
             if a["WFWorkflowActionIdentifier"] == "is.workflow.actions.downloadurl"]
    assert req["WFURL"] == "https://example.test/v1/save"


@contextlib.contextmanager
def _stubbed(obj, **attrs):
    old = {k: getattr(obj, k) for k in attrs}
    for k, v in attrs.items():
        setattr(obj, k, v)
    try:
        yield
    finally:
        for k, v in old.items():
            setattr(obj, k, v)


@contextlib.contextmanager
def _a_saved_link(tmp_path, url="https://www.instagram.com/reel/N2/"):
    """A link already saved, with no note: its vault file and ledger row. Yields
    (url, file, the notes Notion was given). Any attempt to fetch the link fails."""
    import acquire
    import bot
    import folders
    import ledger

    def no_fetch(_):
        raise AssertionError("an already-saved link must not run again")
    notes = []
    _setup(tmp_path)
    ledger._PATH, ledger._PENDING = tmp_path / "l.json", tmp_path / "p.json"
    with _stubbed(bot, PROJECT_DIR=tmp_path, _in_flight=set(), _late_notes={}), \
            _stubbed(acquire, acquire=no_fetch), \
            _stubbed(bot.notion, enabled=lambda: True,
                     add_note=lambda u, n: notes.append((u, n)) or True):
        rel = bot._write_vault_note({"title": "Fonts", "folder": folders.CRAFT, "why_save": "a model's guess"},
                                    url, "**Why save:** said in the video", "2026-11-01", {})
        ledger.put(url, {"status": "done", "title": "Fonts", "path": rel, "sig": ""})
        yield url, tmp_path / "vault" / rel, notes


def test_a_note_on_a_saved_link_goes_into_its_note_without_running_it_again(tmp_path):
    import bot
    with _a_saved_link(tmp_path) as (url, path, notes):
        def share(note):
            return asyncio.run(bot.run_pipeline(url, user_note=note)).html
        before = path.read_text()

        assert "Kept" not in share("") and path.read_text() == before and not notes

        assert "Kept your note" in share('for "subs" on reels')
        text = path.read_text()
        assert 'my_note: "for \\"subs\\" on reels"' in text.split("\n---\n")[0]
        assert '**Why save:** for "subs" on reels\n\n**Original:**' in text
        assert "a model's guess" not in text
        assert "**Why save:** said in the video" in text  # the transcript is verbatim
        assert notes == [(url, 'for "subs" on reels')]
        assert len(list((tmp_path / "vault").rglob("*.md"))) == 1

        assert "Kept" not in share('for "subs" on reels')  # nothing new, nothing repeated
        assert path.read_text() == text and len(notes) == 1

        share("no, for the gameplan site")  # the newest words are the reason now
        text = path.read_text()
        assert text.count("my_note:") == 1 and 'my_note: "no, for the gameplan site"' in text
        assert text.count("**Why save:** no, for the gameplan site") == 1 and "reels" not in text
        assert len(notes) == 2

        moved = path.parent.parent / "Elsewhere" / path.name  # re-filed by a tool
        moved.parent.mkdir()
        path.rename(moved)
        share("still here")
        assert 'my_note: "still here"' in moved.read_text()


def test_a_note_on_a_note_less_save_is_added_where_a_fresh_save_puts_it(tmp_path):
    import bot
    import folders
    import ledger
    with _a_saved_link(tmp_path, "https://www.instagram.com/reel/N3/") as (url, path, _):
        rel = bot._write_vault_note({"title": "Plain", "folder": folders.CRAFT}, url, "", "2026-11-01", {})
        path.unlink()
        ledger.put(url, {"status": "done", "title": "Plain", "path": rel, "sig": ""})
        assert asyncio.run(bot._keep_note(url, "why"))
        text = (tmp_path / "vault" / rel).read_text()
        fresh = bot._write_vault_note({"title": "Plain", "folder": folders.CRAFT, "why_save": "why",
                                       "my_note": "why"}, url, "", "2026-11-01", {})
        assert text == (tmp_path / "vault" / fresh).read_text()  # byte for byte
        ledger.put(url, {"status": "failed"})
        assert not asyncio.run(bot._keep_note(url, "not saved, so nothing to note"))


def test_a_note_on_a_repost_goes_to_the_save_it_repeats(tmp_path):
    import bot
    import ledger
    words = "the same words spoken in both of these reels, long enough to fingerprint " * 5
    with _a_saved_link(tmp_path) as (url, path, _):
        ledger.put(url, ledger.get(url) | {"sig": bot.textsig.sig(words)})
        res = asyncio.run(bot.run_pipeline("https://www.tiktok.com/@a/video/1", user_note="for subs",
                                           media={"transcript": words}))
        assert res.share == "duplicate" and "Kept your note" in res.html
        assert 'my_note: "for subs"' in path.read_text()


def test_a_note_sent_while_the_link_is_running_lands_when_it_ends(tmp_path):
    """Missing the share button's window and sharing again usually lands here:
    the first run takes about a minute, and it started without the note."""
    import bot
    import ledger

    async def go(outcome):
        started, finish = asyncio.Event(), asyncio.Event()

        async def run(*a, **k):
            started.set()
            await finish.wait()
            return bot.Result("note", None, None, outcome)
        with _stubbed(bot, run_pipeline=run):
            first = asyncio.create_task(bot.process(None, 1, url, force=False, source="app"))
            await started.wait()
            await bot.process(None, 1, url, force=False, user_note="for Lak", source="app")
            assert ledger.pending_all()[url]["note"] == "for Lak"  # survives a restart
            finish.set()
            await first
    with _a_saved_link(tmp_path) as (url, path, _):
        asyncio.run(go(bot.RETRYABLE))
        assert "my_note" not in path.read_text()  # still queued: the retry writes it
        assert ledger.pending_all()[url]["note"] == "for Lak" and not bot._late_notes

        asyncio.run(go(bot.SAVED))
        assert 'my_note: "for Lak"' in path.read_text()
        assert url not in ledger.pending_all() and not bot._late_notes


def test_a_note_reaches_a_card_that_already_exists(tmp_path):
    _setup(tmp_path)
    calls = _Calls()
    tgcards.call, tgcards._topics_on = calls, None
    url = _item(1)["url"]

    def note(text):
        asyncio.run(tgcards.noted(url, text))
    def edits():
        return [p for m, p in calls.made if m == "editMessageText"]

    note("nothing to attach it to yet")  # no card: propose() reads it from remember_note
    cid = cards.propose(_item(1))
    asyncio.run(tgcards.pump())

    note("this one matters")  # an open card shows it, buttons intact
    assert "Your note: this one matters" in edits()[-1]["text"] and edits()[-1]["reply_markup"]
    assert cards.get(cid)["status"] == "open"
    note("this one matters")
    assert len(edits()) == 1

    note("no, this is for Lak")  # names a topic: the card goes there and goes out again
    c = cards.get(cid)
    assert (c["topic"], c["status"]) == ("lak", "open") and c["my_note"] == "no, this is for Lak"
    assert "Moved to Lak" in edits()[-1]["text"] and "reply_markup" not in edits()[-1]

    cards.act(cid, "done")
    sent = len(calls.made)
    note("and for the gameplan site")  # closed stays closed, but the words are kept
    assert cards.get(cid)["status"] == "done" and len(calls.made) == sent
    said = [e["text"] for e in cards.events() if e["action"] == "comment"]
    assert said == ["this one matters", "no, this is for Lak", "and for the gameplan site"]


def test_a_note_naming_a_library_sends_a_resource_card_home(tmp_path):
    _setup(tmp_path)
    tool = _item(2, title="Music packs", asset="tool", project="lak")
    cid = cards.propose(tool)
    cards.move(cid, "lak")
    assert cards.topic_for_note(cards.get(cid), "music lib") == "content"
    assert cards.topic_for_note(cards.get(cid), "just a thought") is None
    step = cards.get(cards.propose(_item(3, project="lak")))
    assert cards.topic_for_note(step, "the music here") is None  # only a resource has a library


def test_a_later_note_is_added_to_the_notion_page_as_a_callout(tmp_path):
    import notion
    made = []

    def api(url, token, method="GET", body=None):
        made.append((url, method, body))
        return {"results": [{"id": "page1"}] if url.endswith("/query") and rows else []}
    env = {"NOTION_TOKEN": "t", "NOTION_DATABASE_ID": "db"}
    old = {k: cards.os.environ.get(k) for k in env}
    cards.os.environ.update(env)
    try:
        with _stubbed(notion, _api=api):
            rows = True
            assert notion.add_note("https://x/1", " for subs ")
            url, method, body = made[-1]
            assert url.endswith("/blocks/page1/children") and method == "PATCH"
            text = body["children"][0]["callout"]["rich_text"][0]["text"]["content"]
            assert text == "for subs"
            rows = False  # a real-life save has no row
            assert not notion.add_note("https://x/2", "for subs")
    finally:
        for k, v in old.items():
            cards.os.environ.pop(k, None) if v is None else cards.os.environ.__setitem__(k, v)


if __name__ == "__main__":
    fns = [v for k, v in dict(globals()).items() if k.startswith("test_") and callable(v)]
    for fn in fns:
        with tempfile.TemporaryDirectory() as d:
            fn(pathlib.Path(d))
        print("ok", fn.__name__)
    print(f"{len(fns)} passed")
