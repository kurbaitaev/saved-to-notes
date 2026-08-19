# Saved to Notes — iPhone app

A reader and a review loop over the notes the bot already files. It does **not**
capture links: Telegram does that, and does it reliably. This app exists for the
two things a chat window is bad at — reading 200+ notes, and lifting an exact
script out of one for a remake.

## How it gets your notes

Straight from Notion, with no server in between. The pipeline that *writes*
notes needs yt-dlp, ffmpeg and a headless agent and stays on the Mac; reading
them needs none of that. Moving the pipeline to a VPS would be a regression —
Instagram blocks datacenter IPs far harder than home ones, which would break
yt-dlp and force you back onto paid Apify.

## Running it in the simulator

```bash
./configure.sh                      # copies NOTION_TOKEN out of ../.env
open SavedToNotes.xcodeproj         # then just run
```

`configure.sh` writes `Sources/Secrets.swift`, which is gitignored. The token is
never in a tracked file.

Launch flags for checking a screen without tapping through the app:

```
--open review              # start on the Review tab
--open review-revealed     # ...already past the answer step
--open note:forbes         # push the first note whose title matches
```

## Review questions

The app never invents a question. People who write their own quiz questions get
no benefit from answering them and tend to do *worse* than if they had reread,
because they aim at the wrong material (Myers, Hausman & Rhodes 2024). So the
question comes from the agent.

**New notes get one automatically** — the bot writes it at save time, into the
note's frontmatter and the `Review question` column in Notion.

Notes saved before that shipped need a backfill, oldest first:

```bash
python3 ../review_questions.py --limit 30
```

The rules both paths follow live in `review.py`, not in the prompt file. Notes
too thin to support a real question get none, and are skipped in review rather
than faked.

A note becomes reviewable **7 days** after it was saved, and the ladder is
10 → 30 → 90 days on recall, 3 days on a miss. Deliberately loose: the penalty
for too *short* a gap is far larger than for one that is too long, so precision
buys much less than showing up does.

## TestFlight

```bash
./release.sh            # archive, export, validate
./release.sh upload     # ...and send it
```

Signing is manual on purpose. Automatic signing resolves to a *development*
profile, which requires a registered device; an App Store profile does not.

One-time setup already done on the account:

- bundle id `com.kurbaitaev.savedtonotes`
- provisioning profile `SavedToNotes App Store` (App Store, team A58FFUY6DF)

The only step Apple does not allow over the API is creating the app record
itself — `POST /v1/apps` returns *"The resource 'apps' does not allow 'CREATE'"*.
That one is done once, by hand, at
[appstoreconnect.apple.com](https://appstoreconnect.apple.com) → Apps → **+**,
picking the bundle id above.
