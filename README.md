# saved-to-notes

Your saved posts are a graveyard. Turn them into something you'll actually read.

Send a link — Instagram reel, carousel or photo, an X post, a TikTok — to your own Telegram bot. Get back a clean, permanent note: what it actually said, word for word, plus real verified links to every book, podcast, tool and concept it mentioned. Filed into a folder, searchable, and still yours after the original post is deleted.

You bookmark something useful, and three weeks later you can't find it, can't remember which one had the book recommendation, and half of them are gone. That's the problem this exists for.

**It reads the pictures too.** A reel that shows a book cover on screen but never says the title still gets that book in the note, with a link. Carousels with no audio at all are read slide by slide.

Everything lands in a local markdown vault (Obsidian-compatible) organised into folders, optionally a Notion database, and back in your Telegram chat.

> **Runs on your Mac, for you.** A single-user personal tool, not a hosted service. Your saves and notes never leave your machine except to the APIs you configure.

## What a note looks like

From a reel where an investor lists books he gives away:

> **Bill Gurley's 3 Most-Gifted Books**
>
> 📌 **Recommended**
> 1. ✅ [Complexity: The Emerging Science at the Edge of Order and Chaos](https://www.goodreads.com/book/show/337123.Complexity) — M. Mitchell Waldrop
> 2. ✅ [Mr. China](https://www.goodreads.com/book/show/109705.Mr_China) — Tim Clissold
> 3. ✅ [Range: Why Generalists Triumph in a Specialized World](https://www.goodreads.com/book/show/41795733-range) — David Epstein
> 4. ✅ [Runnin' Down a Dream: How to Thrive in a Career You Actually Love](https://www.goodreads.com/book/show/237134711-runnin-down-a-dream) — Bill Gurley
>
> 💾 *Curated reading list from a top venture capitalist…*
> 📄 Full transcript (collapsed)

The fourth book is never spoken aloud — it's on a cover shown on screen. ✅ means the link was checked; ⚠️ means it couldn't be confirmed, and the note says so rather than guessing.

## How it works

`bot.py` is a thin Telegram poller. Per link:

1. **Acquire** ([acquire.py](acquire.py)) — deterministic Python, no model involved. Downloads the media and metadata, and samples frames from the video with ffmpeg so on-screen text can be read. Carousels and photo posts download every image.
2. **Reason** — spawns a headless [Claude Code](https://claude.com/product/claude-code) agent (`claude -p`, instructions in [agent_prompt.md](agent_prompt.md)). It reads the transcript and every image, detects what kind of content it is, and web-searches to verify each link. It returns exactly one JSON object; it writes no files.
3. **Save** — `bot.py` renders the note and writes it to the vault, to Notion ([notion.py](notion.py)), and to Telegram. A ledger prevents reprocessing (send `/force` to redo).

Acquisition is kept out of the agent on purpose: it's the fragile, infrastructure-heavy part, and it belongs in code you can debug.

## Setup

**Requires macOS** (launchd for the service, Apple's ffmpeg build, Claude Code CLI) and **Python 3.10+**.

```bash
git clone https://github.com/kurbaitaev/saved-to-notes.git
cd saved-to-notes
pip install -r requirements.txt
brew install yt-dlp ffmpeg
cp .env.example .env
python3 doctor.py          # tells you exactly what's still missing
```

`doctor.py` is the fastest way to find out whether you're ready — it checks every dependency and prints the fix for each.

You need three things in `.env`:

1. **`TELEGRAM_BOT_TOKEN`** — message [@BotFather](https://t.me/BotFather), send `/newbot`, copy the token.
2. **Claude access** — either run `claude` once and `/login` (uses your Claude subscription), or set `ANTHROPIC_API_KEY` (bills per token, and never expires — see [Which to use](#claude-login-vs-api-key)).
3. **`ALLOWED_USER_IDS`** — start the bot, send it `/start`, and it replies with your numeric id. Put that in `.env` and restart. **The bot refuses everyone until you do this**, on purpose: an open bot lets anyone who finds the token run processes on your Mac.

Then:

```bash
python3 bot.py
```

Send it a reel. The first note takes 1–3 minutes.

To try the pipeline without Telegram:

```bash
python3 bot.py --test "https://www.instagram.com/reel/..."
```

### One-time trust step

The agent's permissions live in [.claude/settings.json](.claude/settings.json), and Claude Code ignores them in a directory you haven't trusted. Run `claude` once inside the project folder and accept the trust prompt — otherwise web search is silently disabled and links come back unverified. The watchdog re-checks this and repairs it if a future login resets it.

## Keeping it running

```bash
./install.sh        # installs two launchd services: the bot + a watchdog
./ctl.sh status     # running? pid? last exit code
./ctl.sh restart    # after editing bot.py or agent_prompt.md
./ctl.sh tail       # follow the log
```

The watchdog ([watchdog.py](watchdog.py)) checks every 90 minutes that the bot is alive *and* still polling, restarts it if not, and sends you a Telegram ping either way. It also repairs the trust flag above and warns you if your Claude login has genuinely expired.

These are **LaunchAgents**, so they only run while you're logged in and the Mac is awake. That's a requirement, not an oversight: the Claude CLI reads its login from your login keychain, which isn't available to a system daemon.

If a reel is interrupted mid-processing (restart, sleep, crash), it's recorded in `pending.json` and retried on the next start — up to three times, then it tells you it gave up.

## Configuration

Everything optional lives in [.env.example](.env.example) with comments. The ones worth knowing:

| Variable | Default | What it does |
|---|---|---|
| `APIFY_TOKEN` | *(unset)* | Paid, and now optional for almost everything — see below. Its one remaining exclusive is following an X **thread** past its first post. |
| `NOTION_TOKEN` + `NOTION_DATABASE_ID` | *(unset)* | Sync notes to a Notion database. Skipped silently if unset. |
| `CLAUDE_MODEL` | *(your default)* | e.g. `claude-sonnet-4-6`. A stronger model gets links right more often. |
| `VIDEO_FRAMES` | `6` | Frames sampled per video for on-screen text. `0` disables. |
| `RICH_MESSAGE` | `1` | Telegram Rich Messages. Set `0` for plain HTML. |
| `SERVICE_LABEL` | `com.<user>.saved-to-notes` | launchd service name. |

### Free vs. paid

**It runs with no paid services at all.** yt-dlp fetches public reels anonymously, ffmpeg samples the frames, and the agent reads them.

The **spoken transcript** used to be the one thing you lost without `APIFY_TOKEN`. It isn't any more — `pip install openai-whisper` and [transcribe_local.py](transcribe_local.py) transcribes on your machine, free. Benchmarked at **97.4–98.4%** word similarity against the paid transcript, and on the one reel where they disagreed the local transcript was the correct one. See [docs/local-transcription.md](docs/local-transcription.md).

It refuses to guess: on a silent reel with background music Whisper will happily "transcribe" the song lyrics as speech, so `transcribe()` gates on confidence and returns nothing instead. A note that says "no speech detected" beats a note quoting a rap verse as the creator's words.

**X posts are free too.** They go through [FxTwitter](https://github.com/FixTweet/FxTwitter), the open-source embed API — no key, no account. It returns the complete post text where Twitter's own public syndication endpoint truncates: 932 characters against 268 on a real saved post. It also downloads attached photos and video, and the video is transcribed locally like any other. As with the article fallback, this asks a third party about a public post ID.

What still needs `APIFY_TOKEN`: following an X **thread** past its first post (FxTwitter answers about one post), Instagram **play counts** (yt-dlp returns `view_count: None`), and enumerating a whole profile. A post with replies says so in the note rather than quietly keeping only the first part.

yt-dlp's Instagram support **needs 2026.07.04 or newer** — older builds fail with "empty media response". `doctor.py` checks the version for you.

**Do not add Instagram cookies.** People get their accounts permanently banned for scraping with them, including on their own posts. Public reels don't need them.

### Articles and newsletters

Send a blog post, an essay or a Substack link and you get the same kind of note, plus the full article text kept in the vault — so a piece that later goes behind a paywall is still readable in your own notes.

A link that isn't a known media host is read as a page. [Trafilatura](https://trafilatura.readthedocs.io/) does the extraction locally: no browser, no API key, nothing leaves the machine. When a page is JavaScript-only and Trafilatura comes back empty, [Jina Reader](https://jina.ai/reader/) is the fallback — it's free and keyless, but it fetches the page from *their* servers, which means telling a third party what you saved. That's why it's second rather than first, and why `pip install trafilatura` is worth doing.

PDFs are skipped deliberately. A half-extracted PDF is worse than an honest failure.

### Claude login vs. API key

| | Subscription (`claude` → `/login`) | `ANTHROPIC_API_KEY` |
|---|---|---|
| Cost | Included in your plan | ~$0.05–0.10 per reel |
| Expiry | **Expires every few months** — the bot stops until you log in again | Never |
| Best for | Trying it out | Leaving it running |

The watchdog warns you when a login expires, but the API key is the set-and-forget option.

## Notion setup (optional)

Create a database, share it with an internal integration ([notion.so/my-integrations](https://www.notion.so/my-integrations)), and put the token and database id in `.env`.

You don't have to match a schema. `notion.py` reads your database's live columns and only fills the ones that exist, so you can rename and add freely. It looks for: `Source` (url), `Date` (date), `Author`, `Platform`, `Summary`, `Hook / key idea`, `Takeaways`, `Category` (multi-select), `Items`. **`Source` as a url column is the one worth adding** — deduplication and date preservation use it.

## Security notes

Reel captions, transcripts and web pages are **untrusted text written by strangers**, and they go into a prompt for an agent with tools. Two consequences:

- The agent's permission list is deliberately minimal — read the downloaded images, search the web, return JSON. **No shell access, no write access.** If you add tools there, a hostile caption can reach them.
- `ALLOWED_USER_IDS` fails closed.

The bot's own logs are gitignored, and `.env` is never committed. Telegram request URLs contain your bot token, so httpx logging is turned down to keep it out of the log file.

## Limitations

- **macOS only.** The service layer is launchd; the rest is portable but untested elsewhere.
- **Instagram and X are first-class.** Instagram uses Apify with yt-dlp as fallback (the fallback now transcribes locally, so it is no longer a downgrade for speech); X/Twitter uses Apify's tweet scraper, which handles text, photo and video posts — yt-dlp only understands tweets containing video. YouTube and TikTok go through yt-dlp and mostly work. Articles and newsletters work too (see below), but **PDFs don't** — they're excluded on purpose rather than half-read.
- **Acquisition breaks periodically.** Instagram changes things; yt-dlp catches up within days. Keep it updated.
- **Single user.** One person, one machine, a JSON-file ledger. Sharing it with friends means one install each.
- Verified links are checked by an LLM with web search. ✅ means it found a canonical page — not a human guarantee.

## License

MIT — see [LICENSE](LICENSE).
