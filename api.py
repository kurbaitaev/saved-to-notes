#!/usr/bin/env python3
"""Afterscroll API — what the iOS app and its share button talk to.

    GET  /v1/health                   -> {"ok": true}           (no auth)
    GET  /v1/saves                    -> {"saves": [...]}       real-life saves + clip URLs
    GET  /v1/clips/<save>/<file>.mp4  -> the video (Range supported)
    POST /v1/save  {"url", "note"?}   -> 202, queued for the bot

Cards (cards.py) — one next step per save, for every surface that shows them:
    GET  /v1/cards?topic=&status=open&limit=   -> {"cards": [...], "topics": [...]}
    GET  /v1/cards/stats                       -> the 14-day action rate
    GET  /v1/cards/events?since=&actions=a,b   -> what you did and said, for the matcher
    POST /v1/cards/propose {"items": [...]}    -> Context Engine hands over new matches
    POST /v1/cards/<id> {"action"} | {"comment"} -> act on a card from outside Telegram

Every call but health needs `Authorization: Bearer $APP_TOKEN` (.env). It listens
on 127.0.0.1 only; Tailscale Funnel publishes it over HTTPS
(`tailscale funnel --bg --https=8443 http://127.0.0.1:8791`).

Stdlib only, on purpose: one person's saves, a handful of requests a day — a
framework would be one more thing to upgrade on the server.
"""

import hmac
import json
import os
import pathlib
import re
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PROJ = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(PROJ))

import appdb  # noqa: E402
import cards  # noqa: E402

PORT = int(os.environ.get("APP_API_PORT", "8791"))
_CLIP = re.compile(r"^/v1/clips/([0-9a-f]{12})/((?:loop|move\d{1,2})\.(?:mp4|jpg))$")
_CARD = re.compile(r"^/v1/cards/([0-9a-f]{12})$")


def load_env() -> None:
    f = PROJ / ".env"
    if f.exists():
        for line in f.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


class Handler(BaseHTTPRequestHandler):
    server_version = "Afterscroll/1"

    def log_message(self, fmt, *args):  # one line per request, no headers or tokens
        stamp = time.strftime("%Y-%m-%d %H:%M:%S")
        ua = self.headers.get("User-Agent", "")[:40]
        sys.stderr.write(f"{stamp} {self.command} {self.path.split('?')[0]} {ua}\n")

    def _json(self, code: int, obj) -> None:
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _authed(self) -> bool:
        token = os.environ.get("APP_TOKEN", "")
        got = self.headers.get("Authorization", "").removeprefix("Bearer ").strip()
        if token and hmac.compare_digest(got, token):
            return True
        self._json(401, {"error": "missing or wrong token"})
        return False

    def do_GET(self):  # noqa: N802
        path = self.path.split("?")[0]
        if path == "/v1/health":
            return self._json(200, {"ok": True})
        if not self._authed():
            return
        if path == "/v1/saves":
            return self._json(200, {"saves": appdb.all_saves(), "pending": appdb.pending_count(),
                                    "recent": appdb.recent_shares()})
        if path.startswith("/v1/cards"):
            return self._cards_get(path, self._query())
        m = _CLIP.match(path)
        if m:
            return self._file(appdb.CLIPS / m.group(1) / m.group(2))
        self._json(404, {"error": "not found"})

    def _query(self) -> dict:
        from urllib.parse import parse_qs, urlsplit
        return {k: v[-1] for k, v in parse_qs(urlsplit(self.path).query).items()}

    def _body(self) -> dict:
        n = min(int(self.headers.get("Content-Length", "0")), 512_000)
        try:
            d = json.loads(self.rfile.read(n).decode("utf-8", "replace") or "{}")
        except ValueError:
            return {}
        return d if isinstance(d, dict) else {}

    def _cards_get(self, path: str, q: dict):
        if path == "/v1/cards":
            limit = max(1, min(int(q.get("limit") or 50), 200))
            status = q.get("status", "open") or None
            return self._json(200, {"cards": cards.listing(tid=q.get("topic"), status=status, limit=limit),
                                    "adds": cards.pending_adds(), "topics": cards.topics(),
                                    "destinations": cards.config().get("destinations", [])})
        if path == "/v1/cards/stats":
            return self._json(200, cards.stats())
        if path == "/v1/cards/events":
            acts = tuple(a for a in (q.get("actions") or "").split(",") if a)
            return self._json(200, {"events": cards.events(since=float(q.get("since") or 0),
                                                           actions=acts)})
        self._json(404, {"error": "not found"})

    def _cards_post(self, path: str):
        d = self._body()
        if path == "/v1/cards/propose":
            made = [cid for it in (d.get("items") or []) if isinstance(it, dict)
                    for cid in [cards.propose(it)] if cid]
            return self._json(200, {"created": made})
        m = _CARD.match(path)
        if not m or not cards.get(m.group(1)):
            return self._json(404, {"error": "no such card"})
        cid = m.group(1)
        if d.get("comment"):
            cards.comment(cid, str(d["comment"]))
        if d.get("action") == "applied":
            cards.applied(cid)
        elif d.get("action"):
            try:
                # "via" tells the bot to update the Telegram message, which
                # otherwise keeps offering buttons for a card already handled.
                cards.act(cid, str(d["action"]), f"via {str(d.get('via') or 'api')[:20]}")
            except ValueError as e:
                return self._json(400, {"error": str(e)})
        self._json(200, cards.get(cid))

    def do_POST(self):  # noqa: N802
        path = self.path.split("?")[0]
        if path.startswith("/v1/cards/"):
            if self._authed():
                self._cards_post(path)
            return
        if path not in ("/v1/save", "/v1/report"):
            return self._json(404, {"error": "not found"})
        if not self._authed():
            return
        if path == "/v1/report":
            # The share button calls this when it can't find a link, saying
            # what the other app actually handed over — the only way to see
            # inside another app's share sheet.
            n = min(int(self.headers.get("Content-Length", "0")), 8_000)
            sys.stderr.write(f"  share report: {self.rfile.read(n).decode('utf-8', 'replace')[:2000]}\n")
            return self._json(204, {})
        n = min(int(self.headers.get("Content-Length", "0")), 64_000)
        raw = self.rfile.read(n).decode("utf-8", "replace")
        try:
            d = json.loads(raw or "{}")
            d = d if isinstance(d, dict) else {"url": str(d)}
        except ValueError:
            # A shortcut splices clipboard text straight into its JSON, so a
            # caption with quotes or newlines breaks it — search the raw text.
            d = {"url": raw}
        # The shared item first; the clipboard ("clip") only when the sharing
        # app passed nothing — Instagram hands shortcuts an empty input.
        link = re.compile(r"https?://[^\s\"'<>\\]+")
        m = link.search(str(d.get("url") or "")) or link.search(str(d.get("clip") or ""))
        if not m:
            # What arrived instead tells us how the sharing app packs its link.
            sys.stderr.write(f"  no link in: {json.dumps(d, ensure_ascii=False)[:600]}\n")
            return self._json(400, {"error": "no link in 'url'"})
        appdb.enqueue(m.group(0), str(d.get("note") or "")[:500])
        sys.stderr.write(f"  queued {m.group(0)[:120]}\n")
        self._json(202, {"queued": m.group(0)})

    def _file(self, p: pathlib.Path) -> None:
        if not p.is_file():
            return self._json(404, {"error": "no such clip"})
        size = p.stat().st_size
        start, end = 0, size - 1
        rng = re.match(r"bytes=(\d*)-(\d*)$", self.headers.get("Range", ""))
        if rng and (rng.group(1) or rng.group(2)):
            if rng.group(1):
                start = int(rng.group(1))
                end = int(rng.group(2)) if rng.group(2) else size - 1
            else:  # suffix range: the last N bytes
                start = max(0, size - int(rng.group(2)))
            end = min(end, size - 1)
            if start > end:
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{size}")
                self.end_headers()
                return
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        else:
            self.send_response(200)
        self.send_header("Content-Type", "image/jpeg" if p.suffix == ".jpg" else "video/mp4")
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(end - start + 1))
        self.send_header("Cache-Control", "private, max-age=31536000, immutable")
        self.end_headers()
        with p.open("rb") as f:
            f.seek(start)
            left = end - start + 1
            while left > 0:
                chunk = f.read(min(65536, left))
                if not chunk:
                    break
                self.wfile.write(chunk)
                left -= len(chunk)


def main() -> None:
    load_env()
    if not os.environ.get("APP_TOKEN"):
        sys.exit("APP_TOKEN is not set in .env — refusing to serve without auth")
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
