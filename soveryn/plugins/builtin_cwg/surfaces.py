"""CWG / PondWright surface probes. The shared pondwright tunnel stays in core."""

from __future__ import annotations

from soveryn.platform.surfaces.registry import Kind, Surface


def surfaces() -> list[Surface]:
    return [
        Surface(
            "pondwright-crm", Kind.HTTP, "https://crm.pondwright.com/",
            owner="jon", interval_s=1800, expect_status=401,
            notes="401 is healthy — the CRM is password-gated. Holds real customer "
                  "leads; leads.db is git-ignored by stem, not extension.",
        ),
        Surface(
            "pondwright-chat", Kind.FUNCTIONAL, "https://chat.pondwright.com/chat",
            owner="jon", interval_s=1800, method="POST",
            payload={"session_id": "surface-probe",
                     "messages": [{"role": "user",
                                   "content": "In one sentence, what do you help with?"}]},
            expect_json_field="reply", expect_min_chars=40,
            notes="The openly-AI intake agent. Never quotes prices. POST /chat only.",
        ),
        Surface(
            "pondwright-estimator", Kind.HTTP, "https://crm.pondwright.com/field/login",
            owner="jon", interval_s=3600, expect_status=200,
            notes="Field estimator now lives in pondwright-cwg-ops at /field "
                  "(estimator.pondwright.com 301s there). Probe the login page: "
                  "GET /field itself 401s non-HTML clients after the redirect. "
                  "NEVER expose estimator Step 2 — it is Jon's margin.",
        ),
        Surface(
            "carolinawatergardens", Kind.PUBLIC, "https://carolinawatergardens.com/",
            owner="jon", interval_s=3600,
        ),
        Surface(
            "pondwright-health", Kind.HTTP, "https://chat.pondwright.com/health",
            owner="soveryn", interval_s=600, expect_contains='"model_ok": true',
            notes="CWG chat agent on the Spark; red means it lost its model backend.",
        ),
    ]
