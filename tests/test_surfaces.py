"""The surface registry exists because Atticus was invisible, not because it broke.

On 2026-08-07 `atticus.historysledger.com` served 404s with its systemd unit
never installed. No monitor caught it and none could have — Atticus appeared in
no registry, so its failure mode was not "a check failed" but "nothing knew it
was supposed to exist."

These tests pin the four rules that came out of that week, each of which was
learned by getting it wrong first.
"""
from __future__ import annotations

import json
import time

import pytest

from soveryn.agents.ares.findings import Severity
from soveryn.agents.ares.lanes import surfaces as lane
from soveryn.platform.surfaces import registry
from soveryn.platform.surfaces.probe import Result, Status
from soveryn.platform.surfaces.registry import Kind, Surface
from soveryn.platform.surfaces.staleness import Observations


# ── rule 1: UNKNOWN is not HEALTHY ──────────────────────────────────────────

def test_unknown_is_not_ok():
    """The single most repeated defect of the week, asserted directly.

    The audit tool read four stores of five and reported an empty audit. Ares
    read a failed nvidia-smi as three healthy cards. Both folded "could not
    check" into "nothing wrong."
    """
    r = Result("x", Status.UNKNOWN, "could not reach", 0.0, time.time())
    assert r.ok is False
    assert Result("x", Status.HEALTHY, "", 0.0, time.time()).ok is True
    assert Result("x", Status.FAILED, "", 0.0, time.time()).ok is False


def test_unreachable_surface_is_unknown_not_failed(monkeypatch):
    """A host that cannot be reached is UNKNOWN — we learned nothing about it."""
    from soveryn.platform.surfaces import probe as probe_mod

    def boom(*a, **k):
        raise OSError("network is down")

    monkeypatch.setattr(probe_mod.urllib.request, "urlopen", boom)
    s = Surface("t", Kind.HTTP, "http://127.0.0.1:9/")
    assert probe_mod.probe(s).status is Status.UNKNOWN


# ── rule 2: probe function, not status ──────────────────────────────────────

def test_answering_is_not_working(monkeypatch):
    """HTTP 200 with a useless body is DOWN.

    `systemctl is-active` called the Telegram bridge active for eight days while
    it delivered nothing. A 200 is the same lie one layer up.
    """
    from soveryn.platform.surfaces import probe as probe_mod

    class _R:
        status = 200
        def read(self, n=0): return json.dumps({"reply": ""}).encode()
        def __enter__(self): return self
        def __exit__(self, *a): return False

    monkeypatch.setattr(probe_mod.urllib.request, "urlopen", lambda *a, **k: _R())
    s = Surface("t", Kind.FUNCTIONAL, "http://x/chat", method="POST",
                payload={"a": 1}, expect_json_field="reply", expect_min_chars=60)
    r = probe_mod.probe(s)
    assert r.status is Status.FAILED
    assert "missing or empty" in r.detail


def test_functional_probe_does_not_assert_on_model_wording():
    """Regression for a flaw in this module's own first draft.

    The Atticus surface originally required the substring "rebate" in the reply.
    The model said "kickbacks" on two runs in three, so a perfectly healthy
    service was reported DOWN two thirds of the time. A monitor that cries wolf
    gets muted, and a muted monitor is how Ares ended up holding 53 lint findings
    nobody read while real outages ran underneath.

    Any model-generated surface must assert on SHAPE, never on wording.
    """
    generated = [s for s in registry.SURFACES if s.kind is Kind.FUNCTIONAL]
    assert generated, "expected at least one functional surface"
    for s in generated:
        assert not s.expect_contains, (
            f"{s.name} asserts on model wording via expect_contains={s.expect_contains!r}; "
            "use expect_json_field/expect_min_chars instead"
        )
        assert s.expect_json_field, f"{s.name} must assert on a response field"


def test_a_401_can_be_the_healthy_answer(monkeypatch):
    """Shepherd sits behind HTTP Basic. Expecting 200 would report a working
    auth gate as an outage — a false alarm on a correctly secured surface."""
    from soveryn.platform.surfaces import probe as probe_mod
    import urllib.error

    def raise401(*a, **k):
        raise urllib.error.HTTPError("http://x", 401, "Unauthorized", {}, None)

    monkeypatch.setattr(probe_mod.urllib.request, "urlopen", raise401)
    s = Surface("shepherd", Kind.HTTP, "http://x/", expect_status=401)
    assert probe_mod.probe(s).status is Status.HEALTHY


# ── rule 3: absence of a signal is itself a finding ─────────────────────────

def test_never_verified_is_critical_and_immediate(tmp_path):
    """The Atticus case. Not a failing check — an absent one.

    'We have no idea' and 'it is broken' carry the same operational risk, and
    only one of them announces itself. So never-verified gets no grace period.
    """
    obs = Observations(tmp_path / "seen.json")
    s = Surface("never-looked-at", Kind.UNIT, "nope.service", interval_s=300)
    stale = obs.stale([s])
    assert len(stale) == 1
    assert stale[0].reason == "never-verified"
    assert stale[0].never is True


def test_only_a_healthy_probe_resets_the_clock(tmp_path):
    """Storing last-PROBED would defeat the purpose: a surface probed every
    minute and failing every minute would look perfectly fresh."""
    obs = Observations(tmp_path / "seen.json")
    now = time.time()
    obs.record([Result("s", Status.FAILED, "", 0.0, now),
                Result("s", Status.UNKNOWN, "", 0.0, now)])
    assert obs.last_healthy("s") is None
    obs.record([Result("s", Status.HEALTHY, "", 0.0, now)])
    assert obs.last_healthy("s") == now


def test_stale_needs_two_missed_intervals(tmp_path):
    """One missed cycle is a blip; two is a pattern."""
    obs = Observations(tmp_path / "seen.json")
    now = time.time()
    s = Surface("s", Kind.UNIT, "u.service", interval_s=100)
    obs.record([Result("s", Status.HEALTHY, "", 0.0, now - 150)])
    assert obs.stale([s], now=now) == []
    obs.record([Result("s", Status.HEALTHY, "", 0.0, now - 250)])
    assert [x.reason for x in obs.stale([s], now=now)] == ["stale"]


# ── rule 4: a lane that cannot see must not report health ───────────────────

def test_empty_registry_raises_rather_than_reporting_all_clear(tmp_path):
    """Established 2026-08-02: a collector returning () means 'nothing wrong'.

    A lane with nothing to check has learned nothing, and must say so.
    """
    with pytest.raises(lane.SurfaceProbeError):
        lane.collect(observations=Observations(tmp_path / "s.json"), surfaces=[])


def test_retired_surface_does_not_alarm(tmp_path):
    """tg-bridge is deliberately off. 'Deliberately off' is a recorded state,
    not an absence someone re-discovers in six months."""
    obs = Observations(tmp_path / "s.json")
    retired = [s for s in registry.SURFACES if s.retired]
    assert retired, "expected the retired tg-bridge entry to still be declared"
    assert obs.stale(retired) == []
    assert registry.BY_NAME["tg-bridge"] not in registry.live()


def test_lane_emits_critical_for_down_and_never_verified(tmp_path, monkeypatch):
    from soveryn.agents.ares.lanes import surfaces as lane_mod

    surfaces = (Surface("dead", Kind.HTTP, "http://x/"),
                Surface("blind", Kind.HTTP, "http://y/"))
    now = time.time()
    monkeypatch.setattr(lane_mod, "probe_all", lambda s, timeout=0: [
        Result("dead", Status.FAILED, "HTTP 404, expected 200", 0.1, now),
        Result("blind", Status.UNKNOWN, "could not reach", 0.1, now),
    ])
    found = lane_mod.collect(observations=Observations(tmp_path / "s.json"),
                             surfaces=surfaces)
    by_type = {f.finding_type: f for f in found}
    assert by_type["surface.down"].severity is Severity.CRITICAL
    assert by_type["surface.unknown"].severity is Severity.WARNING
    # 'blind' was never healthy, so it is ALSO never-verified — unknown and
    # unverified are different facts and both belong in the record.
    assert by_type["surface.never_verified"].severity is Severity.CRITICAL


# ── the registry itself ─────────────────────────────────────────────────────

def test_the_incident_surfaces_are_declared():
    """Every surface that failed silently this week is now watchable."""
    for name in ("atticus", "soveryn-agent", "shepherd",
                 "soverynintelligence.com", "router-blackwell", "laguna-spark"):
        assert name in registry.BY_NAME, f"{name} is undeclared and therefore unwatched"


def test_chat_surfaces_are_probed_on_the_path_they_actually_serve():
    """Both agent front doors serve ONLY POST /chat and return 404 on GET /.

    Declared as GET / first, they reported two healthy services as DOWN — and a
    duplicate Atticus was installed on the tower before anyone checked. That is
    this package's own failure mode committed while building it: an expectation
    asserted without verifying the contract, and the mismatch read as an outage.

    A monitor is only worth its false-positive rate.
    """
    for name in ("atticus", "soveryn-agent"):
        s = registry.BY_NAME[name]
        assert s.method == "POST", f"{name} serves POST /chat, not GET"
        assert s.target.endswith("/chat"), f"{name} must be probed on /chat"
        assert s.expect_json_field == "reply"


def test_every_surface_has_a_probe_target_and_owner():
    for s in registry.SURFACES:
        assert s.target.strip(), f"{s.name} has no probe target"
        assert s.owner.strip(), f"{s.name} has no owner"
        assert s.interval_s > 0, f"{s.name} has no staleness interval"
