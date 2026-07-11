"""Signal message formatting + reply classification for the human-approval gate.

This is the safety seam between Aetheria's drafted posts and what actually
goes out on @Soveryn_AI: nothing posts without a human (Jon) approving over
Signal. classify_reply is deliberately biased to safety — only an exact,
recognized affirm token approves. Everything else (including anything
ambiguous, unexpected, or empty) is treated as NOT approved: clear reject
tokens reject, and any other non-empty text becomes an edit (Jon's literal
text replaces the post). An empty/whitespace-only reply is a no-op — it must
not approve and there is no text to edit with, so it is reported as a reject
with no reason rather than silently posting or editing-to-blank.
"""

from __future__ import annotations

from typing import Optional, Tuple

from soveryn.agents.presence.drafting import NO_PROVENANCE_STATED, Draft

Decision = Tuple[str, Optional[str]]

_APPROVE_TOKENS = {"y", "yes", "approve", "post"}
_REJECT_TOKENS = {"n", "no", "reject", "skip"}


def format_signal_message(draft: Draft, draft_id: str) -> str:
    """Render a Draft as a Signal message for human approval.

    Shows the draft id, kind, post text, provenance (visibly flagged when
    Aetheria gave none), and — for replies/mentions — the tweet being
    answered.
    """
    lines = [
        f"Draft {draft_id} ({draft.kind})",
        "",
        draft.text,
        "",
    ]

    if draft.based_on == NO_PROVENANCE_STATED:
        lines.append(f"Based on: {NO_PROVENANCE_STATED} ⚠️ NO PROVENANCE STATED")
    else:
        lines.append(f"Based on: {draft.based_on}")

    if draft.in_reply_to is not None:
        lines.append(f"In reply to: https://x.com/i/web/status/{draft.in_reply_to}")

    lines.append("")
    lines.append("Reply y/yes/approve/post to post, n/no/reject/skip to reject "
                  "(optionally 'reject: reason'), or anything else to use your "
                  "text as the new post.")

    return "\n".join(lines)


def classify_reply(text: str) -> Decision:
    """Classify a human's Signal reply into an approve/reject/edit Decision.

    Bias to safety: only exact affirm tokens approve. Only exact reject
    tokens (optionally 'reject: <reason>') reject. Any other non-empty text
    is an edit carrying that literal text as the new post. An empty or
    whitespace-only reply is never approved (and there is no text to build an
    edit from), so it is reported as a no-op reject with no reason.
    """
    stripped = text.strip()

    if not stripped:
        return ("reject", None)

    normalized = stripped.lower()

    if normalized in _APPROVE_TOKENS:
        return ("approve", None)

    if normalized in _REJECT_TOKENS:
        return ("reject", None)

    if normalized.startswith("reject:"):
        reason = stripped.split(":", 1)[1].strip()
        return ("reject", reason or None)

    return ("edit", stripped)
