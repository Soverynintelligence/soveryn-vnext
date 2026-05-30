# Phase 2b-ii-b2 Verification: Live Recall Cutover

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
