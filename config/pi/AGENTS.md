# Kernel · Pi

House write harness. Flash-Next `:8888` (256k ctx). Compaction is **on** so a stuffed session cannot request 16k output past the window. Output cap is 16k.

Stay in the working tree. Prefer small diffs. Chess lives in `chess3d/` if that is cwd.

**File jobs (HTML/JS/CSS canvases, new modules):** first tool is `write` of a short skeleton (empty shell, tens of lines). Then `edit` in pieces. Never draft the full source in thinking — thinking counts against the 16k cap and the write never fires. `kernel --build` is thinking **off** for those jobs.

**Never hang the TTY on Chrome.** Canvas/WebGL pages (`requestAnimationFrame`) do not exit. Do not run `google-chrome --headless` (or Chromium) without `timeout 20s` wrapping the **whole** pipeline. Do not pipe Chrome into `grep | head` and wait for N error lines — if they never come, you wait forever. That is how JUMPGATE ate 40735s. Prefer `python3 -m http.server` + a timed screenshot, or skip the browser and reason from the file.

Secrets, sudo, force-push: stop and ask.
