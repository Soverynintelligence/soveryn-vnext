# Matter Ops — Product Brief  
**Private paralegal agents for high-volume matters**  
*One page · Draft for Graham · 2026-08-14*

---

## One-liner
**Private matter ops:** sort the dump, build the docket, prepare the packet, run the checklist — **cite the file or stop**; a lawyer approves anything that leaves the building.

Not a legal-advice practice. Not a full firm OS. A **local work product factory** that eats days of paralegal / associate grind.

---

## Buyer & job-to-be-done

| | |
|--|--|
| **Primary buyer** | Small–mid firm partner or managing paralegal drowning in discovery / productions |
| **User** | Paralegal + attorney (human gate on outbound) |
| **Job** | “We got 15,000 pages and a calendar of hard dates — make it legible, scheduled, and ready to act without inventing facts.” |
| **Why local / private** | Client confidentiality; firm keeps corpus and work product on hardware they control |

---

## What it is / is not

| **Is** | **Is not** |
|--------|------------|
| Document intake, sort, summarize with **page cites** | Legal advice or strategy counsel |
| Deterministic **docket / deadline** engine | “AI guessed a statute of limitations” |
| Drafts from **firm templates** + matter facts only | Replacement for the lawyer’s judgment |
| Packets, checklists, filing **prep** | Unsupervised e-file as the product identity |
| Multi-agent house (Soveryn-shaped) | Chatbot bolted onto cloud drive |

---

## Agent cast (duties)

| Agent | Angle | Output |
|-------|--------|--------|
| **Clerk** | Structure | Inventory, classification, duplicates, hot-doc shortlist (cited) |
| **Chronicler** | Narrative | Timeline, parties, issue map (every claim → doc + page) |
| **Auditor** | Stress | Gaps, contradictions, missing exhibits (cited or “not in the record”) |
| **Docket** | Calendar | Deadlines from **rules + trigger events** (computed, not freelanced) |
| **Drafter** | Execute | First-pass drafts from firm templates + verified facts |
| **Runner** | File / serve prep | Checklist → assemble packet → **human approve** → export / optional connector |

Optional later: COS-style router for “where is this matter?”

---

## End-to-end flow

```
Open matter → Ingest corpus (to ~15k pages)
  → Clerk / Chronicler / Auditor (parallel)
  → Docket builds calendar (rules + orders + filed dates)
  → Work queue (draft / obtain / file / serve / wait)
  → Drafter prepares packet
  → Attorney/paralegal APPROVES
  → Runner exports or submits via gated connector
  → Receipt vaulted; calendar advances; audit log forever
```

**Shared law with Shepherd & History’s Ledger:** ground in real data; refuse to invent; print gaps.

---

## V1 scope (ship this first)

1. **Matter + document room** (immutable originals + page map)  
2. **Three-angle analysis** — Clerk, Chronicler, Auditor  
3. **Docket engine** — jurisdiction/practice *narrow* at first; dates computed from rules + triggers  
4. **Work queue + packet assembly + approve-to-export**  
5. **Audit log** — who ran what on which corpus  

**Explicit non-goals for v1:** full PMS (billing, trust, conflicts), multi-jurisdiction e-file, Westlaw replacement, unsupervised court filing, “answer any legal question.”

---

## V2 / V3 (after trust)

| Phase | Add |
|-------|-----|
| **V2** | Firm calendar sync; email of *approved* packets; **one** e-file path (one court / portal) |
| **V3** | More filing adapters; service workflows; optional time capture from agent work |

---

## Docket principle (Shepherd DNA)

- **Engine computes** deadlines from structured rules + events.  
- Model may **explain** which rule applied and show the source.  
- Model must **not** freestyle “you probably have 30 days.”  
- Missed-date risk is the product’s integrity test — same as Shepherd FCC fines.

---

## Document principle (Ledger DNA)

- Every summary claim → **document id + page (range)** or **“not in the record.”**  
- Privilege flags are **candidates** only; human decides.  
- Nothing client- or court-facing leaves without **approve**.

---

## Packaging & pricing (directional)

| Motion | Intent |
|--------|--------|
| **Per matter** | High-volume productions (e.g. mid hundreds–low thousands USD / matter when it saves days) |
| **Firm seat / month** | Ongoing docket + multi-matter desk for a small firm |
| **Private deploy** | Local / firm-controlled hardware — premium for confidentiality |

Exact numbers later; price against **days of paralegal/associate time** and **deadline risk**, not chat seats.

---

## Relationship to existing work

| Product | Role |
|---------|------|
| **Soveryn** | Runtime DNA: multi-agent house, desks, duties, local control |
| **Shepherd FCC** | Pattern: deterministic compliance / deadlines; Graham + radio path |
| **History’s Ledger / Atticus** | Pattern: cite-or-stop; print gaps |
| **Matter Ops (this)** | Vertical: firm matter intake → docket → packet → gated execution |

Do **not** sell “Soveryn for lawyers” as the brand. Sell **Matter Ops** (name TBD) with the same honesty rules.

---

## Partnership sketch (Jon / Graham)

| | Focus |
|--|--------|
| **Domain / wedge** | Graham: buyer path & vertical story (radio Shepherd now; legal ops if intros exist) |
| **Platform / integrity** | Jon: agents, local stack, cite-or-stop, docket engine discipline |
| **Must agree before build** | IP, customer ownership, support, liability framing (“not legal advice”) |

---

## Success criteria (first pilot)

- One real matter corpus (~thousands+ pages)  
- Attorney says inventory + timeline + docket are **usable without redoing from scratch**  
- Zero known **invented** cites in pilot review  
- At least one full **packet assemble → human approve → export** loop  
- Filing connector optional; **prep quality** is the bar for pilot success  

---

## Open name

Working title: **Matter Ops**. Alternatives later (Clerk’s Desk, File Room, Docket House, etc.).

---

## Ask / next step

Align on: **(1)** first practice + jurisdiction for docket rules, **(2)** pilot firm or synthetic corpus, **(3)** v1 only as above — then build the matter desk + three agents + docket spine.

---

*Status: internal product brief · not a legal services offering · not legal advice*
