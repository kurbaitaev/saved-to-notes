# Local transcription: the free path now includes speech

Until now the honest tradeoff in this project was: **without `APIFY_TOKEN` you lose the spoken
transcript.** yt-dlp fetched the video fine, but notes were built from the caption and on-screen text
only. For a list reel that is barely a downgrade; for a talking-head monologue it is most of the content.

[`transcribe_local.py`](../transcribe_local.py) closes that gap with OpenAI Whisper running on your own
machine. No key, no network, no per-reel cost.

```bash
pip install openai-whisper
```

That is the whole setup. `acquire.py` picks it up automatically on the yt-dlp path; if it is missing,
everything behaves exactly as before.

> **numba vs NumPy.** `openai-whisper` pulls in numba, which currently refuses NumPy ≥ 2.5. If
> `import whisper` raises an ImportError mentioning numba, install into a venv pinning `numpy<2.5`.

---

## Benchmark

Measured 2026-08-13 on an Apple M3 (16GB), against transcripts from the paid pipeline on real
Instagram reels.

| | result |
|---|---|
| Word-level similarity vs paid transcript | **97.4–98.4%** |
| `base.en` runtime | ~14s per 30–40s reel |
| `small.en` runtime | ~27s (2.6×), fixes proper nouns |
| Cost | **$0** |

`base.en`'s only substantive error across the test set was hearing *"leather working"* as
*"weatherworking"*. `small.en` got it right. Set `LOCAL_WHISPER_MODEL=small.en` if that matters to you.

### The local transcript was *more* accurate than the paid one

This is the part worth knowing. On one reel the paid pipeline transcribed the closing line as:

> "...put the ball down and get a—"

and, on the strength of its own mis-hearing, classified the video as ending on a deliberate cliffhanger.
Local Whisper heard what the creator actually said:

> **"Put the ball down and get on the mat."**

`no_speech_prob = 0.055`. A complete sentence, verified twice.

The failure mode there is nastier than a simple typo: the model's *analysis field agreed with its own
transcription error*, so the mistake read as independent corroboration. If you build anything on exact
wording, a second independent transcript is cheap insurance — and now it is free.

---

## The failure mode you must know about

**Whisper will transcribe background music as though someone spoke it.**

On a silent reel with a rap track, it produced a fluent verse of lyrics presented as speech. That is
silently-wrong data, which is worse than no data — a note that says "no speech detected" is honest,
while a note quoting song lyrics as the creator's words is a fabrication.

`transcribe()` therefore gates on Whisper's own confidence signals and returns `""` rather than guess:

```python
no_speech_prob > 0.5  AND  avg_logprob < -0.5   # over the majority of segments
```

The margin is genuinely thin — 0.672 on a music-only clip versus 0.623 on real speech — so there is a
second, independent check: a real talking-head reel shares vocabulary with its own on-screen captions,
whereas hallucinated lyrics share almost none. Pass `on_screen_text=` to enable it.

Callers should treat `""` as "no speech" and fall back to caption plus on-screen text, which is exactly
what the pipeline already did without a token.

---

## What is still worth paying for

Being straight about the limits:

| | free path | needs a token |
|---|---|---|
| Video + metadata (caption, author, timestamp) | ✅ yt-dlp | |
| Likes, comments | ✅ yt-dlp | |
| **Spoken transcript** | ✅ **local Whisper** | |
| On-screen text | ✅ frames → the agent reads them | |
| Play counts | ❌ | Apify only |
| Enumerating a whole profile | ❌ (`Unsupported URL`) | Apify only |
| Visual understanding (shot-by-shot, b-roll share) | ❌ no local vision model | a video model |

yt-dlp's Instagram support **needs 2026.07.04 or newer**, and returns `view_count: None` — Instagram
play counts have no free source. **Never add Instagram cookies**; people get permanently banned for
scraping with them, including on their own posts. Public reels do not need them.

### On-screen text, if you ever want it locally

The agent currently reads sampled frames, which works well. If you want OCR text without a model call,
**macOS Vision** (via `pyobjc`) recovered every on-screen string character-for-character in testing at
2–3 fps. **tesseract is not competitive** — it buried the text in garbage and missed a line entirely.
Sample at 2–3 fps rather than 1, or fast captions get skipped.
