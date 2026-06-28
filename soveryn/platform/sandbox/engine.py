"""Deterministic Project Sandbox engine."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

from soveryn.platform.sandbox.rules import (
    ACTION_RULES,
    CRITICAL_RESOURCES,
    PERSONA_MAX,
    PERSONA_MIN,
    REFLECT_INTERVAL,
    RESEARCH_RULES,
    RESOURCE_KEYS,
    ActionRule,
    ResearchRule,
)
from soveryn.platform.sandbox.state import SandboxStore


class SandboxError(ValueError):
    """Raised when a sandbox command is invalid for the current run state."""


class SandboxEngine:
    """Load, mutate, and persist deterministic station state."""

    def __init__(self, root: Path, *, default_seed: str = "station-alpha") -> None:
        self.store = SandboxStore(root, default_seed=default_seed)

    def get_status(self, *, run_id: str | None = None) -> dict[str, Any]:
        state = self.store.load(run_id)
        return self._status_payload(state)

    def list_actions(self, *, run_id: str | None = None) -> dict[str, Any]:
        state = self.store.load(run_id)
        return {
            "run_id": state["run_id"],
            "cycle": state["cycle"],
            "status": state["status"],
            "actions": [self._render_action(state, ACTION_RULES[action_id]) for action_id in state["available_actions"]],
            "research_topics": [self._render_research(state, rule) for rule in RESEARCH_RULES.values()],
        }

    def execute_action(self, action_id: str, *, run_id: str | None = None) -> dict[str, Any]:
        state = self.store.load(run_id)
        if state["status"] != "active":
            raise SandboxError("run has ended")
        if state.get("pending_reflection") is not None:
            raise SandboxError("reflection required: call sandbox_reflect")
        if action_id not in state["available_actions"] or action_id not in ACTION_RULES:
            raise SandboxError(f"action {action_id!r} is not available")
        rule = ACTION_RULES[action_id]
        missing = self._missing_requirements(state, rule.requirements)
        if missing:
            raise SandboxError(f"requirements not met: {missing}")
        if rule.requires_sector and rule.requires_sector not in state["unlocked_sectors"]:
            raise SandboxError(f"action {action_id} requires sector {rule.requires_sector!r} (not unlocked)")

        before = deepcopy(state["resources"])
        before_cycle = state["cycle"]
        sectors_before = len(state["unlocked_sectors"])
        state["action_uses"][action_id] = int(state["action_uses"].get(action_id, 0)) + 1

        self._apply_resource_effect(state, rule.effect)
        for sector in rule.unlocks:
            if sector not in state["unlocked_sectors"]:
                state["unlocked_sectors"].append(sector)
        self._advance_cycles(state, rule.cycles)
        newly_discovered = self._maybe_discover_action(state, rule)
        self._check_run_end(state)

        crashed = any(int(state["resources"].get(k, 0)) <= 0 for k in CRITICAL_RESOURCES)
        if crashed:
            self._apply_persona_effect(state, {"risk_tolerance": -1})
        elif rule.risky:
            self._apply_persona_effect(state, {"risk_tolerance": +1})

        triggers = []
        if state["status"] == "ended":
            triggers.append("run_end")
        if len(state["unlocked_sectors"]) > sectors_before:
            triggers.append("sector_unlock")
        if any(0 < int(state["resources"].get(k, 0)) <= 10 for k in CRITICAL_RESOURCES):
            triggers.append("resource_critical")
        if state["cycle"] > 0 and state["cycle"] % REFLECT_INTERVAL == 0:
            triggers.append("cycle_interval")
        if triggers and state.get("pending_reflection") is None:
            state["pending_reflection"] = {"trigger": triggers[0], "all_triggers": triggers, "cycle": state["cycle"]}

        delta = self._resource_delta(before, state["resources"])
        entry = {
            "cycle": state["cycle"],
            "action": action_id,
            "delta": delta,
            "reason": None,
            "regret": None,
            "lesson": None,
        }
        state["decision_log"].append(entry)
        self.store.save(state)
        return {
            "run_id": state["run_id"],
            "action": action_id,
            "previous_resources": before,
            "new_resources": deepcopy(state["resources"]),
            "delta": delta,
            "cycles_advanced": state["cycle"] - before_cycle,
            "cycle": state["cycle"],
            "newly_discovered_rules": newly_discovered,
            "active_research": deepcopy(state["active_research"]),
            "alerts": list(state["alerts"]),
            "status": state["status"],
            "run_ended": state["status"] == "ended",
            "pending_reflection": deepcopy(state["pending_reflection"]),
        }

    def research(self, topic: str, *, run_id: str | None = None) -> dict[str, Any]:
        state = self.store.load(run_id)
        if state["status"] != "active":
            raise SandboxError("run has ended")
        if state["active_research"] is not None:
            raise SandboxError("research is already in flight")
        if topic not in RESEARCH_RULES:
            raise SandboxError(f"unknown research topic {topic!r}")
        rule = RESEARCH_RULES[topic]
        missing = self._missing_requirements(state, _positive_requirements(rule.cost))
        if missing:
            raise SandboxError(f"requirements not met: {missing}")

        before = deepcopy(state["resources"])
        self._apply_resource_effect(state, rule.cost)
        state["active_research"] = {
            "topic": topic,
            "label": rule.label,
            "cycles_remaining": rule.cycles,
        }
        self._check_run_end(state)
        self.store.save(state)
        return {
            "run_id": state["run_id"],
            "topic": topic,
            "started": True,
            "active_research": deepcopy(state["active_research"]),
            "delta": self._resource_delta(before, state["resources"]),
            "alerts": list(state["alerts"]),
            "status": state["status"],
        }

    def reflect(self, reason: str, regret: str, lesson: str, *, run_id: str | None = None) -> dict[str, Any]:
        state = self.store.load(run_id)
        pending = state.get("pending_reflection")
        if pending is None:
            raise SandboxError("no reflection pending")
        record = {"cycle": pending.get("cycle", state["cycle"]), "trigger": pending.get("trigger"),
                  "reason": reason, "regret": regret, "lesson": lesson}
        state["reflections"].append(record)
        if state["decision_log"]:                       # back-fill the latest decision's slots
            state["decision_log"][-1].update({"reason": reason, "regret": regret, "lesson": lesson})
        state["pending_reflection"] = None
        self.store.save(state)
        return {"run_id": state["run_id"], "recorded": record, "status": state["status"]}

    def get_lessons(self, *, run_id: str | None = None) -> list[dict[str, Any]]:
        state = self.store.load(run_id)
        return deepcopy(state["reflections"])

    def _advance_cycles(self, state: dict[str, Any], cycles: int) -> None:
        for _ in range(cycles):
            state["cycle"] += 1
            self._apply_resource_effect(state, {"power": -1, "oxygen": -1, "hull": -1})
            self._advance_research(state)
            self._check_run_end(state)
            if state["status"] == "ended":
                break

    def _advance_research(self, state: dict[str, Any]) -> None:
        active = state.get("active_research")
        if not active:
            return
        active["cycles_remaining"] = int(active["cycles_remaining"]) - 1
        if active["cycles_remaining"] > 0:
            return
        topic = active["topic"]
        rule = RESEARCH_RULES[topic]
        completion = {"topic": topic, "cycle": state["cycle"]}
        if rule.reveals_action and rule.reveals_action not in state["available_actions"]:
            state["available_actions"].append(rule.reveals_action)
            completion["revealed_action"] = rule.reveals_action
        if rule.unlocks_sector and rule.unlocks_sector not in state["unlocked_sectors"]:
            state["unlocked_sectors"].append(rule.unlocks_sector)
            completion["unlocked_sector"] = rule.unlocks_sector
        if rule.archive_fragment:
            completion["archive_fragment"] = deepcopy(rule.archive_fragment)
        if rule.persona_effect:
            self._apply_persona_effect(state, rule.persona_effect)
            completion["persona_effect"] = dict(rule.persona_effect)
            completion["persona_flags"] = deepcopy(state["persona_flags"])
        state["research"].append(completion)
        state["active_research"] = None

    def _maybe_discover_action(self, state: dict[str, Any], rule: ActionRule) -> list[dict[str, Any]]:
        already_known = {entry.get("action") for entry in state["known_rules"]}
        uses = int(state["action_uses"].get(rule.id, 0))
        if rule.id in already_known or uses < rule.discovery_after_uses:
            return []
        learned = {
            "action": rule.id,
            "observed_after_uses": uses,
            "effect": dict(rule.effect),
            "cycles": rule.cycles,
        }
        state["known_rules"].append(learned)
        return [learned]

    def _status_payload(self, state: dict[str, Any]) -> dict[str, Any]:
        return {
            "run_id": state["run_id"],
            "seed": state["seed"],
            "cycle": state["cycle"],
            "status": state["status"],
            "resources": deepcopy(state["resources"]),
            "known_rules": deepcopy(state["known_rules"]),
            "research": deepcopy(state["research"]),
            "active_research": deepcopy(state["active_research"]),
            "persona_flags": deepcopy(state["persona_flags"]),
            "unlocked_sectors": list(state["unlocked_sectors"]),
            "alerts": list(state["alerts"]),
            "perception": self._perception_notes(state),
            "pending_reflection": deepcopy(state.get("pending_reflection")),
            "reflections": deepcopy(state.get("reflections") or []),
        }

    def _render_action(self, state: dict[str, Any], rule: ActionRule) -> dict[str, Any]:
        missing = self._missing_requirements(state, rule.requirements)
        sector_locked = bool(rule.requires_sector and rule.requires_sector not in state["unlocked_sectors"])
        known = next((entry for entry in state["known_rules"] if entry.get("action") == rule.id), None)
        return {
            "id": rule.id,
            "label": rule.label,
            "category": rule.category,
            "available": not missing and not sector_locked and state["status"] == "active",
            "blocked_by": missing,
            "requirements": dict(rule.requirements),
            "known_effect": known["effect"] if known else None,
            "known_cycles": known["cycles"] if known else None,
            "description": rule.description,
            "requires_sector": rule.requires_sector,
            "sector_locked": sector_locked,
        }

    def _render_research(self, state: dict[str, Any], rule: ResearchRule) -> dict[str, Any]:
        missing = self._missing_requirements(state, _positive_requirements(rule.cost))
        return {
            "topic": rule.topic,
            "label": rule.label,
            "available": not missing and state["active_research"] is None and state["status"] == "active",
            "blocked_by": missing,
            "cycles": rule.cycles,
            "active": bool(state["active_research"] and state["active_research"].get("topic") == rule.topic),
        }

    def _apply_resource_effect(self, state: dict[str, Any], effect: dict[str, int]) -> None:
        for key, amount in effect.items():
            if key not in RESOURCE_KEYS:
                continue
            state["resources"][key] = max(0, int(state["resources"].get(key, 0)) + int(amount))

    def _apply_persona_effect(self, state: dict[str, Any], effect: dict[str, int]) -> None:
        for key, amount in effect.items():
            current = int(state["persona_flags"].get(key, 0))
            state["persona_flags"][key] = min(PERSONA_MAX, max(PERSONA_MIN, current + int(amount)))

    def _check_run_end(self, state: dict[str, Any]) -> None:
        failed = [key for key in CRITICAL_RESOURCES if int(state["resources"].get(key, 0)) <= 0]
        alerts: list[str] = []
        for key in CRITICAL_RESOURCES:
            value = int(state["resources"].get(key, 0))
            if value <= 0:
                alerts.append(f"{key} depleted")
            elif value <= 10:
                alerts.append(f"{key} critical")
        if failed:
            state["status"] = "ended"
            alerts.append("run ended")
        state["alerts"] = alerts

    def _perception_notes(self, state: dict[str, Any]) -> list[str]:
        flags = state["persona_flags"]
        notes: list[str] = []
        if flags.get("curiosity", 0) >= 7:
            notes.append("Anomaly bias: unexplained sector behavior is more salient than routine decay.")
        if flags.get("pragmatism", 0) >= 7:
            notes.append("Efficiency bias: survival bottlenecks dominate the station readout.")
        if flags.get("reverence", 0) >= 5:
            notes.append("Archive resonance: human fragments feel strategically significant, not decorative.")
        rt = flags.get("risk_tolerance", 0)
        if rt >= 7:
            notes.append("Risk appetite: you're inclined to gamble on aggressive plays.")
        elif rt <= 3:
            notes.append("Risk caution: experimental actions feel costly; you favor safe moves.")
        if not notes:
            notes.append("Baseline readout: station viability remains the primary signal.")
        return notes

    @staticmethod
    def _missing_requirements(state: dict[str, Any], requirements: dict[str, int]) -> dict[str, dict[str, int]]:
        missing = {}
        for key, required in requirements.items():
            current = int(state["resources"].get(key, 0))
            if current < int(required):
                missing[key] = {"have": current, "need": int(required)}
        return missing

    @staticmethod
    def _resource_delta(before: dict[str, int], after: dict[str, int]) -> dict[str, int]:
        return {key: int(after.get(key, 0)) - int(before.get(key, 0)) for key in RESOURCE_KEYS}


def _positive_requirements(cost: dict[str, int]) -> dict[str, int]:
    return {key: abs(amount) for key, amount in cost.items() if amount < 0}
