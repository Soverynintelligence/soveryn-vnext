# SOVERYN tool packs

Harness-side tool surface for Pi 0.74.2. Packs select `--tools` and `--extension`s.
**Not** fixed by long SOVERYN.md lectures — Kernel gets real callable tools.

## Packs

| Pack | Pi tools | Extensions | When |
|---|---|---|---|
| `standard` | default built-ins (`read,bash,edit,write`) | `harness-controls` | default |
| `minimal` | `bash,edit` | `harness-controls` | `--minimal` / tiny fixes |
| `web` | `read,bash,edit,write,web-api-probe,html-module-host,open-html` | `harness-controls` + `web-pack` | cathedral / canvas / HTML |

`--pack` and `--preset` are aliases. Env: `SOVERYN_PACK=web`.

## Web pack tools (real capabilities)

| Tool | What it does |
|---|---|
| `web-api-probe` | Live Chromium `typeof` / existence for named APIs (`AudioContext`, `WebGL2RenderingContext`, `canvas.getContext`, …). Bounded by `timeout 20s`. |
| `html-module-host` | Exit A scaffold: writes `host.html` loading modules as `<script type="module">` — **no bundler**. Default modules: `core.mjs,kit.mjs,world.mjs,render.mjs`. |
| `open-html` | Open HTML/URL in Chrome with house timeout; optional `--screenshot out.png`. |

CLI twins (bash-callable):

```bash
node packages/soveryn-cli/scripts/web/web-api-probe.mjs AudioContext WebGL2RenderingContext
node packages/soveryn-cli/scripts/web/html-module-host.mjs --dir . --out host.html
node packages/soveryn-cli/scripts/web/html-module-host.mjs --serve --port 8765
node packages/soveryn-cli/scripts/web/open-html.mjs host.html --screenshot /tmp/cat.png
```

Chrome: `/usr/bin/google-chrome` or `CHROME_BIN`. If missing, probe exits 2 and doctor G7 warns.

## Auto-detect (phase router)

`web` is selected when (first match wins after CLI/env):

1. `--pack web` / `--web` / `SOVERYN_PACK=web`
2. `package.json` `soverynPack: "web"` or `.soveryn-pack` / `SOVERYN_PACK` file
3. cwd/path contains `cathedral*` / `phosphor*` / `canvas*`
4. Exit A shape: `core.mjs+kit.mjs+world.mjs+render.mjs`, or ≥2 `.mjs` with canvas/WebGL/Audio signals
5. cwd is `$HOME` and `~/sandbox` has a `cathedral*` / `phosphor*` / `canvas*` dir, or canvas/WebGL HTML — so Kernel launched from home still gets web tools

Incidental `*.html` demos in `soveryn_vnext` root do **not** trip web. Home-dir detect scans `~/sandbox` only.

## Cathedral launch

```bash
cd ~/sandbox/cathedral81
soveryn --pack web --build
# or rely on auto-detect:
soveryn --build
# visual gate:
soveryn --pack web --showme --build
```

Prefer Exit A (ES modules host) over inventing Vite/webpack APIs. Probe before writing Audio/WebGL code.

## Harness controls (every pack)

Loaded via `extensions/harness-controls.ts`:

- **Evidence sidecar** — every `tool_result` → `<cwd>/.soveryn/evidence/tools.jsonl` (survives compaction); `/evidence` command
- **Loop guard** — blocks 3rd identical failed tool call (`SOVERYN_LOOP_GUARD`, default 3). Chrome/headless dumps that print `DT_FAIL` / `verdict=*FAIL` / `Error:` / traceback count as failures even when the tool returns OK. Chrome bash fingerprints by kind + target file so flag nits still collide.
- **G6 claims** — annotates assistant `done/fixed/pass` without recent successful tool evidence
- **`--showme`** — annotates visual-done claims lacking screenshot / `file://` / `open-html` artifact

## Pi built-ins inventory (0.74.2)

Built-in tool names: `read`, `bash`, `edit`, `write`, `grep`, `find`, `ls`.  
Default coding surface: `read,bash,edit,write`. **No** browser/DOM/Chrome built-in — house supplies web pack.

## Gates (doctor executes)

`soveryn doctor --gates` runs G1–G8. Results append to `<cwd>/.soveryn/evidence/tools.jsonl` as `GATE PASS|FAIL … exit=N` (survives compaction).

Chrome/JUMPGATE bound is **inside** `web-api-probe` / `open-html` via `timeout ${SOVERYN_CHROME_TIMEOUT:-20}s` — not a prose reminder.
