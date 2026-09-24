"""Shim — implementation lives in portable acttruth package."""
from acttruth.proof import *  # noqa: F403
from acttruth.proof import (
    ActTruthProof,
    AgentProofStats,
    collect_proof,
    format_proof_post,
)
from soveryn.platform.acttruth.hooks import get_acttruth  # noqa: F401
