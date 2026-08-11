#!/usr/bin/env python3
"""Topics — the cross-cutting filter axis.

A note lives in exactly one folder (see folders.py) but is *about* several
things. Folders answer "where does this live"; topics answer "show me
everything about investors". Both are needed: investor material was scattered
across five folders with no way to pull it together.

The vocabulary is CLOSED. The agent already emits free-form `tags`, and 191
notes produced 301 distinct ones — useful as raw material, useless as a filter.
Free tags stay in the note; topics are the curated subset you can actually
filter on.

Derived from the tag histogram of the existing vault, so it describes what is
really saved rather than what might be.

Editing the list: change it HERE, never by renaming an option in Notion. That
mistake is what left the database with both "Motivation" and "Mindset" as
folder values, splitting one folder across two names.
"""

import re

# topic -> the tags and phrasings that should map onto it
ALIASES: dict[str, tuple[str, ...]] = {
    "investors-fundraising": (
        "fundraising", "venture-capital", "vc", "investors", "investor", "angel", "angels",
        "pre-seed", "preseed", "seed", "series-a", "pitching", "pitch", "pitch-deck",
        "accelerator", "accelerators", "incubator", "fellowship", "fellowships",
        "grants", "funding", "cap-table", "valuation", "term-sheet", "yc"),
    "startup-building": (
        "startup", "startups", "founder", "founders", "business", "business-model",
        "monetization", "revenue", "sales", "b2b", "saas", "hiring", "team",
        "product", "product-market-fit", "operations", "equity"),
    "content-creation": (
        "content-creation", "content", "content-strategy", "filming", "editing", "video",
        "production", "capcut", "b-roll", "camera", "batching", "formats", "reels", "reel"),
    "hooks-storytelling": (
        "hooks", "hook", "storytelling", "story", "narrative", "scripting", "script",
        "copywriting", "copy", "virality", "retention", "openers"),
    "platform-growth": (
        "instagram", "youtube", "tiktok", "linkedin", "twitter", "x", "substack",
        "telegram", "threads", "growth", "algorithm", "audience", "followers", "smm",
        "distribution", "seo"),
    "personal-brand": (
        "personal-brand", "branding", "brand", "creator-economy", "influencer",
        "authenticity", "positioning", "founder-brand"),
    "marketing-ads": (
        "marketing", "ads", "advertising", "ad-formats", "meta-ads", "funnels", "funnel",
        "brand-deals", "sponsorship", "pr", "outreach", "cold-email"),
    "ai-tools": (
        "ai", "ai-tools", "llm", "llms", "claude", "chatgpt", "gpt", "automation",
        "no-code", "agents", "prompts", "prompting", "tools", "apps", "software", "mcp"),
    "productivity": (
        "productivity", "focus", "deep-work", "time-management", "time-blocking",
        "procrastination", "planning", "systems", "workflow", "organization"),
    "habits-discipline": (
        "habits", "habit", "discipline", "consistency", "willpower", "routine",
        "routines", "accountability", "self-control"),
    "mindset": (
        "mindset", "motivation", "motivational", "resilience", "identity", "ego",
        "fear", "confidence", "growth-mindset", "self-belief", "purpose", "ambition",
        "quotes", "quote", "inspiration"),
    "psychology-brain": (
        "psychology", "neuroscience", "brain", "cognitive-bias", "biases", "memory",
        "attention", "behavior", "behaviour", "dopamine", "emotions"),
    "learning-education": (
        "learning", "education", "studying", "study", "language-learning", "duolingo",
        "note-taking", "notes", "knowledge", "curiosity", "school", "college", "essays"),
    "books-reading": ("books", "book", "reading", "reading-list", "literature", "fiction"),
    "writing": ("writing", "journaling", "journal", "essay", "newsletter", "blogging"),
    "health": (
        "health", "fitness", "sleep", "stress", "burnout", "energy", "nutrition",
        "exercise", "adhd", "mental-health", "wellbeing"),
    "philosophy-faith": (
        "philosophy", "stoicism", "faith", "religion", "islam", "meaning", "wisdom"),
    "money-finance": (
        "money", "finance", "financial-literacy", "investing", "wealth", "taxes",
        "economics", "ipo", "markets"),
    "career-life": (
        "career", "life", "relationships", "family", "decision-making", "decisions",
        "goals", "travel", "life-design", "work-life"),
}

TOPICS: list[str] = sorted(ALIASES)
MAX_PER_NOTE = 3

_LOOKUP = {alias: topic for topic, aliases in ALIASES.items() for alias in aliases}
_LOOKUP.update({t: t for t in TOPICS})

RULES = f"""\
## Topics (1–3, from this EXACT list)

Topics are how the reader filters later — "show me everything about investors".
Choose the 1–3 that a person would actually search for to find this note again.

{chr(10).join('- ' + t for t in TOPICS)}

Rules:
- Use ONLY these exact strings. Never invent one; an invented topic is dropped.
- 1–3 per note. Two precise topics beat three vague ones.
- Topics are independent of the folder: a book recommendation about fundraising
  is folder `Startup`, topics `investors-fundraising` + `books-reading`.
- Keep filling `tags` as normal — those stay free-form and are unrelated to this.
"""


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(value or "").strip().lower()).strip("-")


def normalize_list(values) -> list[str]:
    """Map whatever came back onto real topics: alias-resolve, drop invented
    ones, de-duplicate, cap. Never raises — an empty list is a fine answer."""
    if isinstance(values, str):
        values = [values]
    out: list[str] = []
    for v in values or []:
        t = _LOOKUP.get(_slug(v))
        if t and t not in out:
            out.append(t)
    return out[:MAX_PER_NOTE]


def from_tags(tags) -> list[str]:
    """Best-effort topics from a note's free-form tags — used to backfill notes
    written before topics existed, without paying for a model call."""
    return normalize_list(tags)
