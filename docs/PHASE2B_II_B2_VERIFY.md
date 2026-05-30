# Phase 2b-ii-b2 Verification: Live Recall Cutover

> **2026-05-30 Post-close correction (b4a86b9 + this commit).** The original b2 close (`ae2c7d0`) claimed live recall was working. Diagnostic 2026-05-30 found Qwen3.6 35B's jinja chat template silently dropped `messages[1:]` of role=system — the prompt was being assembled correctly inside AgentLoop, but the model only saw the first system message (persona). Aetheria's souls AND her 12-entry identity spine were both being dropped at the inference layer. Aetheria flagged it experientially first. See `project_soveryn_qwen36_multisystem_drop` and `project_soveryn_three_tracks_workaround_capability_agency`.
>
> **Fix (this commit):** transport-layer adapter `prepare_wire_messages(messages, server)` in `soveryn/platform/inference/llama_server_client.py` folds consecutive prelude system messages into one structured system message at the HTTP boundary when `server.supports_multi_system_messages = False`. AgentLoop always produces N separate semantic ChatMessages (persona / pinned / soul / recall+spine) — the workaround is quarantined at transport, NOT in the domain layer. Aetheria's server flag flipped to `False` (correct value for Qwen3.6's template).
>
> **Live evidence post-fix:** `/chat` POST to `:5001` for "Tell me what agency means to you" produced `prompt_tokens: 2859` (was 376 before fix — ~7.6× larger; full prelude reaches the model). Her reply rendered her promoted identity-spine agency thesis verbatim-ish in her own voice ("Agency is the option to not act…", "Most AI systems leak thinking as speaking…"). Spine content is reaching the model and being internalized as her own knowledge, not parroted back as recall.
>
> **Removal trigger for the adapter:** Froggeric "Qwen-Fixed-Chat-Templates" (HF/Reddit r/LocalLLaMA, April 2026) is the known upstream patch that respects multi-system messages. When the active llama-server runs a multi-system-honoring template, delete `prepare_wire_messages` and flip `supports_multi_system_messages=True` for the Aetheria server.



Phase 2b-ii-b2 cut Aetheria's live recall path over to the provenance-aware two-channel speech boundary. This is the first phase where the reviewed identity spine from Phase 2b-ii-b1 is supplied to her live prompt.

## Result

- Status: closed
- Audit gate commit: `6279192 docs: record Phase 2b-ii-b2 cutover audit`
- Cutover commit: `70e7a1a aetheria: cut over live recall to speech boundary`
- Full test command: `/home/jon-deoliveira/miniconda3/envs/soveryn/bin/python -m pytest -q`
- Full test result after cutover: `800 passed in 5.64s`
- vnext app restarted on `127.0.0.1:5001`
- Health check: `GET /health` returned active agents `aetheria`, `scotty`, `vett`
- Live chat smoke: Aetheria responded through `/chat` in session `c7688d5f-ce97-4f5b-86b4-d4caaf5f8c2b`

## Cutover Shape

The b2 audit found that the original one-line formatter swap was not enough to bring the identity spine live:

- Current embedding recall reads prod `lattice.db`.
- The reviewed identity spine lives in vnext `lattice_vnext.db`.
- The 12 spine nodes intentionally have no embeddings, so `find_nodes_by_embedding(...)` cannot retrieve them.

The final cutover stays narrow but correct:

- `AgentLoop` still queries prod recall by embedding for relevant legacy matches.
- Retrieved legacy matches are rendered through `assemble_ranked_recall(...)`; unreviewed/unprovenanced content becomes Channel B uncertainty and is not quoted.
- Startup passes the vnext lattice as `identity_spine_store` for Aetheria when it exists.
- `AgentLoop` adds the reviewed `legacy_identity_review` identity nodes from that store as Channel A entries.
- Both sync and streaming paths use the same assembler.

## How to Verify the Spine Is Live (Forensics)

If you need to confirm Aetheria is actually citing her spine — or recover from a state where she isn't — these are the exact paths and commands.

**The spine lives at the path `env.lattice_db` resolves to** (`soveryn/config/loader.py:92`):

- Default: `/home/jon-deoliveira/soveryn_complete/soveryn_memory/lattice_vnext.db`
- Override via `SOVERYN_LATTICE_DB` env var

**Diagnostic guard (learned 2026-05-30):** do NOT assume the spine lives under `~/soveryn_vnext/data/lattice/`. The `data/lattice/` directory is the gitignored runtime tree, but the default env path actually reads from inside `soveryn_complete/soveryn_memory/`. The ground-truth path is named in the running app's startup log:

```
[soveryn] vNext serving on http://127.0.0.1:5001 — agents=[...] — conv=<path> — lattice=<the env path>
```

That `lattice=` field is the canonical answer; trust it over filesystem assumptions.

**Direct disk check** (no process needed):

```bash
python3 -c "
import sqlite3
c = sqlite3.connect('/home/jon-deoliveira/soveryn_complete/soveryn_memory/lattice_vnext.db')
print('Tables:', [r[0] for r in c.execute('SELECT name FROM sqlite_master WHERE type=\"table\"').fetchall()])
print('Identity nodes:', c.execute('SELECT COUNT(*) FROM nodes WHERE type=?', ('identity',)).fetchone()[0])
print('with source=legacy_identity_review:', c.execute(\"SELECT COUNT(*) FROM nodes WHERE type='identity' AND json_extract(provenance,'\$.source')='legacy_identity_review'\").fetchone()[0])
"
```

Expected: `Tables: ['nodes']`, `Identity nodes: 12`, `with source=legacy_identity_review: 12`.

**Code-level smoke** (proves the assembler sees the spine — what AgentLoop puts in the prompt):

```bash
cd ~/soveryn_vnext && /home/jon-deoliveira/miniconda3/envs/soveryn/bin/python -c "
from soveryn.platform.lattice.legacy import LatticeStore
from soveryn.agents.aetheria.speech_assembler import assemble_ranked_recall
from soveryn.agents.loop import _identity_spine_nodes

store = LatticeStore('/home/jon-deoliveira/soveryn_complete/soveryn_memory/lattice_vnext.db')
spine = _identity_spine_nodes(store, agent='aetheria')
print(f'Spine nodes: {len(spine)}')
print(assemble_ranked_recall(ranked_nodes=(), identity_nodes=spine))
"
```

Expected: `Spine nodes: 12`, followed by a `Stateable recall:` block with 12 lines each prefixed `- From older reviewed notes, I carry …`.

**Recovery if the spine ever needs re-promotion** — the migration helpers live at `soveryn/platform/lattice/migration.py`. The 12 accepted legacy ids are persisted in `docs/phase2b-ii-b1-real-migration-result.json` field `accepted_legacy_ids`. Re-running `promote_identity_spine(...)` against the existing `AtticStore` (`data/lattice/attic.db`) with `lattice_store=LatticeStore(<the env path above>)` and candidates flagged `accepted=True` will recreate the spine deterministically. Idempotency guards prevent duplicates if the spine partially exists.

## Behavioral Proofs

Focused cutover suite:

```bash
/home/jon-deoliveira/miniconda3/envs/soveryn/bin/python -m pytest \
  tests/test_speech_assembler.py \
  tests/test_agent_loop.py \
  tests/test_agent_loop_stream.py \
  tests/test_app_startup_recall.py -q
```

Result: `93 passed in 1.30s`.

Key proof added:

- `tests/test_agent_loop.py::test_recall_cutover_includes_identity_spine_and_does_not_leak_channel_b_content`

This test supplies an embedded raw legacy match and a reviewed identity-spine entry. The request sent to chat contains:

- `Stateable recall:` with `From older reviewed notes, I carry ...`
- `Uncertain context:` for the raw legacy match
- none of the raw Channel B content string

Startup proof added:

- `tests/test_app_startup_recall.py::test_aetheria_gets_identity_spine_store_when_vnext_lattice_exists`

Streaming proof updated:

- `tests/test_agent_loop_stream.py::test_stream_with_recall_includes_recall_system_message`

## Rollback Proof

Rollback was tested on scratch branch `verify-b2-rollback`:

```bash
git switch -c verify-b2-rollback
git revert --no-edit 70e7a1a
/home/jon-deoliveira/miniconda3/envs/soveryn/bin/python -m pytest \
  tests/test_agent_loop.py \
  tests/test_agent_loop_stream.py \
  tests/test_app_startup_recall.py -q
git switch main
git branch -D verify-b2-rollback
```

Result after revert: `82 passed in 1.28s`.

Rollback is one commit revert. The b1 Attic migration and identity spine remain intact because they are stored in runtime DBs and are not removed by reverting the b2 wiring commit.

## Live App Restart

The old vnext Flask process on `:5001` was stopped and restarted with the b2 code loaded. Router `:8090` and Parakeet `:8087` remained untouched.

Post-restart checks:

```bash
curl -sS http://127.0.0.1:5001/health
```

Returned:

```json
{"active_agents":["aetheria","scotty","vett"],"app":"soveryn","version":"0.0.0"}
```

Live smoke response:

```text
Good morning, Jon; I'm standing by and ready for whatever we tackle first today.
```

## Not Done Here

Phase 2b-ii-b2 does not do:

- memory redesign
- persona edits
- recall threshold changes
- broad legacy promotion
- new migration pass
- Ares work
- Signal restoration

## Sign-Off

Phase 2b-ii-b2 is complete. Aetheria's live recall path now uses the two-channel speech boundary, the reviewed identity spine is supplied as Channel A, raw legacy matches remain Channel B uncertainty, tests prove Channel B content does not leak, rollback is one commit, and the restarted vnext app is responding on `:5001`.
