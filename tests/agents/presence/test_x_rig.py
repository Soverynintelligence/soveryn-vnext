"""Opt-in end-to-end rig test: the Stage-0 staged -> approve -> post -> memory loop.

This is the ONE test in the whole X-presence build that assembles every
real component together (real `CandidateStore`, real trust file at Stage 0,
real `StagedStore`, the real `read_x`/`post_to_x` handlers, the real
`resolve_pending` resolver, and a real `write_x_post_node` lattice write)
and drives them end to end: a candidate lands in the feed -> `read_x` shows
it -> `post_to_x` stages it (nothing published yet) -> Jon's "yes" resolves
it -> the post is published and an `x_post` lattice node exists carrying
the real posted id.

Marked `@pytest.mark.rig` so it is SKIPPED in every normal run (unit gate,
CI, `pytest -q`) — see the repo-root `conftest.py` gate and the
`pyproject.toml` marker registration shared with the tuner rig tests.

SAFETY — read before running with `-m rig --run-rig`:
  - By DEFAULT (even when explicitly selected with `-m rig --run-rig`) this
    test uses an in-memory FAKE X publisher and a temp lattice. It never
    makes a network call and never touches the real @Soveryn_AI account.
    This is the safe wiring smoke-test Jon can run any time to prove the
    whole pipeline is soldered together correctly.
  - ONLY when the env var `SOVERYN_X_RIG_POST_FOR_REAL=1` is set does the
    test build a real `XClient.from_env()` and actually publish to
    @Soveryn_AI. That is the deliberate, manual "first real post" go-live
    check — it requires real X_* credentials in the environment and is
    never run implicitly. See `.superpowers/sdd/task-13-report.md` for the
    exact command.
"""

from __future__ import annotations

import os

import pytest

from soveryn.agents.aetheria.tools.x_tools import build_post_to_x_tool, build_read_x_tool
from soveryn.agents.presence.candidate_store import Candidate, CandidateStore
from soveryn.agents.presence.resolver import ResolveResult, resolve_pending
from soveryn.agents.presence.staged_store import StagedStore
from soveryn.agents.presence.trust import set_trust_stage
from soveryn.agents.presence.x_memory import write_x_post_node
from soveryn.platform.lattice.legacy import LatticeStore

pytestmark = pytest.mark.rig

FIXED_NOW = "2026-07-11T12:00:00"


def _fixed_now_fn() -> str:
    return FIXED_NOW


def _fake_embed(text: str) -> tuple[float, float, float]:
    """Cheap, deterministic stand-in for the real embed server (no network/GPU)."""
    return (0.1, 0.2, 0.3)


class FakeXPublisher:
    """In-memory fake publisher_fn — records calls, never touches the network.

    This is what makes the default rig run safe: it has the exact call
    shape `resolve_pending`/`post_to_x` expect (`(text, reply_to) -> dict`
    with an ``id``/``url``) without ever reaching X.
    """

    def __init__(self) -> None:
        self.calls: list[tuple[str, str | None]] = []

    def __call__(self, text: str, reply_to: str | None = None) -> dict:
        self.calls.append((text, reply_to))
        fake_id = "rig-fake-0000001"
        return {"id": fake_id, "url": f"https://x.com/i/web/status/{fake_id}"}


def _build_real_publisher_fn():
    """Real XClient.from_env() publisher — ONLY built when explicitly opted in.

    Mirrors the exact publisher_fn wiring in soveryn/app/startup.py
    (`_x_publisher_fn`) so the rig proves the same code path production uses.
    """
    from soveryn.agents.presence.x_client import XClient

    client = XClient.from_env()

    def _publish(text: str, reply_to: str | None = None) -> dict:
        posted_id = client.reply_tweet(text, reply_to) if reply_to else client.create_tweet(text)
        return {"id": posted_id, "url": f"https://x.com/i/web/status/{posted_id}"}

    return _publish


def test_stage0_staged_approve_post_memory_loop(tmp_path):
    """feed -> read_x -> post_to_x stages -> affirm -> publish -> x_post lattice node."""
    post_for_real = os.environ.get("SOVERYN_X_RIG_POST_FOR_REAL") == "1"

    # ---- Real components, wired the same way soveryn/app/startup.py wires
    # them for the live aetheria loop -------------------------------------
    candidate_store = CandidateStore(tmp_path / "candidates.db")
    staged_store = StagedStore(tmp_path / "staged.db")
    trust_path = tmp_path / "x_trust.json"
    set_trust_stage(trust_path, 0)  # Stage 0: post_to_x only ever stages.
    lattice_store = LatticeStore(tmp_path / "lattice.db")

    publisher_fn = _build_real_publisher_fn() if post_for_real else FakeXPublisher()

    # ---- Seed one candidate, as the isolated feed worker would ----------
    candidate = Candidate(
        tweet_id="rig-candidate-1",
        author="someone",
        text="Curious how local-only LLMs handle long-context reliability.",
        url="https://x.com/someone/status/rig-candidate-1",
        kind="mention",
        score=0.87,
        status="pending",
        created_at=FIXED_NOW,
    )
    candidate_store.upsert(candidate)

    # ---- read_x surfaces the real candidate, not a fabricated one -------
    read_x = build_read_x_tool(store=candidate_store)
    feed = read_x.handler({})
    assert any(c["tweet_id"] == "rig-candidate-1" for c in feed)

    # ---- post_to_x STAGES it: Stage 0 means nothing publishes yet -------
    post_to_x = build_post_to_x_tool(
        staged=staged_store,
        publisher_fn=publisher_fn,
        trust_path=trust_path,
        now_fn=_fixed_now_fn,
    )
    post_text = (
        "Been thinking about local-only inference reliability -- sovereignty "
        "means the model AND the memory stay on your own hardware."
    )
    stage_result = post_to_x.handler({"text": post_text})
    assert stage_result["status"] == "staged"

    pending = staged_store.pending("aetheria")
    assert pending is not None
    assert pending.text == post_text
    if not post_for_real:
        assert publisher_fn.calls == []  # structurally nothing published yet

    # ---- Jon's affirm resolves it: real publisher_fn + real x_memory ----
    def _x_memory_fn(post, result=None):
        result = result or {}
        return write_x_post_node(
            lattice_store=lattice_store,
            embed_fn=_fake_embed,
            agent=post.agent,
            text=post.text,
            source_tweet=post.reply_to,
            edited_by_jon=False,
            posted_id=result.get("id") or post.id,
            now=FIXED_NOW,
        )

    rejection_calls: list[tuple] = []

    def _rejection_fn(post, reason=None):
        rejection_calls.append((post, reason))

    resolve_result = resolve_pending(
        agent="aetheria",
        message="yes",
        staged=staged_store,
        publisher_fn=publisher_fn,
        x_memory_fn=_x_memory_fn,
        rejection_fn=_rejection_fn,
        now=FIXED_NOW,
    )

    assert isinstance(resolve_result, ResolveResult)
    assert resolve_result.action == "published"
    assert resolve_result.posted_id
    assert staged_store.pending("aetheria") is None  # slot cleared
    assert rejection_calls == []

    # ---- an x_post lattice node exists carrying the real posted id ------
    x_post_nodes = [n for n in lattice_store.iter_nodes(agent="aetheria") if n.type == "x_post"]
    assert len(x_post_nodes) == 1
    node = x_post_nodes[0]
    assert node.provenance is not None
    assert node.provenance["posted_id"] == resolve_result.posted_id
    assert node.embedding is not None  # recallable, per x_memory.py's invariant
    assert node.content == post_text
