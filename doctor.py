#!/usr/bin/env python3
"""Check whether this machine can actually run the bot, and say what's missing.

    python3 doctor.py

Every line is either OK, MISSING (must fix), or OPTIONAL (works without it,
but you lose something specific).
"""

import json
import os
import pathlib
import shutil
import subprocess
import sys

import claude_login  # noqa: E402

PROJ = pathlib.Path(__file__).resolve().parent
OK, BAD, OPT = "\033[32mOK\033[0m", "\033[31mMISSING\033[0m", "\033[33mOPTIONAL\033[0m"
problems = 0


def say(status: str, name: str, detail: str = "") -> None:
    print(f"  [{status}] {name}" + (f" — {detail}" if detail else ""))


def need(cond: bool, name: str, fix: str, detail: str = "") -> None:
    global problems
    if cond:
        say(OK, name, detail)
    else:
        say(BAD, name, fix)
        problems += 1


def _apify_usage(token: str) -> tuple[float | None, float | None]:
    """(spent this month, monthly cap) in USD, or (None, None) if unreachable."""
    import urllib.request
    try:
        with urllib.request.urlopen(
                f"https://api.apify.com/v2/users/me/limits?token={token}", timeout=15) as r:
            d = json.load(r)["data"]
        return (float(d.get("current", {}).get("monthlyUsageUsd", 0)),
                float(d.get("limits", {}).get("maxMonthlyUsageUsd") or 0) or None)
    except Exception:  # noqa: BLE001 — a doctor check must never itself crash
        return None, None


def optional(cond: bool, name: str, without: str, detail: str = "") -> None:
    say(OK if cond else OPT, name, detail if cond else f"without it: {without}")


def env(key: str) -> str:
    return os.environ.get(key, "").strip()


def load_env() -> None:
    f = PROJ / ".env"
    if not f.exists():
        return
    for line in f.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def ytdlp_version() -> str:
    try:
        return subprocess.run(["yt-dlp", "--version"], capture_output=True, text=True,
                              timeout=20).stdout.strip()
    except Exception:  # noqa: BLE001
        return ""


def main() -> int:
    global problems
    load_env()
    print("\nRequired\n")
    need(sys.version_info >= (3, 10), f"python {sys.version_info.major}.{sys.version_info.minor}",
         "need Python 3.10+ (brew install python)")
    try:
        import telegram  # noqa: F401
        need(True, "python-telegram-bot", "", "installed")
    except ImportError:
        need(False, "python-telegram-bot", "pip install -r requirements.txt")
    need(bool(env("TELEGRAM_BOT_TOKEN")), "TELEGRAM_BOT_TOKEN",
         "get one from @BotFather on Telegram, put it in .env")
    need(bool(env("ALLOWED_USER_IDS")), "ALLOWED_USER_IDS",
         "send /start to your bot to learn your id, then put it in .env "
         "(without it the bot refuses everyone)")

    # Reasoning backend: an API key, or a CLI login (keychain on macOS, a
    # credentials file on Linux). Exactly one of these must be usable.
    openai_key = bool(env("OPENAI_API_KEY"))
    anthropic_key = bool(env("ANTHROPIC_API_KEY"))
    cli = bool(shutil.which("claude"))
    logged_in = False
    if cli and not (openai_key or anthropic_key):
        blob = claude_login.oauth_blob()
        # A refreshable session counts: access tokens roll over hourly on
        # their own, as long as the CLI keeps being used.
        logged_in = claude_login.session_valid(blob) or claude_login.can_refresh(blob)
    if openai_key:
        backend = f"OpenAI ({env('OPENAI_MODEL') or 'gpt-5.6-terra'})"
    elif anthropic_key:
        backend = "Anthropic API key"
    elif logged_in:
        backend = claude_login.describe() + " — refreshes itself while in use"
    else:
        backend = ""
    need(bool(backend), "reasoning backend",
         "set OPENAI_API_KEY (or ANTHROPIC_API_KEY) in .env, or run `claude` then /login",
         backend)
    if openai_key:
        try:
            import openai  # noqa: F401
            say(OK, "openai package", "installed")
        except ImportError:
            say(BAD, "openai package", "pip install -r requirements.txt")
            problems += 1

    print("\nInstagram\n")
    ver = ytdlp_version()
    # The Instagram extractor was reworked 2026-06-28; older builds fail with
    # "empty media response" on public reels.
    fresh = ver >= "2026.07.04"
    if not ver:
        need(False, "yt-dlp", "brew install yt-dlp  (needed unless you use Apify)")
    elif fresh:
        say(OK, f"yt-dlp {ver}", "Instagram works without an account")
    else:
        say(BAD, f"yt-dlp {ver}", "too old for Instagram — run: brew upgrade yt-dlp")
        problems += 1
    # Token presence is not the same as Apify working. The account silently hit
    # its monthly spend cap and answered 403 for three days while this check
    # kept reporting OK, which is how 62 notes lost their transcript.
    tok = env("APIFY_TOKEN")
    if not tok:
        optional(False, "APIFY_TOKEN (paid)",
                 "no Apify — yt-dlp + local Whisper handle it", "")
    else:
        used, cap = _apify_usage(tok)
        if used is None:
            say(OPT, "APIFY_TOKEN", "token set, but the account couldn't be checked")
        elif cap and used >= cap:
            say(BAD, f"Apify ${used:.2f} / ${cap:.0f}",
                "monthly cap reached — Apify returns 403 and every reel falls "
                "back to yt-dlp. Raise the limit or wait for the cycle to reset")
            problems += 1
        else:
            pct = f" ({used / cap:.0%} of cap)" if cap else ""
            say(OK, f"Apify ${used:.2f}{pct}", "spoken transcripts available")

    try:
        import transcribe_local
        has_whisper = transcribe_local.available()
    except Exception:  # noqa: BLE001
        has_whisper = False
    optional(has_whisper, "local Whisper",
             "a reel with no Apify transcript keeps NO exact wording "
             "(pip install openai-whisper)",
             "reels get a free transcript even when Apify is unavailable")

    print("\nOptional\n")
    optional(bool(shutil.which("ffmpeg")) and bool(shutil.which("ffprobe")), "ffmpeg",
             "no video frames, so text shown on screen is missed", "frame sampling works")
    try:
        import trafilatura  # noqa: F401
        has_traf = True
    except ImportError:
        has_traf = False
    optional(has_traf, "trafilatura",
             "articles fall back to r.jina.ai, which sends the URL to a third party "
             "(pip install trafilatura)",
             "articles and newsletters are read on this machine")
    optional(bool(env("NOTION_TOKEN") and env("NOTION_DATABASE_ID")), "Notion",
             "notes only go to the local vault + Telegram", "notes sync to Notion")

    print()
    if problems:
        print(f"{problems} thing(s) to fix above, then re-run: python3 doctor.py\n")
        return 1
    print("All good — start it with:  python3 bot.py   (or ./install.sh to run it always)\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
