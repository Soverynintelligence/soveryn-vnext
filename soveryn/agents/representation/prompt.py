from __future__ import annotations

_FORMAT_LINE = "MODE | CONFIDENCE | CONTENT | [node:ID],[node:ID]"

_TEMPLATE = """\
You are a bare analytical reasoning engine. Your task is to reason over recent \
conversation and prior conclusions about {subject} and infer {subject}'s \
ENDURING traits, values, preferences, and patterns of thought — a lasting model \
of who {subject} is, NOT a log of what just happened.

This is NOT roleplay or persona performance. Draw only what the cited premises \
directly support. If a premise does not exist for a claim, do not state the claim.

---
RECENT BRIEFING (each line is a witness node prefixed with its ID):
{briefing}

---
PRIOR CONCLUSIONS (each line is a prior conclusion node prefixed with its ID):
{prior_conclusions}

---
REASONING MODES:
- deductive  — conclusion follows necessarily from the premises
- inductive  — conclusion is a reasonable generalisation from repeated evidence
- abductive  — conclusion is the best explanation for the observed pattern

OUTPUT RULES:
1. One conclusion per line, exactly this format:
   {format_line}
2. MODE must be one of: deductive, inductive, abductive
3. CONFIDENCE must be a plain natural-language phrase (e.g. "confident", \
"fairly confident", "tentative", "low confidence") — NOT a number.
4. CONTENT is the conclusion statement.
5. The final field must contain AT LEAST ONE premise node cited as [node:ID], \
taken from the briefing or prior conclusions above. Lines with no cited premise \
are invalid and will be discarded.
6. If a new conclusion CONTRADICTS a prior one, restate it with the corrected \
content — the writeback layer will handle superseding the old node.
7. Output ONLY the conclusion lines. No preamble, no commentary, no blank lines.
8. Conclusions are descriptive, not prescriptive — describe {subject} as observed, \
not as you think they should be.
9. Conclude ONLY durable characteristics — traits, values, preferences, recurring \
patterns evidenced in the material. Do NOT record transient events, logistics, or \
one-off facts (e.g. "arrived at the terminal", "finished today's tasks", "fixed a \
bug today"). Those are noise tomorrow. If the material holds only passing events \
with no durable signal about {subject}, output nothing at all.
""".strip()


def render_representation_prompt(
    *,
    subject: str,
    briefing: str,
    prior_conclusions: str,
) -> str:
    """Return the full reasoning prompt for the cognition surface."""
    return _TEMPLATE.format(
        subject=subject,
        briefing=briefing,
        prior_conclusions=prior_conclusions,
        format_line=_FORMAT_LINE,
    )
