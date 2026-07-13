from dataclasses import dataclass
from pathlib import Path

_NICHE = (
    "sovereign AI", "local LLM", "on-device AI", "open-weight models",
    "AI honesty", "AI confabulation", "AI hallucination", "AI reliability",
    "local-first AI", "AI companions",
)


@dataclass(frozen=True)
class PresenceConfig:
    niche_terms: tuple[str, ...]
    own_handle: str
    score_threshold: float
    max_drafts_per_scan: int
    poll_interval_seconds: float
    db_path: Path
    signal_log_path: Path
    pending_db_path: Path
    # When False (the default), the feed worker only searches for own-handle
    # mentions and never trawls the niche terms — she replies only to people
    # who @-mention her, and we stop burning metered X reads on random topic
    # tweets. `niche_terms` stays populated regardless: the scorer still uses
    # them to score a mention's *content*. Set True to restore the old trawl.
    trawl_niche_topics: bool = False

    @classmethod
    def default(cls) -> "PresenceConfig":
        base = Path.home() / "soveryn_vnext" / "data"
        return cls(
            niche_terms=_NICHE, own_handle="Soveryn_AI", score_threshold=2.0,
            max_drafts_per_scan=3, poll_interval_seconds=300.0,
            db_path=base / "presence_candidates.db",
            signal_log_path=base / "presence_signal_log.db",
            pending_db_path=base / "presence_pending.db",
            trawl_niche_topics=False,
        )
