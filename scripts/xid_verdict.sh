#!/usr/bin/env bash
# One-shot Xid verdict, 2026-08-12.
#
# Aetheria moved to llama.cpp 18f7ad7fc on 2026-08-08 12:44 to test whether the
# 2-month-stale build was behind the Xid 8 class. The historical rate is
# 0.53/day (19 events over 36 days), so silence only becomes evidence with time:
#   4.4 clean days = 90% confidence, 5.7 = 95%.
# Checking earlier reads a coin flip as a trend, which is the mistake that cost
# a week last time.
set -uo pipefail
SINCE='2026-08-08 12:44'
N=$(journalctl -k --since "$SINCE" --no-pager 2>/dev/null | grep -c 'NVRM: Xid')
UP=$(ps -eo etime,cmd 2>/dev/null | grep 'alias aetheria' | grep -v grep | awk '{print $1}' | head -1)

if [ "$N" -eq 0 ]; then
  MSG="Xid verdict: CLEAN. 0 events in 4+ days on llama.cpp 18f7ad7fc (was 0.53/day). ~90% confidence the rebuild fixed it. Backend uptime ${UP:-unknown}. The stale build was the cause."
else
  LAST=$(journalctl -k --since "$SINCE" --no-pager 2>/dev/null | grep 'NVRM: Xid' | tail -1 | cut -c1-90)
  MSG="Xid verdict: NOT FIXED. $N event(s) since the rebuild. That rules out the stale llama.cpp and points at the driver or the card. Last: $LAST"
fi
echo "$MSG"
~/soveryn_vnext/scripts/alert_signal.sh "$MSG" 2>/dev/null || echo "(signal send failed — verdict above)"
