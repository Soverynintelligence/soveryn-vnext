#!/usr/bin/env bash
# verify.sh — the gate before any deploy or "done" claim on this repo.
# Green here, and only here, means: tests pass, code compiles, no secrets staged.
set -uo pipefail
cd "$(dirname "$0")/.."
fail=0

echo "── compile ──"
if ! python3 -m compileall -q soveryn/ 2>&1 | tail -3; then fail=1; fi

echo "── tests ──"
if command -v pytest >/dev/null 2>&1; then
  if ! timeout 600 python3 -m pytest -x -q 2>&1 | tail -4; then fail=1; fi
else
  echo "pytest missing in this env — install the soveryn conda env or run manually"; fail=1
fi

# CLI suite (audit hole #7, 2026-09-24): packages/soveryn-cli has 25 node
# tests that verify.sh never ran — CLI changes were only tested by hand.
if command -v node >/dev/null 2>&1 && [ -f packages/soveryn-cli/package.json ]; then
  echo "── cli tests ──"
  if ! (cd packages/soveryn-cli && timeout 300 npm test 2>&1 | tail -3); then fail=1; fi
fi

echo "── staged secrets ──"
if command -v gitleaks >/dev/null 2>&1; then
  if ! gitleaks protect --staged --redact --no-banner; then
    echo "staged changes contain likely secrets"; fail=1
  fi
fi

if [ $fail -eq 0 ]; then echo "VERIFY: GREEN"; else echo "VERIFY: RED — do not deploy"; fi
exit $fail
