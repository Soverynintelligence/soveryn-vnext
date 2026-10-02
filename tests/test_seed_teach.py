"""House seed facts stay public; customer facts stay optional and local."""

from __future__ import annotations

import json

from soveryn.platform.lattice.seed_teach import (
    CUSTOMER_FACTS_ENV,
    SEED_FACTS,
    all_seed_facts,
    load_customer_facts,
)


_PII_NEEDLES = (
    "dan ward",
    "valkanoff",
    "andrew valkanoff",
    "581-3970",
    "5813970",
    "910-581-3970",
    "(910) 581-3970",
)


def test_public_seed_facts_contain_no_customer_pii():
    blob = "\n".join(f"{entity}\n{content}" for entity, content in SEED_FACTS).lower()
    for needle in _PII_NEEDLES:
        assert needle not in blob, needle
    entities = {entity for entity, _ in SEED_FACTS}
    assert "cwg.job.dan_ward" not in entities
    assert "cwg.job.valkanoff" not in entities
    assert "house.rule.no_street_address" in entities
    assert "cwg.ads.pmax" in entities
    assert "lab.voice.tts" in entities


def test_load_customer_facts_missing_is_empty(tmp_path):
    assert load_customer_facts(tmp_path / "missing.json") == ()


def test_load_customer_facts_unreadable_is_empty(tmp_path):
    path = tmp_path / "seed_customer_facts.json"
    path.write_text("{not-json", encoding="utf-8")
    assert load_customer_facts(path) == ()


def test_load_customer_facts_from_file_and_env(tmp_path, monkeypatch):
    path = tmp_path / "seed_customer_facts.json"
    path.write_text(
        json.dumps(
            [
                ["cwg.job.local", "local-only customer note"],
                {"entity": "cwg.job.other", "content": "another local note"},
            ]
        ),
        encoding="utf-8",
    )
    assert load_customer_facts(path) == (
        ("cwg.job.local", "local-only customer note"),
        ("cwg.job.other", "another local note"),
    )
    monkeypatch.setenv(CUSTOMER_FACTS_ENV, str(path))
    combined = all_seed_facts()
    assert ("cwg.job.local", "local-only customer note") in combined
    assert SEED_FACTS[0] in combined
