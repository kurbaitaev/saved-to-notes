"""Cards: one next step per save (cards.py), its API and its Telegram side.

Runs under pytest or on its own: `python tests/test_cards.py`.
"""

import asyncio
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


if __name__ == "__main__":
    fns = [v for k, v in dict(globals()).items() if k.startswith("test_") and callable(v)]
    for fn in fns:
        with tempfile.TemporaryDirectory() as d:
            fn(pathlib.Path(d))
        print("ok", fn.__name__)
    print(f"{len(fns)} passed")
