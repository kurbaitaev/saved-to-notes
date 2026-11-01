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


if __name__ == "__main__":
    fns = [v for k, v in dict(globals()).items() if k.startswith("test_") and callable(v)]
    for fn in fns:
        with tempfile.TemporaryDirectory() as d:
            fn(pathlib.Path(d))
        print("ok", fn.__name__)
    print(f"{len(fns)} passed")
