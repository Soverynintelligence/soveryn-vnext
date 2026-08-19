# Coding bake: Qwen 3.8 (Aetheria) vs DeepSeek Flash (Kernel)

**Date:** 2026-08-19  
**Task:** Same Automations scaffold prompt (registry + runner + 3 stubs + pytest).  
**Outputs:** `tmp/coding-bake-2026-08-19/`

| | **Qwen 3.8** (`aetheria` @ `:8090`) | **DeepSeek Flash** (`bench-flash` @ `:8091`) |
|--|--|--|
| Wall clock | **32.9 s** | **94.4 s** (~2.9× slower) |
| Completion tokens | 1328 | 998 |
| Approx tok/s | **~40** | **~11** |
| Files emitted | 6 (incl. package `__init__`) | 5 |
| Syntax | parse OK | parse OK |
| Dry-run CLI | works | works |
| Pytest (isolated `/tmp`) | **1 passed** | **2 passed** |

## Takeaway
On this Automations scaffold, **Aetheria’s Qwen 3.8 is clearly faster and still produces a runnable dry-run scaffold**. Flash is not “dumb” here — both cleared the bar — but Flash is **slow-mo** on wall clock for multi-file codegen.

Implication for tomorrow’s Kernel Automations job: either
- keep Kernel/Flash for surgical mend, or
- let **Qwen/OpenCode** draft the Automations spike and use Kernel to review/mend,
- or dual-lane: Qwen drafts, Flash (Kernel) verifies.

Not a merge decision — bake only.
