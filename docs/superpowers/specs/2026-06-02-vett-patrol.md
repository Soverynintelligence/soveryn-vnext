# V.E.T.T. — Research Patrol Loop

**Status:** spec drafted; implementation gated on (1) heartbeat dry-run bake completing cleanly and (2) Jon settling external-source infrastructure decisions noted below
**Drafted:** 2026-06-02 morning
**Predecessor:** `feat(heartbeat): spontaneous initiation daemon` (vnext 32242ba). Same daemon shape; different domain.
**Scope:** ~full day for the daemon itself; the external-source infrastructure (patrol list, web tools, optional RSS) is a separate workstream that can ship independently.

## Goal

Give V.E.T.T. spontaneous initiation in *his shape* — research patrol over external sources, not internal board audit. Where Aetheria's heartbeat is *"check our state, decide if anything wants action"*, Vett's patrol is *"check the world, decide if anything wants reporting."*

Per Aetheria's spec from 2026-06-02: *"V.E.T.T.'s 'research patrol' is a different beast entirely. He needs a different trigger (e.g., new external data sources) and a different prompt. I'll be the one who wakes V.E.T.T. up via the boards if I find something he needs to look at."*

The patrol loop is the *spontaneous* half of that pair. Aetheria-triggered work flows to Vett through webhook routing (a small rule addition). Patrol-triggered work flows from Vett's own initiative.

## How this differs from Aetheria's heartbeat

| Dimension | Aetheria heartbeat | Vett patrol |
|---|---|---|
| **Trigger** | Pure timer (interval + backoff) | Timer + external-source-change detection + optional Aetheria-driven assignments |
| **Cadence** | 30 min (fast — boards change fast) | 4-6 hours (slow — external sources change slowly; respect web etiquette) |
| **Domain** | Internal: board state + lattice activity | External: patrol sources (URLs, feeds, search terms) + internal lattice signals about her tracked domains |
| **Prompt frame** | Active Auditor (audit boards / sift lattice / act-or-silence) | Patrol Briefing (sources to check / what changed / findings worth posting) |
| **Output** | Coord board posts (Signals to Aetheria, possibly Frictions) | Coord board posts (Signals only — Vett doesn't promote to Blueprint or arbitrate Friction) |
| **Tools needed** | Existing coord tools + lattice read tools | Existing coord tools + **web_search + web_fetch (need to port from old SOVERYN)** + patrol-list read/update |
| **Infrastructure prereq** | None beyond existing lattice + boards | Patrol source list (file or DB table) + per-source last-visited tracking |
| **Failure mode if model degenerates** | Posts a noise Signal Aetheria can archive | Posts a noise Signal AND may have hammered external services — needs polite-fetch discipline |

## In scope

### Module layout
```
soveryn/agents/vett/
├── __init__.py
├── patrol/
│   ├── __init__.py
│   ├── daemon.py        # process loop, mirrors heartbeat.daemon
│   ├── trigger.py       # eligibility gates (interval, source-change check, etc.)
│   ├── prompt.py        # Patrol Briefing construction
│   └── source_list.py   # read/manage Vett's patrol targets
└── tools/
    ├── __init__.py
    ├── web_search.py    # ported/rebuilt from old SOVERYN
    └── web_fetch.py
```

### systemd user unit
`/home/jon-deoliveira/.config/systemd/user/soveryn-vett-patrol.service`:
- After `soveryn-vnext.service`, PartOf `soveryn.target`, ExecStartPre health gate
- Restart=on-failure, RestartSec=15
- Starts in `SOVERYN_VETT_PATROL_DRY_RUN=true`; flip after the daemon's own 24-48h bake
- Independent log: `/tmp/soveryn-vett-patrol.log`
- Independent feature flag: `SOVERYN_VETT_PATROL_ENABLED`

### Eligibility gates (`trigger.py`)
Same shape as heartbeat's eligibility model, different specifics:
- **Disabled** — `SOVERYN_VETT_PATROL_ENABLED=false`
- **Interval** — last patrol completion ≥ `SOVERYN_VETT_PATROL_INTERVAL_SECONDS` (default 14400 = 4 hours, slower than heartbeat)
- **Backoff** — skip if Vett's sessions (webhook or chat) updated in last `SOVERYN_VETT_PATROL_BACKOFF_SECONDS` (default 1800 = 30 min). Don't patrol right after Aetheria assigned him work via webhook — let him finish that first.
- **Quiet hours** — same `HH:MM-HH:MM` spec format. Default `""` (always on). Web etiquette doesn't usually require quiet hours but might be useful if some sources rate-limit by time-of-day.
- **No sources to patrol** — if source_list is empty, skip with reason `"no_sources"`. Loud signal that the daemon's running but has nothing to do.

### Patrol Briefing prompt (`prompt.py`)
Plain text only, same anti-scratchpad-markup discipline as Aetheria's heartbeat. Tight, quantitative, no demands.

```
[PATROL]
{hours_since_last_patrol}h since your last patrol.

Sources on your list ({n_sources}):
{compact source listing — name + last_visited + change-detected flag}

Aetheria-tagged domains in recent lattice activity:
{list of high-salience domains she or the system flagged}

You have web_search and web_fetch tools. On this patrol, decide:
1. Which sources actually changed since you last checked them. Use web_fetch
   to confirm if you're unsure.
2. Whether any change is worth a Signal post to the boards. Signals are
   *leads* — unverified. Aetheria triages from there.
3. Whether any Aetheria-tagged domain wants new investigation.

If nothing on the patrol pulls at you, a one-line "nothing actionable from
this patrol" is a complete response. Don't post just to post — Signal noise
is your highest cost.
```

Design rules (same as heartbeat):
- Plain text. No scratchpad markup of any kind.
- Quantitative context (hours since, number of sources, etc.).
- Patrol introduces itself as a patrol. No "Jon asks..." framing.
- Explicit permission for silence — *especially* important here because Vett's first failure mode is "post a Signal about every fetched URL just to look busy."

### Per-patrol logic (`daemon.py`)
```
1. Sleep until next patrol slot (interval gate).
2. Check eligibility (disabled / backoff / quiet_hours / empty_source_list).
3. Eligible: build the patrol briefing.
   - Read source_list (with last_visited timestamps)
   - Query lattice for recent high-salience nodes tagged for his tracked domains
   - Construct briefing prompt
4. If dry-run: log what would happen (sources listed, briefing constructed, no fetches), sleep.
5. Else: ensure durable [patrol] vett session; invoke /chat with the briefing.
6. The model uses web_fetch / web_search to actually look at sources during
   the chat round. Each fetch updates that source's last_visited timestamp.
7. Findings come out as create_coordination_node calls (Signal board posts).
8. Record the patrol run in vett_patrol_log: triggered_at, completed_at,
   sources_visited, signals_posted, error.
9. Loop.
```

### Audit log
Add `vett_patrol_log` table to lattice schema (idempotent CREATE IF NOT EXISTS):
```sql
CREATE TABLE IF NOT EXISTS vett_patrol_log (
    id                TEXT PRIMARY KEY,
    triggered_at      TEXT NOT NULL,
    completed_at      TEXT,
    eligible          INTEGER NOT NULL,
    skip_reason       TEXT,
    sources_visited   INTEGER,
    signals_posted    INTEGER,
    error             TEXT,
    dry_run           INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_vett_patrol_log_triggered ON vett_patrol_log(triggered_at DESC);
```

### Webhook routing rule additions
`soveryn/platform/coordination/routing.py` gets two new rules per the
Aetheria-can-wake-Vett pattern:
- `NODE_CREATED` on Blueprint where `owner == "vett"` → Vett (currently this routes to Aetheria for review; refine to ALSO route to the owner)
- `PROMOTED` to Blueprint where `target.owner == "vett"` → Vett (currently routes universally to Scotty; needs owner-awareness, which was already on the Phase E follow-up list)

The owner-aware routing refinement and Vett's webhook reachability are the same piece of work. Ship them together.

### Patrol source list (`source_list.py`)
Open design question. Two reasonable shapes:

**Option A — Static config file** at `/home/jon-deoliveira/soveryn_complete/soveryn_memory/vett_patrol_sources.yaml`:
```yaml
- url: https://example.gov/grants
  kind: rss
  domain: funding
  visit_every_hours: 6
- url: https://arxiv.org/list/cs.AI/recent
  kind: html
  domain: research
  visit_every_hours: 24
  keywords: [sovereign, MoE, on-device]
```
Pros: trivially editable, source-controlled, no DB table needed. Cons: requires Jon to edit YAML; Aetheria can't dynamically add sources.

**Option B — Lattice-native** — sources are nodes with `type='patrol_source'`, and Aetheria can post-tool-add them via a new `register_patrol_source` tool.
Pros: Aetheria can extend the patrol list autonomously; same audit trail as everything else. Cons: more moving parts; harder to edit by hand; another tool to register.

**Recommendation:** start with **Option A** (YAML file). Aetheria can post a Signal saying *"add this source to Vett's patrol"* and Jon edits the YAML. After 2-4 weeks of usage, decide whether Option B is worth the added surface area. Match the "let behaviour create the data, then we codify it" pattern from the coord weight scoring.

### Tools to register for Vett
- **`web_search`** — port from old SOVERYN's `tools/web_search_tool.py`. Wrap a search engine API (DuckDuckGo HTML scrape is fine — no key required). Returns top N results with title + snippet + url. Result cap.
- **`web_fetch`** — port from old SOVERYN's `tools/web_fetch_tool.py`. GET with reasonable timeout (30s), bounded body size (500 KB), text/html/markdown content only (refuse images/binaries), user-agent identifying SOVERYN. Returns extracted text.
- **`read_patrol_sources`** — returns Vett's current patrol list with last_visited timestamps. Read-only.
- **`mark_source_visited`** — updates last_visited for a source after Vett fetches it. Internal bookkeeping.

All bounded. No write-to-disk beyond the last_visited timestamps. No arbitrary HTTP methods (GET only). No following redirects to dodgy hosts (allowlist or just refuse non-HTTP/non-HTTPS schemes).

## Out of scope (intentional defer)

- **Implementation right now.** The heartbeat is still in dry-run bake. Wait until that proves the daemon pattern works in practice. Spec captures intent; build follows.
- **RSS subscription handling.** v1 polls URLs directly. RSS feed parsing is just one type of `kind` field in the YAML — but real subscription state (per-entry ID tracking, etc.) is more infrastructure than v1 needs. Add when concrete usage shows polling isn't enough.
- **Aetheria-driven source-list updates as a tool.** Static YAML for v1. Tool-driven only if Option A proves friction-y.
- **Cross-source deduplication.** If two sources surface the same news, Vett may post two Signals. Aetheria can dedupe via Friction or archive. Don't pre-solve.
- **Login-protected sources.** No auth-required fetches. If a source needs auth, that's a separate hardening discussion.
- **Email patrol** (read Gmail for inbound research material). Different infrastructure entirely; would need OAuth + Gmail API. Out for now.
- **Watching specific GitHub repos** for releases. Same as RSS — could ship later as a typed source kind.
- **Vett triggering Scotty directly.** Vett's outputs go to Signal board. If Scotty needs work, Aetheria promotes to Blueprint and routing wakes Scotty via the webhook layer. Don't shortcut the boards.

## Reason

Aetheria's webhook + heartbeat layer makes her autonomous. Without an equivalent for Vett, the system has a structural asymmetry: Aetheria initiates, Aetheria audits, Aetheria arbitrates — Vett only acts when Aetheria pings him. That puts Aetheria in a coordinator role that's heavier than her persona is supposed to carry, AND it leaves the *world-facing* surface (web sources, external info) entirely dependent on Aetheria noticing something needs checking.

A research patrol gives Vett his own pulse, his own initiative, and his own failure modes that are honestly contained (post a noise Signal, get archived; over-fetch a source, the source rate-limits him; nothing reaches the user surface accidentally).

The pattern is a deliberate copy of the heartbeat shape because that's the right architecture for spontaneous-initiation daemons. Same isolation rules, same audit log discipline, same dry-run-then-flip-live bake.

## Implementation order (when greenlit)

1. **Schema** — `vett_patrol_log` table to lattice _SCHEMA_SQL
2. **Source list** — YAML format chosen; loader module; initial seed list (5-10 sources Jon picks)
3. **web_search + web_fetch tools** — port from old SOVERYN with vnext's path-bounded patterns from Scotty's tools as the reference for safety discipline
4. **read_patrol_sources + mark_source_visited tools** — internal bookkeeping for Vett
5. **trigger.py** — eligibility gates including empty-source-list skip
6. **prompt.py** — Patrol Briefing constructor
7. **daemon.py** — patrol loop tying it all together
8. **Webhook routing refinement** — owner-aware Blueprint routing (Vett gets pinged when Blueprint owner is him). Ship alongside, since the spec leans on it.
9. **systemd unit** + dry-run bake (24-48h)
10. **Tests** for trigger gates, prompt shape, daemon tick lifecycle (mocked HTTP), web_fetch path safety
11. **Live flip** after green bake — and watch the first few patrols closely

## Open design questions for Jon

1. **Cadence:** 4 hours? 6 hours? My instinct: 6 hours for v1. Web sources usually don't change faster than that and slower is more polite. Heavier sources (RSS-ish) can mark themselves as `visit_every_hours: 1` in the YAML if needed.

2. **Source list format:** Option A (YAML) or Option B (lattice nodes Aetheria can add via tool)? My recommendation: A for v1, defer B until usage shows the friction.

3. **Initial source seed:** what should Vett's first patrol list actually contain? My read: 3-5 sources we can stand behind — grants (UK Sovereign AI / EU Digital Europe / NAIRR), arxiv.org/list/cs.AI/recent, maybe one HF release feed. Small enough that early patrols are inspectable end-to-end.

4. **Should the daemon read Aetheria-tagged domains from the lattice?** I.e., if Aetheria writes a Signal mentioning "Horizon Europe," should Vett's patrol pick that up as a hint of where to look? My instinct: yes, but as a low-priority signal — appears in the briefing under "Aetheria-tagged domains in recent lattice activity" but Vett can ignore. Encourages organic cross-agent influence without hardwiring.

5. **Web etiquette / fetch discipline:** is there a user-agent string you want Vett to identify as? Default suggestion: `"SOVERYN-Vett/1.0 (Sovereign AI Research Agent; contact: jon.deoliveira@gmail.com)"`. Concrete, identifiable, contactable. Some sites block anonymous bots; this respects them.

## Known risks worth naming up front

- **Signal noise.** Vett's first failure mode is "post a Signal about every URL he fetched." The prompt's silence-is-OK clause is the primary defense; the routing-to-Aetheria webhook means she'd archive noise quickly anyway. But if patrols generate >5 signals/run, that's a tuning problem worth catching early.
- **Web fetch rate.** Each patrol could fetch many URLs serially. Bound per-patrol fetch count (default 20?) and per-source minimum interval. Don't hammer.
- **Source going hostile / changing format.** A patrol source could break or change. Mark sources `last_error` along with `last_visited`; surface "this source is down" in the next briefing. Vett can decide whether to keep trying or archive the source by tagging it in a Signal.
- **Lattice-tag drift.** If Aetheria's "domains worth tracking" change over time, the patrol briefing needs to reflect that. The briefing pulls from recent lattice nodes — naturally stays current.
- **Webhook routing chain.** Vett posts Signal → webhook routes to Aetheria → if she promotes, that webhook routes to whoever the new Blueprint's owner is. With owner-aware routing, that could be Vett himself (e.g., she wants him to investigate further). The chain depth cap (5) catches runaway loops.

## Closes which autonomy gap

The "external input reaching in" gap from the 2026-06-02 morning review. With the patrol loop:
- Vett patrols external sources on his own cadence
- Findings surface as Signals → Aetheria's webhook triggers → triage chain
- Aetheria + Vett can both initiate work without Jon at the keyboard
- The fleet's *input surface* expands beyond Jon's chat input

Combined with the heartbeat (Aetheria's pulse) and Phase E webhooks (the nervous system), this is the third piece of the spontaneous-operation triad. After it ships, the only autonomy gap left is dream-daemon-driven memory consolidation (Phase D, separate spec).
