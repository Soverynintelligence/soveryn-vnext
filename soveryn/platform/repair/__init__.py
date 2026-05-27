"""Repair grammar boundary for bounded self-repair recipes.

Scotty may eventually execute registered recipes through this platform layer,
but recipe authoring and tier policy stay human-reviewed. Phase 1 parses recipe
metadata only; it does not execute repair actions.
"""

from soveryn.platform.repair.recipes import (
    RepairRecipe,
    RepairRecipeError,
    RepairTier,
    load_recipe,
)

__all__ = ["RepairRecipe", "RepairRecipeError", "RepairTier", "load_recipe"]
