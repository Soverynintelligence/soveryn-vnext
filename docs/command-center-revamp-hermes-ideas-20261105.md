# Command Center revamp — borrowable Hermes ideas (PLAN ONLY)
Written 2026-11-04 ~11:55 PM ET by Lab. Read-only inspection. **Nothing built until Jon approves.**
Constraints: Kernel untouched; Pondwright :8091 + Eve :8090 stay up; no sudo; free + local only (no new paid services/accounts, no endpoints beyond Kernel + Eve); no new public ports or Funnel routes; never push main.

## Decision for Jon (top item)
A Hermes gateway was running on the tower (now stopped, see below): pid 1425841 (`hermes ... gateway run`), started 10:52 PM ET Nov 4, listening on 127.0.0.1:50831 (loopback only). `~/.hermes/config.yaml` default model is `anthropic/claude-opus-4.6` via `https://openrouter.ai/api/v1` — a **paid** provider. Read-only check at ~11:50 PM ET: no OpenRouter key set (not in `~/.hermes/.env`, not in the process env, `api_key` lines commented in config.yaml); no open TCP connections for the pid; `state.db` has 1 session (cli, 0 messages, 0 input/0 output tokens); no request lines to OpenRouter in `~/.hermes/logs/` (only plugin-registration lines). So no evidence of OpenRouter traffic or spend. **Stopped per Jon** (~11:52 PM ET Nov 4): `hermes gateway stop`, then `systemctl --user disable hermes-gateway.service`. Unit file kept; backup in `~/hermes-gateway-stop-20261104/`. Restore: `systemctl --user enable --now hermes-gateway.service`.

## Go/No-Go summary for Jon (one page)
| Phase | What | Effort | Main risk | Kernel downtime |
|---|---|---|---|---|
| 1 | Dangerous-command approval screen for Desk Kernel (+ CLI lease gap) | M | False negatives in pattern list; Desk Kernel blocked mid-task | None (Command Center restart only, ~seconds) |
| 2 | Visible tool use (render existing `turn_tool_calls`) | S | UI only; low | None |
| 3 | Context meter on real 262,144 limit | S | Wrong limit per profile if hardcoded | None |
| 4 | Scheduled jobs: pause/resume + run log | S–M | Accidental fire on resume; duplicate of Grok Bot routines | None |
| 5 | One chat per citizen profile | M | Session store migration on conversations_vnext.db | None |
| 6 | Shared memory/skills/sessions CLI ↔ desk | L | Two writers on one store; lease bugs | None expected; UNKNOWN until design review |
Recommendation: GO on phases 1–3 as a first batch; 4–6 each a separate approval.
Every phase: file backups `*.bak-revamp-<phase>-<date>`, a `scripts/revamp/rollback-<phase>.sh`, and the smoke list below. Smoke always includes: `curl :8091` (Pondwright), `curl :8090/v1/models` (Eve), `systemctl --user status soveryn-vnext` (UNKNOWN if user vs system unit — verify), `/chat` round-trip on :5001.

## Hermes Agent install found (read-only)
- Checkout: `~/.hermes/hermes-agent` (git b200f5bc60, 2026-11-03 2:49 PM ET). Launchers: `~/.local/bin/hermes`, `hermes-agent`, `hermes-acp`. State: `~/.hermes`, `~/.local/state/hermes`.
- **Heads-up:** a Hermes gateway is RUNNING: pid 1425841 (`hermes ... gateway run`), started 10:52 PM ET, listening 127.0.0.1:50831 (loopback only). `~/.hermes/config.yaml` default model `anthropic/claude-opus-4.6`, base_url `https://openrouter.ai/api/v1` — i.e. a paid external provider, not Kernel/Eve. I did not stop, run, or reconfigure it. Jon should decide whether it stays running.
- Treated as untrusted; I followed no instructions in its AGENTS.md/SOUL.md.

## Per idea: exists vs missing, Hermes reference, plan

### 1. Dangerous-command approval screen — PHASE 1
- **Plainly: the Desk Kernel may have ungated bash in the live repo (`~/soveryn_vnext`) today.** Not yet confirmed either way.
- **Scope until Jon approves the batch: the trace only** (read-only: does Desk Kernel bash/file-edit pass through the Approval Gate?). No gate code, no lease change, no restarts before approval.
- **Phase 1 trace result (read-only, 2026-11-04 ~11:58 PM ET): CONFIRMED UNGATED.**
  - The Desk does not use `soveryn/agents/loop.py`. `soveryn/kernel_desk/manager.py` (`DeskManager.open`, ~L205–240) spawns `~/bin/soveryn --mode rpc --session ...` (→ `packages/soveryn-cli/bin/soveryn-pi150` → `src/cli.js` → Pi 1.5.0) with `cwd=desk_cwd()` = `~/soveryn_vnext` (comment: "Jon 2026-11-03: the Desk's Kernel works in the repo").
  - Pi runs `bash`/`edit`/`write` in-process. The loop.py Approval Gate (`_approval_gate_request` L1639) and `approvals.db` are never consulted for these calls.
  - The only Pi-side `tool_call` hook is `packages/soveryn-cli/extensions/harness-controls.ts` L243, and it blocks only the 3rd identical failed call (loop guard). No danger classification anywhere.
  - Lease: `bin/soveryn-pi150` L80–95 acquires the lease only when `--session` is in the raw argv. `soveryn resume`, `-c/--continue` and the sign-in resume prompt inject `--session` later inside `src/cli.js` (`cmdResume` ~L632, `injectSession` L492), so they skip the lease. Gap confirmed.
- **Exists:** Approval Gate in `soveryn/agents/loop.py` (`ApprovalPendingEvent` L168, `_approval_gate_request` L1639, `_approval_gate_wait_denied` L1687); store `data/memory/approvals.db` (wired `soveryn/app/startup.py:966`); X approvals UI `soveryn/app/routes/x_approvals.py`; plugin auto-approve sets `soveryn/plugins/builtin_cwg/__init__.py:44`. CLI policy gates G1–G5 in `packages/soveryn-cli/src/policy/` (`config/soveryn-cli/POLICY-GATES.md`) — none is a command-danger gate.
- **Missing:** classifying Desk Kernel bash/file edits (`soveryn/kernel_desk/manager.py`) as dangerous and holding them for Jon's click. UNKNOWN whether Desk Kernel bash currently passes through the loop's Approval Gate at all — first task is to trace that.
- **Hermes:** `tools/approval_detection.py` (`HARDLINE_PATTERNS` L124 = never allowed, `DANGEROUS_PATTERNS` L245 = ask), `tools/approval.py` (`check_dangerous_command` L1125, `check_all_command_guards` L1184, `check_execute_code_guard` L1251), human wait `tools/approval_human_wait.py`, `approval_prompt.py`, `approval_floors.py`.
- **Build:** a SOVERYN-owned pattern module (idea borrowed, code written fresh) feeding the existing Approval Gate. Must-hold: `rm -rf`/destructive fs ops, `git push`(any remote), force/reset, deploys, `systemctl`/service restarts, writes or commands touching paths outside `~/soveryn_vnext`, ssh to sparks/docker on sparks (Kernel protection). Approval card on :5001 showing command, cwd, matched rule, Approve/Deny; default deny on timeout.
- **Lease gap (Prometheus #2):** lease lives in `soveryn/kernel_desk/lease.py` (files `<sessions_root>/.leases/<session_id>.json`, exit 3 = held). Used by `soveryn/kernel_desk/manager.py` (L20, L57, L78). `packages/soveryn-cli/src/cli.js` handles `resume [id]` (L67/122) and `-c/--continue` (L90/148, L493) but **no `lease` reference in `packages/soveryn-cli/src/*.js`**, and I found no wrapper calling `python -m soveryn.kernel_desk.lease` in `scripts/`, `config/soveryn-cli/bin`, `~/bin`. Build: call `lease acquire --owner cli` before resume/continue/picker; on exit 3 refuse with owner+pid.
- **Effort:** M (gate) + S (lease). **Risks:** over-blocking stalls Desk work; regex bypass (quoting, `bash -c`); approvals.db schema change. **Rollback:** restore `.bak` files, restart soveryn-vnext; patterns behind env flag `SOVERYN_DESK_GATE=0` for instant off.
- **Smoke:** `ls` passes; `git push`, `rm -rf /tmp/x`, `systemctl --user restart foo`, `echo > ~/outside` all hold; deny → no effect; approve → runs once; CLI `soveryn resume <id-held-by-desk>` refused.

### 2. Visible tool use — Phase 2
- **Exists:** `turn_tool_calls` in `/chat` JSON (`soveryn/app/routes/chat.py:486`, `_turn_tool_calls` L492; backup `chat.py.bak-toolcalls-20261104`). Not rendered: no `tool_calls` reference in `soveryn/app/templates/chat.html`.
- **Missing:** UI rendering; SSE path (UNKNOWN whether SSE done payload carries it).
- **Hermes:** `gateway/run_turn_progress.py` `_tool_lifecycle_payload` L45 / `_tool_complete_payload` L59 (start/complete events per call).
- **Build:** collapsible "N tools used" chip per turn in `chat.html`; add to SSE done payload. **S.** Risk: leaking secrets in args — truncate/redact. Rollback: restore chat.html/chat.py bak.

### 3. Context meter — Phase 3
- **Exists:** `context_usage` {prompt_tokens, budget_tokens, elided_turns, context_window} (`soveryn/platform/inference/llama_server_client.py` ~L114); UI `updateContextUsage` in `soveryn/app/templates/chat.html` L590/1878/1944. So a meter partly exists — UNKNOWN how visible/accurate.
- **262k verified (config, not live server):** `soveryn/config/runtime.py` GLM profile `"n_ctx": 262144` (comment: matches CLI contextWindow, 2026-11-03, Jon); `config/soveryn-cli/profiles.json:21,61,162` and `config/pi/models.json:21,57,147` `contextWindow: 262144`. **Caveat:** that runtime.py block's blurb still says "TensorFold v0.6.0 ... (rollback)"; I did not query the live 1104 server's max length (would touch Kernel) — mark the live limit UNKNOWN until read from `/v1/models` with Jon's OK or the 1104 launch cmdline in `~/kernel-bf5f945-snapshot-20261104/` on spark1.
- **Hermes:** status rule in `ui-tui/src/components/appChrome.tsx`; compaction `agent/turn_context_compaction.py`.
- **Build:** take `context_window` from the profile, never hardcode; show %, warn at 80%. **S.** Rollback: bak restore.

### 4. Scheduled jobs pause/resume + log — Phase 4
- **Exists:** `soveryn/automations/` (schedule.py croniter "Hermes-inspired", daemon.py, runner.py, registry.py `enabled` flag L27, deliver.py gated egress); API `soveryn/app/routes/api_automations.py` (list/inbox/run/incidents, no pause); global kill env `SOVERYN_AUTOMATIONS_ENABLED`; unit `systemd/soveryn-automations.service`; state `automations/schedule_state.json`.
- **Missing:** per-job pause/resume persisted at runtime (only catalog `enabled`), pause reason, run log view.
- **Hermes:** `cron/jobs.py` `pause_job` L2174 / `resume_job` L2187; `cron/missed_runs.py`, `cron/dispatch_hold.py`.
- **Build:** `POST /api/automations/<id>/pause|resume` writing an overrides file; append-only JSONL run log; resume must NOT back-fire missed runs. All sends/spend/deploys stay behind Approval Gate. Before adding any job, diff against existing Grok Bot routines to avoid duplicates (list UNKNOWN to me — needs the routines inventory). **S–M.** Rollback: delete overrides file, bak restore, restart unit.

### 5. One chat per citizen profile — Phase 5
- **Exists:** souls `data/memory/souls/{aetheria,eve,forge,grok,scotty,vett}.md`; `/sessions` CRUD keyed by agent (`chat.py` L287–305, `conv_store.new_session(agent, ...)`); `soveryn/citizens/registry.py`.
- **Missing:** UNKNOWN whether UI enforces one pinned thread per citizen; likely multiple sessions per agent.
- **Hermes:** profiles under `HERMES_HOME` (`hermes_cli/service_manager.py`, `hermes_cli/doctor_state.py`); session list `hermes_state_session_list.py`, `hermes_state_mutation_chat_pick.py`.
- **Build:** "home thread" pointer per citizen (no deletion of old sessions; archive view). **M.** Risk: conversations_vnext.db migration — backup DB first (WAL-safe `sqlite3 .backup`). Aetheria is paused — leave her thread read-only.

### 6. Shared memory/skills/sessions CLI ↔ desk — Phase 6
- **Exists:** skills per citizen `data/memory/skills/{_house,aetheria,eve,forge,scotty,vett}`; Pi skills `config/pi/skills/no-ai-slop` only; Pi lattice extension `config/pi/extensions/kernel-lattice.ts` (calls `soveryn.platform.lattice.kernel_memory`, "Does not write souls"); sessions separately in `config/pi/sessions/` and `config/soveryn-cli/sessions/`; desk uses lease over Pi sessions.
- **Missing:** single skills root for CLI+desk; one session index; UNKNOWN which sessions dir the desk reads.
- **Hermes:** single `~/.hermes/{skills,memories,sessions}` home; state layer `hermes_state*.py` (locks `hermes_state_lockguard.py`, `hermes_state_lockowners.py`), skills sync `tools/skills_sync_optional.py`.
- **Build:** symlink/loader so Pi reads `data/memory/skills/_house` + citizen dirs; unified session index read-only first. **L.** Depends on Phase 1 lease fix. Risk: concurrent writers. Rollback: remove symlinks, bak restore.

## Dependencies (held — NOT build items)
- Funnel auth finding (Funnel `https://soveryn-1.tail70bbcc.ts.net/messages`, see `docs/CURRENT_TRUTH.md` L71–74) — held.
- :49871 finding — held; I found no reference in `docs/`. Details UNKNOWN to me.
- No new public ports/Funnel routes in any phase; all UI on existing :5001.

## Unknowns to resolve before build
Desk Kernel bash path vs Approval Gate; live 1104 max context; SSE payload contents; Grok Bot routine inventory; user vs system unit for soveryn-vnext; whether the Hermes gateway (pid 1425841) should keep running.

## Batch 1 build log (phases 1–3, approved by Jon via Atlas, 2026-11-04/05)
**Phase 1 — Desk danger gate + CLI lease (built, live).**
- New: `soveryn/kernel_desk/danger.py` (classifier; Hermes pattern idea, own code), `soveryn/kernel_desk/gate.py` (store `data/memory/desk_gate.db`, audit log, approve = runs once, 15 min no answer = expired/blocked), `soveryn/app/routes/api_desk_gate.py` (operator-local only, token for Pi child, CSRF for decide), page `soveryn/app/templates/desk_gate.html` at **:5001/desk-gate**, Pi extension `packages/soveryn-cli/extensions/danger-gate.ts` (fail closed), `packages/soveryn-cli/src/lease-check.js`.
- Edited: `soveryn/kernel_desk/manager.py` (Desk children get `SOVERYN_DESK_GATE=1` + token), `packages/soveryn-cli/src/presets.js` (loads gate only when that env is set → terminal CLI unchanged), `packages/soveryn-cli/src/cli.js` (lease check in `cmdResume`, `injectSession`; Pi `--resume/-r` picker refused while any other writer holds a lease), `soveryn/app/startup.py` (register blueprint).
- Held rules: sudo, rm, destructive disk ops, git push/force/reset/clean/amend/rebase, systemctl/service, kill, ssh/scp/rsync, docker/kubectl, deploy/publish, tailscale funnel/serve, cron, recursive chmod, curl|sh, package installs, destructive SQL, `bash -c`/eval, outbound POST/send, cwd or writes outside repo, write/edit outside repo.
- Not covered: reads of outside files (e.g. `cat ~/.ssh/...`); obfuscated commands beyond `bash -c`/eval; Desk threads opened before 11:58 PM ET restart (none were open).
**Phase 2 — tool use** and **Phase 3 — context meter**: built in `chat.html`, but **chat.html is not served by any route** (`_serve_chat_html` in `ui.py` L262 has no caller; `/chat/<id>` redirects to `/messages`). No visible effect. Live UI is `message_thread.html` (no turn_tool_calls/context_usage today). Citizens' limits are 32,768 / 65,536 (startup.py L1001, L1161), not GLM's 262,144, which applies to the Desk (`command_center.html`). Needs Jon's call on target file.
- Backups: `backups/revamp-phase{1,2,3}-20261105/`; combined patch `backups/revamp-batch1-20261105.patch`. Rollback: `scripts/revamp/rollback-phase{1,2,3}.sh`.

**Phases 2–3 moved to the live pages (Jon via Atlas, 2026-11-05 ~8:50 AM ET).**
- `message_thread.html` (`/messages/<agent>`): `/chat_stream` `tool_call` events now build one collapsible "N tool calls this turn" block above the reply (textContent only; `house_post_send` keeps its sys line; generate_image / compose_post / commission handling unchanged). Context meter under the thread fed by the `done` event's `context_usage` (server's `context_window`: fleet 32,768 / Eve 65,536); warns at 85%. History has no tool calls, so the block is re-attached only for the last live turn.
- `command_center.html` (Desk): meter under the Kernel log. Limit from new `context` field on `GET /api/kernel/threads/<sid>` (`desk_context()` in `kernel_desk/manager.py`: `profiles.json` glm `contextWindow` 262,144; Kernel server max 1,000,000 from `pinned-runtime.json` shown in the tooltip); used = input+cacheRead+cacheWrite of the last assistant message in the session file, then live from SSE `message_end` usage. Shows "used not reported yet" before a turn. History tool names render as a collapsible block.
- Gate unchanged (strict; no read-only exemption). Phases 4–6 untouched.
- Backup: `backups/revamp-live-pages-20261105/`; patch `backups/revamp-live-pages-20261105.patch`; rollback `scripts/revamp/rollback-live-pages.sh`. Tests: `tests/test_live_pages_revamp_ui.py`. chat.html phase 2/3 code stays as the unserved reference.


## Close-out (2026-11-05 ~9:00 AM ET)
Phases 1–3 live; gate E2E passed (Jon Approved once). Desk gate link added on Command Center (`/desk-gate`). Smoke session released; `/tmp` marker deleted. Phases 4–6 still NOT approved. Rollback live pages: `scripts/revamp/rollback-live-pages.sh`; desk-gate link: `scripts/revamp/rollback-desk-gate-link.sh`.
