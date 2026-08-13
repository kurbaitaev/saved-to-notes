"""Local speech-to-text, so the spoken transcript stops being the paid part.

Without APIFY_TOKEN the pipeline downloads the video fine but has no speech, and
notes fall back to the caption and on-screen text. This module fills that gap
with OpenAI Whisper running on the machine: no key, no network, no per-reel cost.

Benchmarked against the Apify/Gemini transcripts on real reels (2026-08-13):
97.4-98.4% word-level similarity, and MORE accurate than the paid path on the
cases where they disagreed. `base.en` runs ~14s per 30-40s reel on an M3;
`small.en` is ~2.6x slower and fixes proper nouns ("leather working" that
base.en heard as "weatherworking").

Install (optional — the pipeline degrades gracefully without it):

    pip install openai-whisper

Note: openai-whisper pulls numba, which currently refuses NumPy >= 2.5. If
`import whisper` raises an ImportError mentioning numba, install into a venv
pinning `numpy<2.5`.

THE FAILURE MODE THAT MATTERS
-----------------------------
Whisper will happily transcribe *song lyrics from background music* as though
someone spoke them. On a silent reel with a rap track it invented a verse. That
is silently-wrong data, which is worse than no data, so `transcribe()` gates on
Whisper's own confidence signals and returns "" rather than guess. Callers
should treat "" as "no speech" and fall back to caption + on-screen text, which
is exactly what the pipeline already does without a token.
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

log = logging.getLogger(__name__)

# Whisper reports these per segment. A segment that is probably-not-speech AND
# low-confidence is almost always background music being hallucinated into words.
# Thresholds measured on real reels; the margin is genuinely thin (0.672 on a
# music-only clip vs 0.623 on real speech), which is why the vocabulary
# cross-check below matters as much as the numbers.
NO_SPEECH_PROB_MAX = 0.5
AVG_LOGPROB_MIN = -0.5

DEFAULT_MODEL = os.environ.get("LOCAL_WHISPER_MODEL", "base.en").strip()


def available() -> bool:
    """True when local transcription can actually run."""
    if not shutil.which("ffmpeg"):
        return False
    try:
        import whisper  # noqa: F401
    except Exception:
        return False
    return True


def _extract_audio(video_path: str, out_wav: str) -> bool:
    """16 kHz mono WAV — what Whisper wants, and small."""
    cmd = [
        "ffmpeg", "-nostdin", "-y", "-loglevel", "error",
        "-i", video_path, "-vn", "-ac", "1", "-ar", "16000", out_wav,
    ]
    try:
        subprocess.run(cmd, check=True, stdin=subprocess.DEVNULL,
                       stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=120)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        log.warning("audio extraction failed: %s", e)
        return False
    return Path(out_wav).exists() and Path(out_wav).stat().st_size > 1000


def _looks_like_music(segments: list) -> bool:
    """Whisper singing along to the backing track instead of hearing a person.

    Judged over the whole clip rather than per segment: a real monologue has
    confident segments throughout, while a music-only clip is uniformly
    unconfident even when it produces fluent-looking text.
    """
    if not segments:
        return True
    bad = sum(
        1 for s in segments
        if (s.get("no_speech_prob", 0.0) > NO_SPEECH_PROB_MAX
            and s.get("avg_logprob", 0.0) < AVG_LOGPROB_MIN)
    )
    return bad >= max(1, len(segments) // 2)


def transcribe(video_path: str, model_name: str | None = None,
               on_screen_text: str = "") -> str:
    """Return the spoken transcript, or "" when there is no speech.

    `on_screen_text`, when supplied, is used as a sanity check: a genuine
    talking-head reel shares vocabulary with its own captions, whereas
    hallucinated song lyrics share almost none. It only ever downgrades a
    borderline result, never upgrades one.
    """
    if not available():
        log.info("local whisper unavailable — skipping (install openai-whisper to enable)")
        return ""

    import whisper

    model_name = (model_name or DEFAULT_MODEL).strip()
    with tempfile.TemporaryDirectory() as td:
        wav = str(Path(td) / "audio.wav")
        if not _extract_audio(video_path, wav):
            return ""
        try:
            model = whisper.load_model(model_name)
            result = model.transcribe(wav, fp16=False)
        except Exception as e:
            log.warning("whisper failed (%s) — continuing without a transcript", e)
            return ""

    segments = result.get("segments") or []
    text = (result.get("text") or "").strip()
    if not text:
        return ""

    if _looks_like_music(segments):
        log.info("local whisper: audio reads as music rather than speech — "
                 "returning no transcript instead of guessing")
        return ""

    # Borderline confidence plus no vocabulary overlap with the on-screen text
    # is the other shape of the same failure.
    if on_screen_text:
        spoken = {w for w in text.lower().split() if len(w) > 4}
        shown = {w for w in on_screen_text.lower().split() if len(w) > 4}
        if spoken and shown and not (spoken & shown):
            weak = sum(1 for s in segments if s.get("no_speech_prob", 0.0) > 0.3)
            if weak >= max(1, len(segments) // 2):
                log.info("local whisper: transcript shares no vocabulary with the "
                         "on-screen text and confidence is weak — discarding")
                return ""

    log.info("local whisper (%s): %d chars", model_name, len(text))
    return text


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        sys.exit("usage: python transcribe_local.py <video> [model]")
    out = transcribe(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
    print(out if out else "(no speech detected)")
