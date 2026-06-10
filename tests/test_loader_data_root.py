"""Tests for EnvConfig.data_root + SOVERYN_DATA_ROOT override.

Path consolidation Task 1: add a single root for all vnext runtime data
so downstream defaults can derive from it.
"""

from pathlib import Path
from soveryn.config.loader import load_env_config, DEFAULT_DATA_ROOT


def test_default_data_root_is_under_soveryn_vnext():
    cfg = load_env_config({})
    assert cfg.data_root == Path.home() / "soveryn_vnext" / "data"
    assert cfg.data_root == DEFAULT_DATA_ROOT


def test_data_root_env_override():
    cfg = load_env_config({"SOVERYN_DATA_ROOT": "/tmp/custom-data"})
    assert cfg.data_root == Path("/tmp/custom-data")


def test_data_root_empty_env_falls_back_to_default():
    cfg = load_env_config({"SOVERYN_DATA_ROOT": ""})
    assert cfg.data_root == DEFAULT_DATA_ROOT


# ─── Task 2: derived defaults cascade from data_root ────────────────────────


def test_lattice_db_default_derives_from_data_root():
    cfg = load_env_config({})
    assert cfg.lattice_db == cfg.data_root / "memory" / "lattice_vnext.db"


def test_conversations_db_default_derives_from_data_root():
    cfg = load_env_config({})
    assert cfg.conversations_db == cfg.data_root / "memory" / "conversations_vnext.db"


def test_souls_dir_default_derives_from_data_root():
    cfg = load_env_config({})
    assert cfg.souls_dir == cfg.data_root / "memory" / "souls"


def test_pinned_memory_default_derives_from_data_root():
    cfg = load_env_config({})
    assert cfg.pinned_memory_path == cfg.data_root / "memory" / "pinned_memory.md"


def test_recall_lattice_db_default_derives_from_data_root():
    cfg = load_env_config({})
    assert cfg.recall_lattice_db == cfg.data_root / "memory" / "lattice_vnext.db"


def test_salience_db_default_derives_from_data_root():
    cfg = load_env_config({})
    assert cfg.salience_db == cfg.data_root / "memory" / "salience_vnext.db"


def test_data_root_override_cascades_to_all_paths():
    cfg = load_env_config({"SOVERYN_DATA_ROOT": "/tmp/different"})
    assert cfg.lattice_db == Path("/tmp/different/memory/lattice_vnext.db")
    assert cfg.conversations_db == Path("/tmp/different/memory/conversations_vnext.db")
    assert cfg.souls_dir == Path("/tmp/different/memory/souls")
    assert cfg.pinned_memory_path == Path("/tmp/different/memory/pinned_memory.md")
    assert cfg.salience_db == Path("/tmp/different/memory/salience_vnext.db")
    assert cfg.recall_lattice_db == Path("/tmp/different/memory/lattice_vnext.db")


def test_per_path_env_override_wins_over_data_root_cascade():
    """If SOVERYN_LATTICE_DB is set explicitly, it overrides the data_root cascade."""
    cfg = load_env_config({
        "SOVERYN_DATA_ROOT": "/tmp/data",
        "SOVERYN_LATTICE_DB": "/explicit/path/lattice.db",
    })
    assert cfg.lattice_db == Path("/explicit/path/lattice.db")
    # Other paths still follow the cascade
    assert cfg.conversations_db == Path("/tmp/data/memory/conversations_vnext.db")


def test_no_soveryn_complete_in_loader_defaults():
    """Defense in depth: with default env (no overrides), no resolved path
    should mention soveryn_complete."""
    cfg = load_env_config({})
    for attr in ("data_root", "lattice_db", "conversations_db", "souls_dir",
                  "pinned_memory_path", "recall_lattice_db", "salience_db"):
        value = str(getattr(cfg, attr))
        assert "soveryn_complete" not in value, f"{attr} still points at museum: {value}"
