# Kernel · Pi

House write harness. GLM `:8001`. Compaction is **off**. Output cap is 16k (OpenCode was 8k and auto-compacted).

Stay in the working tree. Prefer small diffs. Chess lives in `chess3d/` if that is cwd.

**File jobs (HTML/JS/CSS canvases, new modules):** first tool is `write` of a short skeleton (empty shell, tens of lines). Then `edit` in pieces. Never draft the full source in thinking — thinking counts against the 16k cap and the write never fires. `kernel --build` is thinking **low** for those jobs.

Secrets, sudo, force-push: stop and ask.
