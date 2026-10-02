"""Point data / skills / persona roots at a tmp dir for hermetic tests.

The live checkout ``data/`` is machine-local (persona overrides, skill
indexes, routine overlays). Golden and plugin-boot tests must not read it.
"""
from __future__ import annotations

import shutil
from pathlib import Path

SKILLS_FIXTURE = (
    Path(__file__).resolve().parents[1] / "fixtures" / "cwg_split_2b" / "skills"
)


def isolate_data_root(
    tmp_path: Path,
    monkeypatch,
    *,
    seed_skill_fixtures: bool = False,
) -> Path:
    """Redirect SOVERYN_DATA_ROOT and SOVERYN_SKILLS_DIR under ``tmp_path``.

    Persona overrides stay empty (baked personas). When
    ``seed_skill_fixtures`` is true, copy the committed CWG 2b skill
    indexes so routines/skills goldens stay reproducible.
    """
    data_root = Path(tmp_path) / "hermetic-data"
    data_root.mkdir(exist_ok=True)
    (data_root / "memory" / "personas").mkdir(parents=True, exist_ok=True)
    skills = data_root / "memory" / "skills"
    if seed_skill_fixtures:
        if skills.exists():
            shutil.rmtree(skills)
        shutil.copytree(SKILLS_FIXTURE, skills)
    else:
        skills.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("SOVERYN_DATA_ROOT", str(data_root))
    monkeypatch.setenv("SOVERYN_SKILLS_DIR", str(skills))
    monkeypatch.delenv("SOVERYN_EMAIL_IDENTITIES", raising=False)
    return data_root
