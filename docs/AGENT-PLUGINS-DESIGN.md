# Agent Plugins Design (inventory + Week 1 DONE)

> Status: **Week 1 DONE** (2026-09-17 ET) — grants drive catalog tool registration at boot.  
> Week 2 (install/revoke API + auth stubs) not started.  
> Goal: Grok-Bot-style plugin catalog (catalog + install + auth + per-agent tools) for SOVERYN citizens.

## Reality check: where these agents live

| Surface | Aetheria / Eve / Kernel |
|---|---|
| SOVERYN Messages + AgentLoop | **Yes** — `ACTIVE_AGENTS` / `MESSAGES_CONTACTS` |
| Cursor / Grok Bot sidebar agents | **No** — house citizens only |
| Related | `data/memory/souls/grok.md` is a Messages coding-peer soul for Grok Build CLI; **not** in `ACTIVE_AGENTS`. Runtime comment: *“Grok is desktop Grok Bots, not a house chat agent.”* |

## Current architecture (paths)

| Concern | Path |
|---|---|
| Live roster | `soveryn/config/runtime.py` — `ACTIVE_AGENTS`, `MESSAGES_CONTACTS` |
| AgentLoop registry | `soveryn/agents/registry.py` |
| Tool capability registry | `soveryn/platform/tools/registry.py` (`ToolSpec` per `(owner, name)`) |
| Boot / wiring | `soveryn/app/startup.py` → `register_granted_packs(PackContext(...))` |
| Pack registrars | `soveryn/citizens/plugin_packs.py` |
| Turn loop | `soveryn/agents/loop.py` — `iter_tools_for_agent(agent_name)` |
| Personas | `soveryn/agents/personas.py` (+ `aetheria/persona.py`, Kernel tower prompt) |
| Souls | `soveryn/agents/souls.py` → `data/memory/souls/<agent>.md` |
| Skills (on-demand docs) | `soveryn/agents/skills.py` → `data/memory/skills/<agent>/` |
| Citizens census | `soveryn/citizens/census.py` |
| Connector catalog | `soveryn/citizens/connectors.py` |
| Board API | `GET /api/citizens/connectors` → `board_payload()` |
| UI chips | `soveryn/app/templates/citizens.html` |
| Map | `docs/KERNEL_SYSTEM_MAP.md` |

### What already exists (reusable)

`connectors.py` + `plugin_packs.py`:

1. **Catalog** — `CATALOG: ConnectorDef` (id, title, tools[], sovereignty class, notes)
2. **Per-citizen grants** — `FOUNDING_GRANTS` (aetheria / eve / kernel / vett / scotty)
3. **Armed checks** — env/unit presence (`email_armed`, `signal_armed`, …); `pondwright` is house-local
4. **Pack loader** — `PACK_REGISTRARS` + `register_granted_packs` at boot
5. **Approval Gate hooks** — `requires_approval(tool_name, source=…)`
6. **Board payload** for UI (read-only chips today)

**Still missing vs Grok Bot Plugins model (Week 2+):**

| Grok Bot Plugins | SOVERYN today |
|---|---|
| Browseable install catalog | Catalog exists; **no install/uninstall API yet** |
| OAuth / auth per plugin | Env vars + ad-hoc desks; **no plugin auth UX** |
| Enable plugin → tools appear | **Week 1:** grants ∩ armed load tools at **boot**; live flip still needs restart |
| Per-agent enablement UI | Grants hardcoded; board is read-only chips |
| External MCP servers | **None** — house ToolRegistry only |

### Per-agent tool shape (summary)

**Aetheria** — CoS / closer: lattice recall, personal files, soul origin, sandbox, steward, delegation, specialists, reflection, coord/DM, read files, kernel_child, library, audit, spark, web, email*, house_post, teammates brief, objectives, pondwright, system_probe, documents/intake/ledgers/QR, **signal_send**, messenger share/mark, dream, botdirectory, generate_image. **Off X.**

**Eve** — research + ship: web, git (via vett tools), pondwright, PDF, personal files, documents, house_post, email*, system_probe, spark, library, **read_x / post_to_x**, compose_post, eve_ig_*, GBP, GCal, Google desk, Canva, generate_image, cron_notepad.

**Kernel** — build: read/list files, **run_aider**, **run_opencode**, **kernel_child**, **kernel_run**, web, email*, house_post, documents/intake/ledgers/QR, botdirectory, cron_notepad, lattice get_node/recent (+ shared search when wired). Writes via Aider/OpenCode/Pi — not free bash on Messages.

\* email tools register only when `email_armed()` (SMTP + `SOVERYN_EMAIL_PRODUCTION=1`).

Grants snapshot (`FOUNDING_GRANTS`): see `soveryn/citizens/connectors.py`.

---

## Week 1 — DONE: grants are the loader

### How to enable a tool pack today

1. Add the pack id to that citizen’s tuple in `FOUNDING_GRANTS` (`soveryn/citizens/connectors.py`).
2. Ensure `connector_armed(pack_id)` is true (env / house-local).
3. **Restart the SOVERYN app** — `ToolRegistry` has no unregister; packs register once at boot. The citizens board remains **read-only** (chips reflect grant ∩ armed; flipping grant in code without restart does not change live tools).

### Boot path

`startup.py` builds a `PackContext` (registry, searxng, env, messenger, lattice, signal, document/delegation stores, extras including Eve X registrar) and calls:

```python
register_granted_packs(PackContext(...), owners=tuple(FOUNDING_GRANTS.keys()))
```

Non-catalog tools stay imperative in startup (lattice recall, sandbox, canva, botdirectory, dream, intake/ledgers/QR, cron notepad, personal_files, aetheria-specific, mark_share, aetheria `kernel_child`, specialists, …).

### Pack → tools map (`PACK_REGISTRARS`)

| Pack | Tools / register surface | Typical owners (grant ∩ prior behavior) |
|---|---|---|
| `web` | `register_web_tools` (web_search, fetch_url) | aetheria, vett, eve, kernel |
| `email` | `register_email_tools` | founding when email armed |
| `house_post` | `register_house_post_tools` | all founding |
| `pondwright` | `register_pondwright_tools` | aetheria, vett, eve |
| `system` | spark_status + system_probe (owner subsets) | spark: aetheria/vett/scotty/eve; probe: vett/aetheria/eve |
| `delegation` | `register_delegation_tools` | aetheria only |
| `git` | `register_vett_git_tools` | vett, eve (kernel grant no-ops) |
| `patrol` | `register_vett_patrol_tools` | vett only |
| `documents` | `register_document_tools` | aetheria, vett, eve (kernel grant no-ops) |
| `files` | read_file + list_directory | aetheria/vett/eve/kernel (scotty via code pack) |
| `code` | scotty tools **or** kernel aider/opencode/child/run | scotty, kernel |
| `signal` | `register_signal_send_tool` | aetheria only |
| `messenger` | deliberate_share + list_my_outbound | aetheria, vett |
| `x` | read_x + post_to_x (via startup extras callback) | eve |
| `social` | compose_post, eve_ig, gbp, gcal, google_desk | eve |

### Gaps fixed in Week 1

- `pondwright` was falling through to `unknown connector` in `connector_armed` — now house-local armed.
- Catalog `register_*` loops removed from `startup.py` (no double-register).

---

## Week 2 — catalog UX + auth stubs (not done)

1. Extend `/api/citizens/connectors` with `install` / `revoke` that mutate a durable grant file (`data/citizens/plugin_grants.json` or DB column) — Jon-only.
2. Auth: per-pack `needsAuth` + link to existing flows (`canva` tokens, `python -m soveryn.platform.social.agent_desk login eve google`, Signal env) — **no** generic OAuth broker yet.
3. Optional: thin MCP **client** adapter later (external servers → ToolSpec) — only after house packs are grant-driven; do not block on MCP protocol.
4. Still: restart required after grant flip until `ToolRegistry` supports unregister / hot reload.

### Out of scope (near term)

- Publishing house agents as Cursor/Grok Bot sidebar agents
- Full MCP server hosting for the house
- Auto-install of arbitrary third-party packs without Gate + sovereignty class
