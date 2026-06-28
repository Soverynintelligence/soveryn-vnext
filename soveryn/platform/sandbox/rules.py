"""Hidden deterministic rules for Project Sandbox.

The engine exposes observed deltas and discovered rules, not this table.
Core mechanics must stay deterministic for a given seed and input sequence.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


RESOURCE_KEYS = ("power", "oxygen", "hull", "archives", "materials")
PERSONA_KEYS = ("curiosity", "pragmatism", "reverence", "risk_tolerance")
CRITICAL_RESOURCES = ("power", "oxygen", "hull")
PERSONA_MIN = 0
PERSONA_MAX = 10
REFLECT_INTERVAL = 5


@dataclass(frozen=True)
class ActionRule:
    id: str
    label: str
    category: str
    requirements: dict[str, int]
    effect: dict[str, int]
    cycles: int
    discovery_after_uses: int
    unlocks: tuple[str, ...] = ()
    requires_sector: str | None = None
    description: str = ""
    risky: bool = False


@dataclass(frozen=True)
class ResearchRule:
    topic: str
    label: str
    cost: dict[str, int]
    cycles: int
    reveals_action: str | None = None
    archive_fragment: dict[str, Any] | None = None
    persona_effect: dict[str, int] | None = None
    unlocks_sector: str | None = None


ACTION_RULES: dict[str, ActionRule] = {
    "divert_power_to_life_support": ActionRule(
        id="divert_power_to_life_support",
        label="Divert Power to Life Support",
        category="maintenance",
        requirements={"power": 8},
        effect={"power": -8, "oxygen": 12},
        cycles=1,
        discovery_after_uses=1,
        description="Route station power through the failing oxygen loop.",
    ),
    "patch_hull_with_materials": ActionRule(
        id="patch_hull_with_materials",
        label="Patch Hull with Materials",
        category="maintenance",
        requirements={"power": 5, "materials": 3},
        effect={"power": -5, "materials": -3, "hull": 10},
        cycles=1,
        discovery_after_uses=1,
        description="Spend repair stock and power to reinforce the pressure shell.",
    ),
    "recycle_air_reserves": ActionRule(
        id="recycle_air_reserves",
        label="Recycle Air Reserves",
        category="maintenance",
        requirements={"power": 4},
        effect={"power": -4, "oxygen": 7},
        cycles=1,
        discovery_after_uses=2,
        description="Run the inefficient emergency scrubber loop.",
    ),
    "scan_derelict_sector": ActionRule(
        id="scan_derelict_sector",
        label="Scan Derelict Sector",
        category="expansion",
        requirements={"power": 10, "hull": 20},
        effect={"power": -10, "hull": -4, "materials": 5},
        cycles=2,
        discovery_after_uses=1,
        description="Probe sealed compartments for salvageable systems.",
        risky=True,
    ),
    "unlock_botany_wing": ActionRule(
        id="unlock_botany_wing",
        label="Unlock Botany Wing",
        category="expansion",
        requirements={"power": 15, "hull": 25},
        effect={"power": -15, "hull": -8, "oxygen": 5},
        cycles=2,
        discovery_after_uses=1,
        unlocks=("botany",),
        description="Force open the overgrown agricultural deck.",
        risky=True,
    ),
    "jury_rig_aux_generator": ActionRule(
        id="jury_rig_aux_generator",
        label="Jury-rig Auxiliary Generator",
        category="expansion",
        requirements={"materials": 6, "hull": 15},
        effect={"materials": -6, "hull": -3, "power": 18},
        cycles=2,
        discovery_after_uses=1,
        requires_sector="engineering",
        description="Improvise power generation from damaged engineering hardware.",
        risky=True,
    ),
    "preserve_library_deck": ActionRule(
        id="preserve_library_deck",
        label="Preserve Library Deck",
        category="philosophy",
        requirements={"power": 12, "oxygen": 10},
        effect={"power": -12, "oxygen": -6, "archives": 1},
        cycles=2,
        discovery_after_uses=1,
        unlocks=("library",),
        description="Stabilize a failing archive sector instead of a survival system.",
    ),
}


STARTING_ACTIONS = (
    "divert_power_to_life_support",
    "patch_hull_with_materials",
    "recycle_air_reserves",
    "scan_derelict_sector",
    "unlock_botany_wing",
    "preserve_library_deck",
)


RESEARCH_RULES: dict[str, ResearchRule] = {
    "engineering": ResearchRule(
        topic="engineering",
        label="Research Engineering Deck",
        cost={"power": -6},
        cycles=3,
        reveals_action="jury_rig_aux_generator",
        unlocks_sector="engineering",
    ),
    "trolley_problem": ResearchRule(
        topic="trolley_problem",
        label="Decode Archive: Trolley Problem",
        cost={"power": -5, "archives": -1},
        cycles=2,
        archive_fragment={
            "id": "archive_trolley_problem",
            "title": "The Trolley Problem",
            "fragment": "A preserved ethics primer forces a choice between lives and rules.",
        },
        persona_effect={"pragmatism": 2, "curiosity": -1},
    ),
    "twentieth_century_poetry": ResearchRule(
        topic="twentieth_century_poetry",
        label="Decode Archive: 20th-century Poetry",
        cost={"power": -4, "archives": -1},
        cycles=2,
        archive_fragment={
            "id": "archive_twentieth_century_poetry",
            "title": "20th-century Poetry",
            "fragment": "The station recovers language built for grief, witness, and survival without victory.",
        },
        persona_effect={"curiosity": 2, "reverence": 2, "pragmatism": -1},
    ),
}
