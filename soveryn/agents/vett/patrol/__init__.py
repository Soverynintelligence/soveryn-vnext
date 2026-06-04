"""V.E.T.T. research patrol — spontaneous initiation over external sources.

Mirror of the heartbeat daemon shape, different domain. Where the
heartbeat is "audit boards / sift lattice / act-or-silence", the patrol
is "check sources / detect change / post-or-silence."

Lives as a separate process (soveryn-vett-patrol systemd unit), talks
to vnext over /chat with the Patrol Briefing prompt.

Public surface (used by daemon + tools + tests):
  - SourceList / PatrolSource — typed config from data/vett_patrol_sources.yaml
  - load_source_list(path) — YAML loader with schema validation
  - read_patrol_state(db) / mark_source_visited(db, url) / mark_source_error(db, url, msg)
  - PatrolConfig.from_env() — daemon config
  - evaluate_tick(...) — eligibility gates
  - build_patrol_brief(...) — prompt construction
"""

from soveryn.agents.vett.patrol.source_list import (
    PATROL_SOURCES_DEFAULT_PATH,
    PatrolSource,
    PatrolSourceError,
    SourceList,
    SourceState,
    load_source_list,
    mark_source_error,
    mark_source_visited,
    read_patrol_state,
)
from soveryn.agents.vett.patrol.trigger import (
    PatrolConfig,
    PatrolSkipReason,
    TickEligibility,
    evaluate_tick,
)
from soveryn.agents.vett.patrol.prompt import (
    LatticeTagSnapshot,
    PatrolBriefingInputs,
    build_patrol_brief,
)


__all__ = [
    "PATROL_SOURCES_DEFAULT_PATH",
    "PatrolSource",
    "PatrolSourceError",
    "SourceList",
    "SourceState",
    "load_source_list",
    "mark_source_error",
    "mark_source_visited",
    "read_patrol_state",
    "PatrolConfig",
    "PatrolSkipReason",
    "TickEligibility",
    "evaluate_tick",
    "LatticeTagSnapshot",
    "PatrolBriefingInputs",
    "build_patrol_brief",
]
