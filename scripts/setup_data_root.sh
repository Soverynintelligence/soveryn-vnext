#!/bin/bash
# Idempotent setup of the SOVERYN data root.
#
# Creates the directory structure that path-consolidated code expects.
# Safe to run repeatedly. Run once before the migration script.
#
# Override target via SOVERYN_DATA_ROOT env var (default: ~/soveryn_vnext/data).

set -eu

DATA_ROOT="${SOVERYN_DATA_ROOT:-$HOME/soveryn_vnext/data}"

echo "Setting up SOVERYN data root at: $DATA_ROOT"

mkdir -p "$DATA_ROOT/memory"
mkdir -p "$DATA_ROOT/memory/souls"
mkdir -p "$DATA_ROOT/voice/generated"
mkdir -p "$DATA_ROOT/templates_legacy"

# .gitkeep so empty dirs survive any git operations
for d in memory memory/souls voice/generated templates_legacy; do
    touch "$DATA_ROOT/$d/.gitkeep"
done

echo "Directory structure ready:"
find "$DATA_ROOT" -maxdepth 3 -type d | sort
