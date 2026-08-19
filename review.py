#!/usr/bin/env python3
"""The rules for writing a review question — one definition, two readers.

The bot writes a question at save time; review_questions.py backfills notes that
predate the field. Both read RULES from here, because the last time guidance was
hand-copied into agent_prompt.md the prompt kept teaching a folder name that had
already been renamed.

Why the tool writes the question rather than the reader: people who write their
own quiz questions get no benefit from answering them, and tend to do *worse*
than if they had simply reread — they aim at material that isn't what matters
(Myers, Hausman & Rhodes 2024, J. Exp. Psych: Applied 30(2), 241-257).

Why higher-order rather than factual: factual questions buy back the fact and
little else, while higher-order ones generalise to related and even unrelated
higher-order material (Hamaker 1986). Pan & Rickard (2018) put the same finding
from the other side — without elaborated retrieval, transfer corrects to
roughly zero.
"""

MAX_LEN = 220

RULES = """\
## Review question

One question the reader should be able to answer from memory weeks from now,
without the note in front of them.

- **Higher-order, not recall.** Ask why something works, when it would fail, or
  how it changes a decision. Never "what did the post say".
- **Answerable from this note alone.** Never require outside knowledge.
- One sentence, under 25 words, ending in a question mark.
- Address the reader as "you".
- If the note is too thin to support a real question (a bare quote, a list with
  no reasoning), return an empty string. A missing question is fine; a hollow
  one wastes the only card of the day.
"""


def clean(value) -> str:
    """Keep it only if it is actually a question. A statement here would be
    shown to the reader as a prompt to answer, which makes no sense."""
    q = " ".join(str(value or "").split())
    if not q.endswith("?") or len(q) < 15:
        return ""
    return q[:MAX_LEN]
