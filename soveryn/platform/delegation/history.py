"""What happened last time this was asked (delegation memory).

`_find_open_duplicate` stops a second dispatch while one is still LIVE. It
deliberately does not stop a re-dispatch after `failed` or `rejected`, because
retrying is legitimate — the 2026-08-11 substrate attempt fixed the exact
connection leak the 2026-08-07 review named, and a guard that blocked it would
have blocked the correction.

The gap this closes is different: she could re-dispatch, but she did so BLIND.
Nothing put the previous outcome in front of her at the moment she asked again,
so the same direction went out at least seven times between 3 and 13 August.
Two of the rejections say it in Jon's own words — *"already completed! nice work
aetheria had you doing loops"* and *"the slice was already built aetheria was
unaware"*.

So this does not block anything. It answers a question she had no way to ask:
**has this been tried, and what came back?** Refusing would cage the retry that
actually fixed the bug; showing her the review means she can say "rejected for X,
and I have addressed X" — or decide not to ask again.

Matching is loose ON PURPOSE, and measured rather than guessed
--------------------------------------------------------------
Scored against the real store (32 tasks, 8 of them substrate attempts):

    jaccard on objective words   same 0.06-0.39   unrelated up to 0.23
    overlap coefficient          same 0.24-0.72   unrelated up to 0.43
    shared files (scope)         caught 11/28 pairs, unrelated up to 0.50

**No single signal separates them cleanly**, because the work was reworded AND
the target kept moving: soveryn/memory/lattice.py -> lattice_vnext.py ->
memory/substrate.py -> lattice/substrate.py across four attempts at the same
idea. An exact-match guard misses all of it; a strict threshold misses most.

So the threshold is set LOW and both signals are combined. A false positive
costs her one glance at a task that turned out to be unrelated. A false negative
costs another full dispatch, another worktree, another Scotty run, and another
rejection — which is the loop this exists to break. Recall wins.

Rejections are also surfaced on weaker evidence than failures, because a
rejection carries a human decision and a reason, and repeating one wastes Jon's
attention rather than just compute.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

# Measured, not guessed — see the module docstring. Substrate attempts score
# 0.24-0.72 by overlap coefficient; unrelated work reaches 0.43, so there is no
# clean cut. Rejections use the lower bar deliberately.
SIMILARITY_THRESHOLD = 0.30
REJECTED_THRESHOLD = 0.22
MAX_PRIOR_SHOWN = 3

# Words that carry no signal about WHAT is being built.
_STOPWORDS = frozenset({
    "the", "a", "an", "and", "or", "of", "to", "in", "for", "on", "with", "that",
    "this", "is", "are", "be", "it", "as", "at", "by", "from", "into", "create",
    "implement", "add", "make", "new", "file", "files", "core", "simple",
})

_WORD = re.compile(r"[a-z0-9_]+")


def _significant(text: str) -> set[str]:
    return {w for w in _WORD.findall((text or "").casefold())
            if w not in _STOPWORDS and len(w) > 2}


_PATH = re.compile(r"[\w./-]+\.(?:py|md|html|ini|json|sql)")


def _paths(*texts: str) -> set[str]:
    found: set[str] = set()
    for t in texts:
        found |= {p.casefold().lstrip("./") for p in _PATH.findall(t or "")}
    return found


def similarity(a: str, b: str, *, a_scope: str = "", b_scope: str = "") -> float:
    """How much two pieces of work look like the same request.

    Overlap coefficient rather than Jaccard: one objective is often a terse
    restatement of a long one, and Jaccard punishes that length difference
    exactly when the two are most alike.

    Naming the same file is strong evidence and lifts the score, but cannot be
    required — the substrate target was renamed three times across attempts at
    one idea.
    """
    left, right = _significant(a), _significant(b)
    if not left or not right:
        return 0.0
    words = len(left & right) / min(len(left), len(right))

    files_a, files_b = _paths(a, a_scope), _paths(b, b_scope)
    if files_a and files_b and (files_a & files_b):
        shared = len(files_a & files_b) / min(len(files_a), len(files_b))
        return max(words, (words + shared) / 2)
    return words


@dataclass(frozen=True)
class PriorAttempt:
    task_id: str
    status: str
    created_at: str
    objective: str
    review_feedback: str
    similarity: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "status": self.status,
            "created_at": self.created_at,
            "objective": self.objective,
            "review_feedback": self.review_feedback,
            "similarity": round(self.similarity, 2),
        }


def prior_attempts(store, objective: str, *, limit: int = MAX_PRIOR_SHOWN
                   ) -> list[PriorAttempt]:
    """Closed tasks that asked for much the same thing, newest first.

    Rejected attempts sort ahead of failed ones at equal recency: a rejection
    carries a human decision and usually a reason, while a failure is often just
    a flaky command.
    """
    try:
        tasks = store.list_tasks()
    except Exception:
        return []      # a guard that breaks dispatch is worse than no guard

    found: list[PriorAttempt] = []
    for task in tasks:
        if task.status not in ("rejected", "failed"):
            continue
        score = similarity(
            objective, task.objective, b_scope=getattr(task, "scope", "") or ""
        )
        bar = REJECTED_THRESHOLD if task.status == "rejected" else SIMILARITY_THRESHOLD
        if score < bar:
            continue
        found.append(PriorAttempt(
            task_id=task.id,
            status=task.status,
            created_at=task.created_at or "",
            objective=" ".join((task.objective or "").split())[:160],
            review_feedback=" ".join((getattr(task, "review_feedback", "") or "").split()),
            similarity=score,
        ))

    found.sort(key=lambda p: (p.status != "rejected", p.created_at), reverse=False)
    found.sort(key=lambda p: (p.status == "rejected", p.created_at), reverse=True)
    return found[:limit]


def dispatch_warning(prior: list[PriorAttempt]) -> str:
    """One line she cannot miss, or empty when there is nothing to say."""
    if not prior:
        return ""
    rejected = [p for p in prior if p.status == "rejected"]
    if rejected:
        latest = rejected[0]
        note = (f"This was REJECTED before ({latest.created_at[:10]}). "
                f"Read the review below before dispatching again — if it was "
                f"declined on principle rather than on a fixable defect, asking "
                f"again will not change that.")
        if latest.review_feedback:
            note += f" Review said: {latest.review_feedback[:300]}"
        return note
    return (f"{len(prior)} earlier attempt(s) at much the same objective failed. "
            "Check what went wrong before repeating it.")
