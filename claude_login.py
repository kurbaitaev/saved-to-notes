#!/usr/bin/env python3
"""Where the Claude CLI keeps its login — the one place that knows.

macOS: the login keychain, entry "Claude Code-credentials".
Linux: ~/.claude/.credentials.json.

doctor.py and watchdog.py each had their own keychain-only copy, so on the
server both reported "no login" while `claude -p` was answering fine on a Max
subscription. One reader, two platforms, no more disagreement.
"""

import json
import pathlib
import subprocess
import sys
import time

IS_MAC = sys.platform == "darwin"
CRED_FILE = pathlib.Path.home() / ".claude" / ".credentials.json"


def oauth_blob() -> dict:
    """The claudeAiOauth dict, or {} when there is no login to read."""
    try:
        if IS_MAC:
            r = subprocess.run(["security", "find-generic-password", "-s",
                                "Claude Code-credentials", "-w"],
                               capture_output=True, text=True, timeout=10)
            raw = r.stdout.strip()
        else:
            raw = CRED_FILE.read_text() if CRED_FILE.exists() else ""
        return json.loads(raw).get("claudeAiOauth", {}) if raw else {}
    except Exception:  # noqa: BLE001 — unreadable is the same as absent
        return {}


def session_valid(blob: dict | None = None, now: float | None = None) -> bool:
    """A live access token. expiresAt of 0/absent is what logged-out looks
    like, and must NOT read as 'no expiry, so fine' — that exact misread once
    let three reels fail with no alert."""
    b = oauth_blob() if blob is None else blob
    exp = b.get("expiresAt") or 0
    return bool(exp) and exp / 1000 >= (time.time() if now is None else now)


def can_refresh(blob: dict | None = None) -> bool:
    b = oauth_blob() if blob is None else blob
    return bool(b.get("refreshToken"))


def describe(blob: dict | None = None) -> str:
    b = oauth_blob() if blob is None else blob
    if not b:
        return ""
    where = "keychain" if IS_MAC else "~/.claude/.credentials.json"
    plan = b.get("subscriptionType") or "subscription"
    return f"Claude CLI login ({plan}, {where})"
