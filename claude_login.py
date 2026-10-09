#!/usr/bin/env python3
"""Where the Claude CLI keeps its login — the one place that knows.

macOS: the login keychain, entry "Claude Code-credentials".
Linux: ~/.claude/.credentials.json.

doctor.py and watchdog.py each had their own keychain-only copy, so on the
server both reported "no login" while `claude -p` was answering fine on a Max
subscription. One reader, two platforms, no more disagreement.
"""

import datetime as dt
import json
import os
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


def can_refresh(blob: dict | None = None, now: float | None = None) -> bool:
    """A refresh token that has itself expired cannot refresh anything — that
    is exactly how the Mac's login died ("could not be refreshed")."""
    b = oauth_blob() if blob is None else blob
    if not b.get("refreshToken"):
        return False
    rexp = b.get("refreshTokenExpiresAt") or 0
    return not rexp or rexp / 1000 >= (time.time() if now is None else now)


def days_until_refresh_expiry(blob: dict | None = None, now: float | None = None) -> float | None:
    """None when the login carries no refresh expiry to read."""
    b = oauth_blob() if blob is None else blob
    rexp = b.get("refreshTokenExpiresAt") or 0
    if not rexp:
        return None
    return (rexp / 1000 - (time.time() if now is None else now)) / 86400


def describe(blob: dict | None = None) -> str:
    b = oauth_blob() if blob is None else blob
    if not b:
        return ""
    where = "keychain" if IS_MAC else "~/.claude/.credentials.json"
    plan = b.get("subscriptionType") or "subscription"
    return f"Claude CLI login ({plan}, {where})"


# --- long-lived token from `claude setup-token` --------------------------------
# The CLI honours CLAUDE_CODE_OAUTH_TOKEN ahead of the credentials file. It does
# not refresh and lasts a year, so nothing about it can be read from the token
# itself; CLAUDE_CODE_OAUTH_TOKEN_SET_AT (YYYY-MM-DD) records when it was made.
TOKEN_LIFETIME_DAYS = 365


def long_lived_token() -> str:
    return os.environ.get("CLAUDE_CODE_OAUTH_TOKEN", "").strip()


def token_days_left(today: dt.date | None = None) -> float | None:
    """Days until the setup-token expires; None when there is no token or no
    recorded creation date."""
    if not long_lived_token():
        return None
    raw = os.environ.get("CLAUDE_CODE_OAUTH_TOKEN_SET_AT", "").strip()
    try:
        made = dt.date.fromisoformat(raw)
    except ValueError:
        return None
    return TOKEN_LIFETIME_DAYS - ((today or dt.date.today()) - made).days
