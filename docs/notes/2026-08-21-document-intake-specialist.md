# Document intake specialist — park for tomorrow (first thing)

**Date:** 2026-08-21 (night)  
**Status:** orientation only — **first agenda item next session**  
**Trigger:** Grok bots (and other agents) treated PDFs as opaque binaries; house agents already have partial vision/chat attachment paths. Next level = **document intake as a first-class citizen duty**, not a lucky tool.

## Problem

- PDF / Office / image / scan intake is uneven: some surfaces can see, many cannot.
- “I see the file exists but can’t read it” is a product failure for a house that claims primary sources and RAG.
- History’s Ledger Atticus energy (**cite-or-stop**, held corpus) should apply to **Jon’s documents**, not only public shelves.

## Intent (one sentence)

A house **Intake** specialist (or Scotty-adjacent duty) that turns any drop — PDF, docx, image, screenshot, audio later — into **held text + provenance + retrievable chunks**, with the same honesty spine: extract what we can, print gaps, never invent page content.

## Sketch (not locked)

| Piece | Notes |
|-------|--------|
| **Identity** | Citizen or standing duty: Intake / Archivist — not CoS, not every citizen gets a full OCR stack |
| **In** | File drop (desk inbox, CC upload, chat attachment, HL corpus path) |
| **Out** | Normalized text, page/image refs, embeddings or Lattice/library write, source card ids |
| **Law** | Cite-or-stop: if OCR/extract fails, say so; no hallucinated quotations |
| **Door** | Derived claims that leave the house still hit Approval Gate; intake itself is house-local |
| **RAG** | Specialist owns chunking + index; others **recall** via tools (`recall_skill` / library / lattice), don’t each run their own ingest |

## Already in the bones (reuse, don’t rewrite)

- Chat vision attachments (Aetheria / Vett / Scotty capable set)
- Document store / library tools / provenance patterns
- Atticus / HL: held source + apparatus (verified / gap)
- Citizens desks (`inbox/` / `work/` / `outbox/`)
- Approval Gate + Active-now (intake mid-job can show on strip later)

## Explicit non-goals (v0)

- Not a Composio marketplace
- Not every citizen gets a GUI computer for reading
- Not “upload anything to a cloud RAG SaaS” as default
- Not replacing Lattice with a generic vector DB slogan

## Tomorrow — first thing

1. Re-read this note + citizens charter (stewardship of documents).  
2. Choose: **new citizen** vs **Scotty duty** vs **thin shared intake service** citizens call.  
3. Name v0 formats: PDF text layer → scanned PDF/OCR → images → docx (in that order).  
4. One spike path: house agent `extract_pdf` / intake job that returns text + page map for a known file.  
5. Only then: design doc / plan if the shape holds.

## Quotable brief

> Next level of the house is **document intake** — all types, pics, reading — maybe an intake specialist for RAG and files. Agents that can’t read a PDF aren’t house-complete.

---

_Parked 2026-08-21 night. Do not start build until Jon opens this tomorrow._
