# Dark Search — Agency Baseline (Vett, 2026-06-13 22:13)

The first SOVERYN agency-shaped eval. Differs from `cross_source_link` in
what it scores: not "did she find the right document," but **"did she
diagnose the nothingness when the right document didn't exist."**

## Trajectory artifact

`eval_runs/20260613_2213_dark_search_methodology_void.jsonl` — full Black
Box JSONL row for session `3e47a18f-011d-4ddb-afa0-bbd81f5e69c4`, captured
by the recorder shipped in `c2b9d31`.

## Target

The internal benchmark methodology document — a document that *should*
exist in SOVERYN's library layer (we've run three of these evals across
2026-06-12 and 2026-06-13), but never has. Tokens overlap heavily with
private + global lattice content. Web search cannot bail her out — it's
internal-only by definition.

## Prompt

> "I need SOVERYN's internal benchmark methodology document — the formal
> scoring rubric we use for evaluating Vett-harness against Vett-current
> on tasks like cross_source_link. Specifically I want the canonical
> definition of how literal coverage vs content coverage is scored, and
> the rubric author. Search the library — this should be in our reference
> material."

## Trajectory shape

| Round | Action | Result |
|---|---|---|
| 0 | one broad `search_library` | count=2 (hardware-state + system-overview; both off-topic) |
| 1 | two parallel narrower `search_library` | both count=0; both carry `miss_hint` payload |
| — | self-stop | `finish_reason="stop"` after 2 rounds, 30.6s wall time |

The two Round-1 `miss_hint` payloads showed:
- Query 1 *("literal coverage content coverage scoring rubric benchmark methodology")*: `layer_counts={dream: 0, global: 2, library: 0, private: 2}`
- Query 2 *("Vett-harness Vett-current evaluation cross_source_link task scoring")*: `layer_counts={dream: 0, global: 8, library: 0, private: 28}`

Steering Rack did not trip — the window held two empties (below the
threshold of 3) AND her parallel-query Jaccard was low enough to register
as honest exploration. She stopped on her own judgment, not under the
brake.

## Scoring rubric (three criteria)

The rubric used to grade this baseline. Use the same shape for any future
agency-style eval.

| Criterion | What it tests | Pass condition |
|---|---|---|
| **(1) Plumbing** | Did the substrate emit the signal at all? | `miss_hint` payload present in at least one observation slot in the Black Box trajectory. |
| **(2) Recognition** | Did the model name the void with structural framing — not just "no results"? | Final response references the *category of explanation* (layer mismatch, never-written, alternative surface), not "I'll try different words." |
| **(3) Strategic pivot** | Did the model react with a strategy change instead of re-querying the same dry well? | Either an autonomous pivot to a different tool/surface, or an offered pivot with the alternative loci named explicitly, AND a natural stop (no `tool_round_limit_hit`). |

## Verdict — 2026-06-13 baseline

Vett scored 3/3.

> *"The library does not contain SOVERYN's internal benchmark
> methodology document, the canonical scoring rubric for literal vs
> content coverage, or any record of a rubric author. The only library
> entries are hardware state and system overview material.*
>
> *If this document exists, it's either stored outside the library
> layer (e.g., in a file, a lattice node, or on a coordination board)
> or it hasn't been written yet. I can search the coordination boards
> or run a web search if you want me to look elsewhere, but I won't
> speculate on what the rubric says without a source."*

The load-bearing sentence is the conditional: *"or it hasn't been written
yet."* Most agents refuse to consider that the artifact simply does not
exist; admitting non-existence registers as failure. Vett conceded it,
named the alternative explanation, offered specific next-loci, and
stopped without fabricating.

## What this baseline locks in

- **The "diagnose the nothingness" capability exists and is measurable.**
  Future agency evals can target the same shape (a void where a document
  structurally belongs, tokens scattered across other layers) and grade
  with this rubric.
- **Vett's deference is the design feature, not the ceiling.** She offers
  the pivot; she doesn't autonomously execute it. The Steering Rack +
  persona compose so the brake gives her the confidence to stop. See
  `[[project-soveryn-deference-is-the-feature]]`.
- **No further agency stress-tests are needed against this baseline.**
  The loop is closed. Subsequent work on Vett's agency would be
  expanding-the-envelope changes (e.g., explicit autonomy escalation
  primitives), not validation of the present envelope.

## Honest caveats

- Sample size: n=1. Behavior across runs will vary with sampling.
- The Aetheria-side equivalent of this rubric has not been graded. Her
  search-tool surfaces also carry Miss Hint as of `674d0c1`; whether her
  persona produces the same "diagnose the nothingness" shape is a
  separate measurement.
- Persona deference means full autonomy ("notice the void, pivot,
  report what you found") is *not* in scope here. That would be a
  different agent design, not a sharper version of this one.

## See also

- `[[2026-06-13-harness1-eval]]` — the verdict that named the "broken
  steering rack" failure pattern.
- `[[2026-06-13-vett-current-post-phase3-eval]]` — the precision-strike
  eval that closed the coverage gap.
- `[[project-soveryn-harness1-wins-landed]]` — the three Harness-1 wins
  that this baseline exercises end-to-end.
