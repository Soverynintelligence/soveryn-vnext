# Automations H2H — Qwen 3.8 vs DeepSeek Flash (OpenCode)

**Date:** 2026-08-19 morning  
**Brief:** full Automations v0 dry-run (9 catalog entries, registry/runner/deliver, pytest, `--live` refuse)  
**Trees:** `tmp/automations-h2h-20260819/{qwen38,flash}/`

| | **Qwen 3.8** (`aetheria` @ `:8090`) | **DeepSeek Flash** (`bench-flash` @ `:8091`) |
|--|--|--|
| Wall clock | **~251 s (~4.2 min)** | **~23+ min then stuck** (killed) |
| Deliverables | Complete (registry, catalog×9, runner, deliver, tests, README, conftest) | None written (plan/compact loop) |
| Pytest | **14 passed** (independent re-verify) | n/a |
| `--list` / dry-run / `--live` refuse | All green | n/a |
| OpenCode issues | Clean finish | Repeated compaction (“provider size limit”), re-planned without writing |

## Verdict
**Qwen 3.8 wins this Automations build head-to-head** — faster and actually ships a verified dry-run layer. Flash remained in planning after context compaction and never produced files in ~23 minutes.

Implication: for Automations into the house, prefer **Qwen/OpenCode draft**, with Kernel/Flash as surgical review — not the primary multi-file builder on this hardware profile.
