#!/usr/bin/env python3
"""Cards in Telegram: one topic per project inside the chat with the bot.

The bot used to answer every save with a full note: reading material, in one
long chat. A card is the opposite: one step for one project, with buttons, in
that project's topic, and never more than three waiting there. You act on it
(Done, Remake, Add, Not now) or write back, and either way the card and the
matcher learn something.

Private-chat topics need Bot API 9.4+ and "topics" switched on for the bot in
@BotFather. Until they are, cards wait in the queue: six projects' worth of
cards in the main chat would be the wall of messages this replaces.
"""

import asyncio
import datetime as dt
import html
import json
import logging
import os
import time
import urllib.error
import urllib.request

from telegram import Update
from telegram.ext import ContextTypes

import cards
import notion

log = logging.getLogger("saved-to-notes.cards")

ACTIONS = {"d": "done", "r": "remade", "a": "added", "n": "notnow"}
LABEL = {"done": "✅ Done", "remade": "🎬 Remake", "added": "➕ Added", "notnow": "Not now"}
AFTER = {
    "done": "✅ Done.",
    "remade": "🎬 Remake: the Russian draft appears in Content Ideas within 15 minutes.",
    "added": "➕ Added. It's waiting for you in your next session there.",
    "notnow": "⏸ Not now.",
    "expired": "⌛ Expired after 14 days. The save stays in Notion.",
}
_topics_on: bool | None = None
_topics_checked = 0.0
RECHECK_S = 600  # how often to ask Telegram again while topics are off
LEARN_BUTTON = {"inline_keyboard": [[{"text": "✅ Finished, next", "callback_data": "l|done"}]]}
_icons: dict | None = None


def _owner() -> int | None:
    first = cards.default_user()
    return int(first) if first.lstrip("-").isdigit() else None


def _api(method: str, params: dict) -> dict:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    req = urllib.request.Request(f"https://api.telegram.org/bot{token}/{method}",
                                 data=json.dumps(params).encode(),
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:  # Telegram explains itself in the body
        try:
            return json.load(e)
        except ValueError:
            return {"ok": False, "description": str(e)}


async def call(method: str, params: dict) -> dict:
    r = await asyncio.to_thread(_api, method, params)
    if not r.get("ok"):
        log.warning("%s failed: %s", method, r.get("description"))
    return r


async def topics_on() -> bool:
    global _topics_on, _topics_checked
    if _topics_on is None or (not _topics_on and time.time() - _topics_checked > RECHECK_S):
        _topics_checked = time.time()
        me = (await call("getMe", {})).get("result") or {}
        was, _topics_on = _topics_on, bool(me.get("has_topics_enabled"))
        if not _topics_on and was is None:
            log.info("private-chat topics are off for this bot; cards wait until they're on")
    return _topics_on


async def _icon_id(emoji: str) -> str | None:
    """Telegram's topic icon for this emoji. It goes on the topic, not in its name,
    where Telegram would draw it a second time. Only its own set of icons is allowed."""
    global _icons
    if _icons is None:
        r = await call("getForumTopicIconStickers", {})
        if not r.get("ok"):
            return None
        _icons = {s.get("emoji", "").replace("️", ""): s.get("custom_emoji_id")
                  for s in r.get("result") or []}
    return _icons.get(emoji.replace("️", ""))


async def thread_for(tid: str) -> int | None:
    """The topic's thread in the owner's chat, created the first time it's needed."""
    have = cards.thread_of(tid)
    if have or not await topics_on():
        return have
    t = cards.topic(tid) or {}
    params = {"chat_id": _owner(), "name": t.get("name", tid)[:128]}
    icon = await _icon_id(t.get("emoji", ""))
    if icon:
        params["icon_custom_emoji_id"] = icon
    r = await call("createForumTopic", params)
    thread = (r.get("result") or {}).get("message_thread_id")
    if thread:
        cards.set_thread(tid, thread)
    return thread


def render(c: dict, status: str = "") -> str:
    t = cards.topic(c["topic"]) or {}
    head = "" if cards.thread_of(c["topic"]) else f"<b>#{html.escape(t.get('name', c['topic']))}</b>\n"
    lines = [f"{head}<b>{html.escape(c.get('title') or 'Saved post')}</b>"]
    if c["kind"] == "add":
        d = cards.destination(c.get("destination") or "") or {}
        lines.append(f"➕ Add to: <b>{html.escape(d.get('name', 'your library'))}</b>")
        lines.append(html.escape(c["step"]))
    else:
        lines.append(f"👉 {html.escape(c['step'])}")
    if c.get("steps"):
        body = "\n".join(f"{i}. {html.escape(s)}" for i, s in enumerate(c["steps"], 1))
        lines.append(f"<blockquote expandable>{body}</blockquote>")
    if c.get("my_note"):
        lines.append(f"<i>Your note: {html.escape(c['my_note'][:300])}</i>")
    meta = [html.escape(c.get("category") or "")]
    meta.append(f'<a href="{html.escape(c["url"], quote=True)}">open the save</a>')
    lines.append(" · ".join(m for m in meta if m))
    if status:
        lines.append(f"\n{status}")
    return "\n".join(lines)


def keyboard(c: dict) -> dict:
    if c["kind"] == "add":
        row = [("a", "➕ Add")]
    elif c["topic"] == cards.config().get("remake_topic", "content"):
        row = [("r", "🎬 Remake"), ("d", "✅ Done")]
    else:
        row = [("d", "✅ Done")]
    row.append(("n", "Not now"))
    return {"inline_keyboard": [[{"text": t, "callback_data": f"c|{c['id']}|{k}"} for k, t in row]]}


async def send(c: dict) -> bool:
    chat = _owner()
    if chat is None:
        return False
    thread = await thread_for(c["topic"])
    params = {"chat_id": chat, "text": render(c), "parse_mode": "HTML",
              "link_preview_options": {"is_disabled": True}, "reply_markup": keyboard(c)}
    if thread:
        params["message_thread_id"] = thread
    r = await call("sendMessage", params)
    if not r.get("ok") and thread:
        # The topic was deleted on the phone: make a new one next time.
        cards.set_thread(c["topic"], None)
        return False
    mid = (r.get("result") or {}).get("message_id")
    if mid:
        cards.opened(c["id"], thread, mid)
    return bool(mid)


async def close(c: dict, status: str) -> None:
    """Show what happened on the card and take the buttons away."""
    if c.get("message_id"):
        await call("editMessageText", {"chat_id": _owner(), "message_id": c["message_id"],
                                       "text": render(c, status), "parse_mode": "HTML",
                                       "link_preview_options": {"is_disabled": True}})


async def _redraw(c: dict) -> None:
    await call("editMessageText", {"chat_id": _owner(), "message_id": c["message_id"],
                                   "text": render(c), "parse_mode": "HTML",
                                   "link_preview_options": {"is_disabled": True},
                                   "reply_markup": keyboard(c)})


_pumping = asyncio.Lock()


async def pump() -> int:
    """Expire what's been ignored, then fill each topic up to its cap. One at a
    time: the heartbeat and a button tap can both pump, and two at once would
    send the same waiting card twice."""
    async with _pumping:
        for c in cards.expire():
            await close(c, AFTER["expired"])
        if not await topics_on():
            return 0
        sent = 0
        for c in cards.due():
            sent += await send(c)
        return sent


async def _move(c: dict, tid: str) -> None:
    if c["status"] == "open":
        name = (cards.topic(tid) or {}).get("name", tid)
        await close(c, f"↪ Moved to {html.escape(name)}.")
    cards.move(c["id"], tid)
    await pump()


async def noted(url: str, note: str) -> None:
    """A note added to a save that already has a card. A note wins here as it
    does when a card is made: if it points at another topic the card goes there,
    otherwise an open card shows it. A closed card only records it."""
    c = cards.set_note(url, note)
    if not c or c["status"] not in ("queued", "open"):
        return
    tid = cards.topic_for_note(c, note)
    if tid:
        await _move(c, tid)
    elif c["status"] == "open":
        await _redraw(c)


async def apply(c: dict, action: str) -> str:
    """Side effects of an action. Returns the line shown on the card."""
    if action == "remade":
        ok = await asyncio.to_thread(notion.set_checkbox, c["url"], "Worth remaking", True)
        if not ok:
            return "🎬 Marked for a remake, but Notion didn't take the tick: tick it there."
    if action == "added":
        d = cards.destination(c.get("destination") or "") or {}
        return f"➕ Added to {d.get('name', 'your library')}. It's waiting in your next session there."
    return AFTER[action]


async def on_callback(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    if str(update.effective_user.id) != cards.default_user():
        await q.answer("Not yours.")
        return
    try:
        _, cid, code = (q.data or "").split("|")
        action = ACTIONS[code]
    except (ValueError, KeyError):
        await q.answer()
        return
    c = cards.get(cid)
    if not c or c["status"] != "open":
        await q.answer("Already handled.")
        return
    await q.answer(LABEL[action])
    c = cards.act(cid, action, "via telegram")
    await close(c, await apply(c, action))
    await pump()


REWRITE = """A saved post was turned into one next step for a project. The owner replied to it.

Project: {project}
Saved post: {title}
Current step: {step}
Current sub-steps: {steps}
Owner's reply: {reply}

If the reply changes what the step should be (narrower, different angle, a specific part to use),
rewrite it to follow the reply exactly: "use" is ONE line, max 16 words, starts with a verb;
"steps" are 2 to 4 short steps. Write to the owner as "you". Only use what the post and the reply
say. If the reply doesn't ask to change the step (thanks, a question, a remark), answer {{"keep": true}}.

Answer with only JSON: {{"use": "...", "steps": ["..."]}} or {{"keep": true}}"""


async def on_text(update: Update, _: ContextTypes.DEFAULT_TYPE) -> bool:
    """A message with no link in a card's topic, or a reply to a card, is about
    that card. Returns False when it isn't, so the caller can say "send a link"."""
    m = update.message
    c = None
    if m.reply_to_message:
        c = cards.by_message(m.reply_to_message.message_id)
    if c is None and m.message_thread_id:
        tid = cards.topic_of_thread(m.message_thread_id)
        c = cards.latest_open(tid) if tid else None
    if c is None:
        return False
    text = (m.text or "").strip()
    cards.comment(c["id"], text)
    named = cards.topic_named_in(text)
    if named and named != c["topic"]:
        await _move(c, named)
        return True
    try:
        import content  # the remake pipeline's Claude helper
        out = await asyncio.to_thread(content.ask_claude, REWRITE.format(
            project=c.get("project") or c["topic"], title=c.get("title") or "", step=c["step"],
            steps="; ".join(c.get("steps") or []), reply=text[:800]), 180)
    except Exception as e:  # noqa: BLE001
        log.warning("rewrite failed for %s: %s", c["id"], e)
        out = {"keep": True}
    if out.get("use") and c["status"] == "open":
        c = cards.rewrite(c["id"], str(out["use"]), [str(s) for s in out.get("steps") or []][:4])
        await _redraw(c)
        await m.reply_text("Rewrote the step. Your reply also goes to the matcher as an example.")
    else:
        await m.reply_text("Noted. The matcher learns from it.")
    return True


async def sync_outside() -> None:
    """A card acted on from the app or a Claude session still shows buttons in
    Telegram; close those messages too."""
    since = float(cards.kv_get("outside_seen") or time.time())
    now = time.time()
    for e in cards.events(since=since, actions=tuple(cards.DONE | {"notnow"})):
        if not str(e.get("text") or "").startswith("via ") or e["text"] == "via telegram":
            continue
        c = cards.get(e["card_id"])
        if c:
            await close(c, AFTER[e["action"]] + f" ({html.escape(e['text'])})")
    cards.kv_set("outside_seen", str(now))


def _ce_call(path: str, body: dict | None = None) -> dict:
    base = os.environ.get("CE_API", "http://127.0.0.1:8792").rstrip("/")
    req = urllib.request.Request(base + path, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Authorization": f"Bearer {os.environ.get('APP_TOKEN', '')}",
                                          "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r)


async def ce(path: str, body: dict | None = None) -> dict:
    """Context Engine, for what to study and think about. Its being down costs
    those lines, not the message."""
    try:
        return await asyncio.to_thread(_ce_call, path, body)
    except (OSError, ValueError) as e:
        log.warning("context engine %s failed: %s", path, e)
        return {}


def _link(item: dict) -> str:
    title = html.escape(item.get("title") or "")
    src = item.get("source") or ""
    return f'<a href="{html.escape(src)}">{title}</a>' if src.startswith("http") else f"<b>{title}</b>"


def _learn_line(item: dict) -> str:
    return f"📚 <b>Learning now:</b> {_link(item)}"


async def on_learn(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
    """The button on Saturday's line: finished it, so show the next one."""
    q = update.callback_query
    if str(update.effective_user.id) != cards.default_user():
        await q.answer("Not yours.")
        return
    got = await ce("/api/learn/done", {"via": "telegram"})
    if not got:
        await q.answer("Couldn't reach the engine. Try again later.")
        return
    await q.answer("Finished")
    await call("editMessageReplyMarkup", {"chat_id": q.message.chat_id, "message_id": q.message.message_id,
                                          "reply_markup": {"inline_keyboard": []}})
    nxt = got.get("next")
    text = (_learn_line(nxt) if nxt else "📚 That was the last one on your list.")
    params = {"chat_id": q.message.chat_id, "text": text, "parse_mode": "HTML",
              "link_preview_options": {"is_disabled": True}}
    if nxt:
        params["reply_markup"] = LEARN_BUTTON
    await call("sendMessage", params)


async def saturday() -> None:
    """Saturday evening, one message: what you finished this week per topic, what
    you're studying, and one idea. The idea asks nothing of you.
    Off while cards are off (CARDS_CAP=0): the Sunday summary carries it."""
    if cards.cap() <= 0:
        return
    now = dt.datetime.now()
    week = now.strftime("%G-W%V")
    if now.weekday() != 5 or now.hour < 18 or cards.kv_get(f"saturday_{week}"):
        return
    cards.kv_set(f"saturday_{week}", "1")
    done = cards.week_done()
    st = cards.stats()
    if done:
        parts = []
        for tid, evs in done.items():
            name = (cards.topic(tid) or {}).get("name", tid)
            titles = ", ".join(html.escape((e.get("title") or "")[:40]) for e in evs[:3])
            parts.append(f"<b>{html.escape(name)}</b> {len(evs)}: {titles}")
        text = "🗓 <b>This week you finished</b>\n" + "\n".join(parts)
    else:
        text = f"🗓 Nothing finished this week. {st['open']} cards are waiting in their topics."
    if st["rate"] is not None:
        text += f"\n\nCards acted on within 14 days: {round(st['rate'] * 100)}% (goal 20%)."
    got = await ce("/api/picks")
    learn, think = got.get("learn"), got.get("think")
    if learn:
        text += "\n\n" + _learn_line(learn)
    if think:
        why = html.escape((think.get("why") or "")[:280])
        text += f"\n\n💭 <b>To think about:</b> {_link(think)}\n{why}"
    params = {"chat_id": _owner(), "text": text, "parse_mode": "HTML", "link_preview_options": {"is_disabled": True}}
    if learn:
        params["reply_markup"] = LEARN_BUTTON
    await call("sendMessage", params)


async def tick() -> None:
    """Every minute from the bot's heartbeat. Each part fails alone."""
    for step in (pump, sync_outside, saturday):
        try:
            await step()
        except Exception as e:  # noqa: BLE001
            log.warning("cards %s failed: %s", step.__name__, e)
