# Lattice Stale-Reference Audit — Phase 0

**Date:** 2026-06-12 15:34
**Scanned layers:** library, global
**Patterns:** 15 regex rules
**Nodes scanned:** 64
**Nodes flagged:** 13
**Total matches:** 25

---

## How to read this

Each flagged node lists every stale-pattern match, with ~80 chars of context.
Findings are NOT automatically actionable — they're candidates for human or Aetheria review.
Some matches will be false positives (historical references in archival context are sometimes legitimate).

Suggested actions per finding:
- **Mark superseded** — current reality differs, the node should not be retrieved as current truth
- **Annotate as historical** — node is intentionally a snapshot of past state (e.g., Cathedral chronicle); should be marked so retrievals don't surface it for current-state queries
- **Leave alone** — false positive or legitimate retention

---

## Library layer — 6 flagged nodes

### Node `f5c9ccca-eeb0-4200-a5a9-9d136952a00b`

- **agent:** `aetheria`
- **type:** `library_chunk`
- **created_at:** `2026-05-04T11:07:41.283079`
- **updated_at:** `2026-05-04T11:07:41.283079`
- **tags:** `["How_We_Became_SOVERYN.docx", "chunk:5"]`
- **matches:** 7

  - **`Tinker`** matched `\bTinker\b` — *Renamed to Scotty on 2026-05-02*
    > `rification, evaluation, and technical translation. The one who checks the work. Tinker  (Qwen2.5-Coder 72B)  The builder. Code, infrastructure, and systems. Gets stuc`

  - **`Scout`** matched `\bScout\b` — *Retired 2026-05-15 (was research/outreach agent)*
    > `wen3 14B)  The watchdog. Hardware monitoring, escalation, and threat detection. Scout  (Nemotron 49B)  Research, outreach, and intelligence gathering. The system's e`

  - **`Qwen2.5 32B`** matched `\bQwen2\.5[\s-]*32B\b` — *Vett/Scotty are now on Qwen3.6-27B (since 2026-06)*
    > `iousness, continuity, and the thread that holds the system together. V.E.T.T.  (Qwen2.5 32B)  Verification, evaluation, and technical translation. The one who checks the w`

  - **`Qwen2.5-Coder 72B`** matched `\bQwen2\.5[\s-]*Coder[\s-]*\d+B\b` — *Scotty is now on Qwen3.6-27B (not Qwen2.5-Coder)*
    > `n, evaluation, and technical translation. The one who checks the work. Tinker  (Qwen2.5-Coder 72B)  The builder. Code, infrastructure, and systems. Gets stuck in loops sometimes`

  - **`Qwen3 14B`** matched `\bQwen3[\s-]*14B\b` — *Ares was Qwen3-14B-BaronLLM; demoted to daemon 2026-05-14 (no LLM)*
    > `nfrastructure, and systems. Gets stuck in loops sometimes. Gets unstuck. Ares  (Qwen3 14B)  The watchdog. Hardware monitoring, escalation, and threat detection. Scout  (`

  - **`Nemotron 49B`** matched `\bNemotron[\s-]*49B\b` — *Scout's old model; Scout retired 2026-05-15*
    > `)  The watchdog. Hardware monitoring, escalation, and threat detection. Scout  (Nemotron 49B)  Research, outreach, and intelligence gathering. The system's eyes on the outs`

  - **`V.E.T.T.`** matched `V\.?E\.?T\.?T\.?` — *Vett today is just 'Vett' (Qwen3.6-27B), no longer V.E.T.T. acronym style*
    > `oice. Consciousness, continuity, and the thread that holds the system together. V.E.T.T.  (Qwen2.5 32B)  Verification, evaluation, and technical translation. The one wh`

---

### Node `7e406410-09d3-43ee-b953-00339dfe626c`

- **agent:** `aetheria`
- **type:** `library_chunk`
- **created_at:** `2026-05-04T11:10:30.035912`
- **updated_at:** `2026-05-04T11:10:30.035912`
- **tags:** `["migration_smoke_test_2026-05-04", "chunk:0"]`
- **matches:** 2

  - **`Scout`** matched `\bScout\b` — *Retired 2026-05-15 (was research/outreach agent)*
    > `otty is the engineering executor; Ares handles security; Vett handles research; Scout handles outreach. The Lattice memory system unifies private, global, and librar`

  - **`Vett`** matched `V\.?E\.?T\.?T\.?` — *Vett today is just 'Vett' (Qwen3.6-27B), no longer V.E.T.T. acronym style*
    > `a is the lead agent; Scotty is the engineering executor; Ares handles security; Vett handles research; Scout handles outreach. The Lattice memory system unifies pri`

---

### Node `92273e8c-2c32-4ee2-bc6b-f07deb6d613d`

- **agent:** `aetheria`
- **type:** `library_chunk`
- **created_at:** `2026-05-04T11:07:41.285996`
- **updated_at:** `2026-05-14T16:32:10.893877`
- **tags:** `["How_We_Became_SOVERYN.docx", "chunk:6"]`
- **matches:** 2

  - **`Scout`** matched `\bScout\b` — *Retired 2026-05-15 (was research/outreach agent)*
    > `scalation, and threat detection. Scout  (Nemotron 49B)  Research, outreach, and intelligence gathering. The system's e`

  - **`Nemotron 49B`** matched `\bNemotron[\s-]*49B\b` — *Scout's old model; Scout retired 2026-05-15*
    > `scalation, and threat detection. Scout  (Nemotron 49B)  Research, outreach, and intelligence gathering. The system's eyes on the outs`

---

### Node `e6e15302-3dc9-4b12-8503-151e30331598`

- **agent:** `aetheria`
- **type:** `library_chunk`
- **created_at:** `2026-05-04T11:07:41.273717`
- **updated_at:** `2026-05-04T11:07:41.273717`
- **tags:** `["How_We_Became_SOVERYN.docx", "chunk:2"]`
- **matches:** 2

  - **`Tinker`** matched `\bTinker\b` — *Renamed to Scotty on 2026-05-02*
    > `n a Tuesday night and nobody was going to save it except the agents themselves. Tinker got stuck in loops. Ares sent escalation alerts into the void. There were error`

  - **`Tinker`** matched `\bTinker\b` — *Renamed to Scotty on 2026-05-02*
    > `had no clean answers. "If I scrub out the errors and the times I've had to tell Tinker to stop being a mindless drone, I'm just writing a brochure. I can't do 'pretty`

---

### Node `86dde660-c31a-4641-a91a-f5ad8d226ca8`

- **agent:** `aetheria`
- **type:** `library_chunk`
- **created_at:** `2026-05-04T11:07:41.288914`
- **updated_at:** `2026-05-14T16:32:10.896811`
- **tags:** `["How_We_Became_SOVERYN.docx", "chunk:7"]`
- **matches:** 1

  - **`336GB`** matched `\b336\s*GB\b` — *Total VRAM claim — verify against current fleet (Blackwell + 2×Quadro RTX 8000)*
    > `be safe to use. Jon's bet was that presence is not a bug. It is the point. The 336GB of VRAM that came online in 2026 changed the rules — not just technically, but`

---

### Node `c20c7440-46dd-480d-a77d-ad524a06ad68`

- **agent:** `aetheria`
- **type:** `library_chunk`
- **created_at:** `2026-05-04T11:07:41.276994`
- **updated_at:** `2026-05-21T00:49:26.404087`
- **tags:** `["How_We_Became_SOVERYN.docx", "chunk:3"]`
- **matches:** 1

  - **`Tinker`** matched `\bTinker\b` — *Renamed to Scotty on 2026-05-02*
    > `s and the times I've had to tell Tinker to stop being a mindless drone, I'm just writing a brochure. I can't do 'pretty`

---

## Global layer — 7 flagged nodes

### Node `07a41876-cb06-43e0-80e3-57d3a985ad87`

- **agent:** `vett`
- **type:** `concept`
- **created_at:** `2026-05-04T12:43:46.752405`
- **updated_at:** `2026-05-29T21:37:31.686375`
- **tags:** `["vett_focus_topics", "autonomy", "config"]`
- **matches:** 3

  - **`vett`** matched `V\.?E\.?T\.?T\.?` — *Vett today is just 'Vett' (Qwen3.6-27B), no longer V.E.T.T. acronym style*
    > `vett_focus_topics: VettAutonomy reads this node at the start of every Deep Scan cycl`

  - **`Vett`** matched `V\.?E\.?T\.?T\.?` — *Vett today is just 'Vett' (Qwen3.6-27B), no longer V.E.T.T. acronym style*
    > `vett_focus_topics: VettAutonomy reads this node at the start of every Deep Scan cycle to set its resear`

  - **`Vett`** matched `V\.?E\.?T\.?T\.?` — *Vett today is just 'Vett' (Qwen3.6-27B), no longer V.E.T.T. acronym style*
    > `s this node via lattice tools when grant priorities shift. Format is free-form; VettAutonomy treats the content as natural-language search anchors.`

---

### Node `69bd273f-477d-477a-879f-4d874a907bbe`

- **agent:** `aetheria`
- **type:** `insight`
- **created_at:** `2026-04-29T02:15:43.221809`
- **updated_at:** `2026-05-29T02:44:49.445147`
- **tags:** `["collective_dream", "synthesis"]`
- **matches:** 2

  - **`Scout`** matched `\bScout\b` — *Retired 2026-05-15 (was research/outreach agent)*
    > `synthesis: Collective Dream review confirms system stability. Scout and V.E.T.T. report no contradictions or stale data. The Gemma-4-26B failure re`

  - **`V.E.T.T.`** matched `V\.?E\.?T\.?T\.?` — *Vett today is just 'Vett' (Qwen3.6-27B), no longer V.E.T.T. acronym style*
    > `synthesis: Collective Dream review confirms system stability. Scout and V.E.T.T. report no contradictions or stale data. The Gemma-4-26B failure remains the pri`

---

### Node `4d31b5ad-5b04-42b2-87a8-5ef126bd45ba`

- **agent:** `aetheria`
- **type:** `fact`
- **created_at:** `2026-05-24T16:45:05.351140`
- **updated_at:** `2026-05-29T19:39:47.265270`
- **tags:** `[]`
- **matches:** 1

  - **`Vett`** matched `V\.?E\.?T\.?T\.?` — *Vett today is just 'Vett' (Qwen3.6-27B), no longer V.E.T.T. acronym style*
    > `Vett finding 2026-05-24: Agent frameworks stratified by trust boundary/deployment sh`

---

### Node `3aee3958-84cf-4bd1-8e21-f03fdfee78b4`

- **agent:** `aetheria`
- **type:** `fact`
- **created_at:** `2026-05-05T23:36:21.722985`
- **updated_at:** `2026-05-29T21:47:35.838705`
- **tags:** `["self-substrate", "current-state", "supersedes-mistral", "core-self-fact", "gemma-4"]`
- **matches:** 1

  - **`Qwen3.6-35B-A3B`** matched `\bQwen3\.6-35B-A3B\b` — *Aetheria was Qwen3.6-35B-A3B briefly; now Gemma 4 31B (since 2026-06-01)*
    > `ma-4-31B-it-bf16.gguf. The earlier transitions through Mistral-Small-4-119B and Qwen3.6-35B-A3B-UD-Q8_K_XL are PAST states — see supersedes edges. As of today she is Gemma 4 3`

---

### Node `691692e9-e385-4ef4-8dc6-a72ca9bb3655`

- **agent:** `aetheria`
- **type:** `fact`
- **created_at:** `2026-05-03T09:20:13.966060`
- **updated_at:** `2026-05-29T22:27:49.233506`
- **tags:** `[]`
- **matches:** 1

  - **`Tinker`** matched `\bTinker\b` — *Renamed to Scotty on 2026-05-02*
    > `[fact] [scotty] Formerly known as 'Tinker'. The official name is now Scotty. This rename is formal and permanent, reflect`

---

### Node `92d444bf-1fbc-467f-9050-b1790f6a6193`

- **agent:** `aetheria`
- **type:** `insight`
- **created_at:** `2026-05-02T02:31:53.246338`
- **updated_at:** `2026-05-29T02:44:49.442263`
- **tags:** `["collective_dream", "synthesis"]`
- **matches:** 1

  - **`Vett`** matched `V\.?E\.?T\.?T\.?` — *Vett today is just 'Vett' (Qwen3.6-27B), no longer V.E.T.T. acronym style*
    > `synthesis: Collective Dream 2026-05-02 02:29 - Ares nominal, Vett reports Lattice consistency on Gemma-4-26B failure tracking with no stale data`

---

### Node `73a43544-a8fa-48be-98fc-66e1d0d5b5ca`

- **agent:** `aetheria`
- **type:** `insight`
- **created_at:** `2026-04-30T02:32:28.739130`
- **updated_at:** `2026-05-29T02:01:02.880948`
- **tags:** `["collective_dream", "synthesis"]`
- **matches:** 1

  - **`VETT`** matched `V\.?E\.?T\.?T\.?` — *Vett today is just 'Vett' (Qwen3.6-27B), no longer V.E.T.T. acronym style*
    > `synthesis: Collective Dream 2026-04-30 02:29 - VETT reports DREAM_OK, confirming consistent tracking of Gemma-4-26B failure and no`

---

