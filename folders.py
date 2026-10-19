#!/usr/bin/env python3
"""The category taxonomy — one definition, used everywhere.

Every note gets exactly ONE category, so it has a single home on disk (the
vault folder) and a single value in Notion. The category answers "what will I
DO with this next", which is how saves are looked for. What a note is *about*
is the separate, overlapping axis in topics.py; Area is derived from topics.

Two families share one list because they share one database:

- KNOWLEDGE categories arrive through the Telegram bot and are used in Notion.
- REAL_LIFE categories (buy, visit, attend, cook, move) belong to the iOS app,
  which reads the same database filtered to them. A real-life save sent to the
  bot therefore lands in the app automatically, and vice versa: routing is
  just categorisation.

The module is still called `folders` (and the JSON field `folder`) because the
category IS the folder; renaming every call site would buy nothing.

Kept in its own module because the rules are consumed in three places that
must agree: the prompt sent to the model, the JSON schema that constrains its
answer, and the validator that catches anything invalid.
"""

import re

# --- knowledge (Telegram -> Notion) ---
IDEA = "Idea"
EXPLAINER = "Explainer"
HOW_TO = "How-to"
CRAFT = "Craft"
TOOL = "Tool"
PROMPT_BUILD = "Prompt & Build"
READ_WATCH = "Read & Watch"
QUOTE = "Quote"
OPPORTUNITY = "Opportunity"
NEWS = "News & Takes"
# --- real life (share sheet -> app) ---
BUY = "Buy"
VISIT = "Visit"
ATTEND = "Attend"
COOK = "Cook"
MOVE = "Move"

KNOWLEDGE = [IDEA, EXPLAINER, HOW_TO, CRAFT, TOOL, PROMPT_BUILD, READ_WATCH, QUOTE,
             OPPORTUNITY, NEWS]
REAL_LIFE = [BUY, VISIT, ATTEND, COOK, MOVE]
FOLDERS = KNOWLEDGE + REAL_LIFE
DEFAULT = IDEA  # used only when the model returns nonsense

DESCRIPTIONS = {
    IDEA: "a perspective, argument, story or observation you could retell or remake "
          "in your own words (most thoughts, opinions, life lessons, personal stories)",
    EXPLAINER: "explains how or why something works: science, the brain, psychology, "
               "economics, history, a mental model or concept",
    HOW_TO: "a method or steps you can follow yourself: habits, learning methods, "
            "journaling, speaking, career moves, life skills (not content-making, "
            "not exercise)",
    CRAFT: "technique for making content: hooks, scripts, formats, storytelling, "
           "filming, editing, captions, posting, growth, personal brand — including "
           "lists of hooks, formats or post ideas",
    TOOL: "a specific app, website, repo, AI model, Claude skill, MCP or extension you "
          "would open or install — including lists of tools or sites",
    PROMPT_BUILD: "exact prompt text to copy, or a recipe for building or automating "
                  "something with AI (agents, pipelines, workflows, vibe-coded apps)",
    READ_WATCH: "books, essays, Substacks, articles, YouTube channels or videos, "
                "lectures, podcasts, people to follow",
    QUOTE: "the value is the exact words of a person, a verse or a dua",
    OPPORTUNITY: "something to apply to or reach out to: investors, funds, accelerators, "
                 "grants, fellowships, programs, competitions, jobs",
    NEWS: "a current event, launch, deal or market move, and commentary on it",
    BUY: "a product to buy: gadget, gear, clothing, gift, household item (NOT a book)",
    VISIT: "a place to go: café, restaurant, bar, shop, gym, park, viewpoint, "
           "neighbourhood, city, hotel, travel destination",
    ATTEND: "a dated event to go to: meetup, conference, concert, fight night, "
            "festival, exhibition, class",
    COOK: "a recipe, drink or food to make",
    MOVE: "a mobility, stretching or workout routine you would do along with the video, "
          "at home or in a gym (NOT sport-specific training plans, technique or drills "
          "for a martial art or sport — those are How-to)",
}

# The tie-breaks are the whole point: they are the crossover decisions, made once.
RULES = f"""\
## Category (exactly one — this is where the note is filed)

Pick the ONE category for what the viewer would DO with this next — not its
subject and not its format.

Knowledge:
{chr(10).join(f'- **{c}** — {DESCRIPTIONS[c]}' for c in KNOWLEDGE)}

Real life (these go to the phone app):
{chr(10).join(f'- **{c}** — {DESCRIPTIONS[c]}' for c in REAL_LIFE)}

Tie-breaks, in order:

1. **Real life wins.** If the save is a thing to buy, a place, a dated event, a
   recipe or an exercise to do, use that real-life category even if it is framed
   as a tip ("the best café in SF" → {VISIT}; "3 moves for tight hips" → {MOVE}).
2. **A list is not a category.** File a list by what is IN it: hooks or formats →
   {CRAFT}; books, videos, Substacks → {READ_WATCH}; investors or programs →
   {OPPORTUNITY}; apps or sites → {TOOL}; places → {VISIT}; products → {BUY}.
3. **Books are {READ_WATCH}, never {BUY}.**
4. **{TOOL} vs {PROMPT_BUILD}.** You'd open or install the thing → {TOOL}. You'd
   copy text or rebuild a workflow (even one built on a named tool) → {PROMPT_BUILD}.
5. **{CRAFT} vs {HOW_TO}.** About making or growing content → {CRAFT}. Any other
   method → {HOW_TO}.
6. **{QUOTE} vs {IDEA}.** The exact words of a person are the point → {QUOTE}. The
   argument is the point, and you'd retell it in your own words → {IDEA}.
7. **{IDEA} vs {EXPLAINER}.** A perspective or opinion → {IDEA}. Facts or a
   mechanism → {EXPLAINER}. Training theory you can't follow along with →
   {EXPLAINER}; a routine you can → {MOVE}. A sport's training plan, schedule,
   technique or drill (judo, wrestling, BJJ, boxing…) → {HOW_TO}, not {MOVE}:
   {MOVE} is only routines a person would follow along with at home or in a gym.
8. **{ATTEND} vs {VISIT}.** Has a date → {ATTEND}. Otherwise → {VISIT}.
9. Never invent a category and never leave it blank — worst case use **{DEFAULT}**.
"""


# Whole-word matching, deliberately: a substring check once put "fundraising"
# under the AI folder because it contains "ai". Order matters: specific first.
_HINTS = [
    (PROMPT_BUILD, r"prompt\w*|workflow\w*|build|automat\w*|pipeline|agent\w*"),
    (READ_WATCH, r"read\w*|watch\w*|book\w*|podcast\w*|video\w*|channel\w*|substack\w*|essay\w*|lecture\w*"),
    (OPPORTUNITY, r"opportunit\w*|investor\w*|fund\w*|vc|grant\w*|fellowship\w*|accelerator\w*|program\w*|apply"),
    (TOOL, r"tool\w*|app|apps|software|site\w*|website\w*|repo\w*|ai"),
    (CRAFT, r"craft|content|reel\w*|hook\w*|script\w*|caption\w*|creator|format\w*"),
    (HOW_TO, r"how[- ]?to|tutorial|guide|steps?|method"),
    (EXPLAINER, r"explain\w*|educational|science|concept\w*"),
    (QUOTE, r"quote\w*|quotation"),
    (NEWS, r"news|take\w*|opinion"),
    (BUY, r"buy|product\w*|shop\w*|gear|gadget\w*"),
    (VISIT, r"visit|place\w*|cafe|café|restaurant\w*|travel|destination\w*"),
    (ATTEND, r"attend|event\w*|meetup\w*|conference\w*|concert\w*"),
    (COOK, r"cook\w*|recipe\w*|food"),
    (MOVE, r"move|exercise\w*|workout\w*|mobility|stretch\w*|training"),
    (IDEA, r"idea\w*|thought\w*|mindset|story|stories"),
]


def normalize(value) -> str:
    """Map whatever the model returned onto a real category."""
    v = str(value or "").strip()
    if not v:
        return DEFAULT
    low = v.lower()
    for f in FOLDERS:
        if low == f.lower():
            return f
    # Tolerate near-misses ("How to", "Tools", "Recipe") rather than dumping an
    # otherwise-good note into the default.
    for folder, pattern in _HINTS:
        if re.search(rf"\b(?:{pattern})\b", low):
            return folder
    return DEFAULT


def is_real_life(value) -> bool:
    return normalize(value) in REAL_LIFE


def safe_dirname(folder: str) -> str:
    """Category name as a filesystem directory.

    Deliberately identical to the Notion value — an earlier version rewrote
    "&" to "and", so the same folder was called "Tools and AI" on disk and
    "Tools & AI" in Notion, which just looks like two different folders.
    Only path separators are unsafe in a directory name.
    """
    return normalize(folder).replace("/", "-")


# Added to the agent's context when a link arrives through the Afterscroll app
# (share button, shortcut, Paste link) rather than Telegram. Sharing to the app
# IS the person saying "this is a real-life thing"; the first mobility reel sent
# that way was filed as an Explainer because it also explained why.
APP_HINT = (
    "SAVED VIA THE AFTERSCROLL APP: the person shared this to their real-life app "
    f"(things to {BUY.lower()}, places to {VISIT.lower()}, events to {ATTEND.lower()}, "
    f"recipes to {COOK.lower()}, workouts to do). Choose a real-life category "
    f"({', '.join(REAL_LIFE)}) whenever the content plausibly fits one — a mobility or "
    f"exercise reel that shows moves is {MOVE} even if it also explains why they matter. "
    "Use a knowledge category only if nothing in it can be bought, visited, attended, "
    "cooked or done. SPEED MATTERS for these saves — the person is waiting in the app: "
    "do NOT search the web or verify links; leave every item `verified: false` with an "
    "empty `link` unless the post itself shows the URL.")
