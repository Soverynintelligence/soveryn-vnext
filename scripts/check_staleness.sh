#!/usr/bin/env bash
# check_staleness.sh — per-line staleness check for docs/CURRENT_TRUTH.md.
#
# Scans the truth file for YYYY-MM-DD dates. Prints "STALE: <line>" for every
# line containing a date older than 7 days before today; otherwise prints
# "OK: no stale rows". Exits 0 either way.
#
# Deps: grep, awk, date. Usage: bash scripts/check_staleness.sh

set -u

REPO="$(cd "$(dirname "$0")/.." && pwd)"
TRUTH="$REPO/docs/CURRENT_TRUTH.md"

if [ ! -f "$TRUTH" ]; then
    echo "check_staleness: truth file not found: $TRUTH" >&2
    exit 1
fi

TODAY=$(date +%Y-%m-%d)
CUTOFF=$(date -d "$TODAY - 7 days" +%Y-%m-%d)

STALE=$(grep -E '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]' "$TRUTH" \
    | awk -v cutoff="$CUTOFF" '
    {
        s = $0
        stale = 0
        while (match(s, /[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]/)) {
            if (substr(s, RSTART, RLENGTH) < cutoff) { stale = 1; break }
            s = substr(s, RSTART + RLENGTH)
        }
        if (stale) print "STALE: " $0
    }')

if [ -n "$STALE" ]; then
    printf '%s\n' "$STALE"
else
    echo "OK: no stale rows"
fi

exit 0
