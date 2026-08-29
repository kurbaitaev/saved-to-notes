#!/usr/bin/env python3
"""Content fingerprints — catching the same post saved under two links.

URL dedup can't see a repost: "10 Levels of Fake Progress" sits in the vault
twice, June and August, from two different reel URLs with the same content.
A 64-bit simhash of the transcript is enough to catch that at this scale —
comparing one new save against ~250 stored fingerprints is instant, and no
embeddings or index are needed below tens of thousands of notes.
"""

import hashlib
import re


def sig(text: str) -> str:
    """16-hex-char simhash over character 4-grams. '' when there's too little
    text to fingerprint — a signature of near-nothing matches everything."""
    t = re.sub(r"\W+", " ", (text or "").lower()).strip()
    if len(t) < 80:
        return ""
    grams = {t[i:i + 4] for i in range(len(t) - 3)}
    weights = [0] * 64
    for g in grams:
        h = int.from_bytes(hashlib.blake2b(g.encode(), digest_size=8).digest(), "big")
        for b in range(64):
            weights[b] += 1 if (h >> b) & 1 else -1
    return f"{sum(1 << b for b in range(64) if weights[b] > 0):016x}"


def distance(a: str, b: str) -> int:
    """Hamming distance; 64 (no match) when either side has no signature."""
    if not a or not b:
        return 64
    return (int(a, 16) ^ int(b, 16)).bit_count()


# Measured across all 253 fingerprints in this vault (31,878 pairs): the two
# real duplicates sit at distance 3; the closest UNRELATED pair sits at 11.
# Ten catches every true duplicate and admits zero false ones. The cost is
# honest: a repost with real edits can land at 11+ and slip through — better to
# miss one repost than to falsely refuse a genuine save.
SAME = 10
