# SOVERYN quote skeleton — INTERNAL

**Not public. Not for Seneca. Not a price sheet.**  
Seneca may describe the *process* (demo → written quote; hardware you own; two install shapes). Dollar figures live only here. If you change a number, change this file — do not put `$` in `soveryn-agent/knowledge.py`.

**Last edited:** 2026-08-28 · **Owner:** Jon

---

## What we sell

Not ChatGPT seats. Not tokens. A **house that runs on iron they own**: local models, memory, Gate, no egress. PondWright is the honest reference (our own shop), not a third-party case study.

Hardware is **theirs**. We do not rent them a model.

---

## Three paths (pick one on the call)

| Path | What they get | When | How you bill |
|------|----------------|------|----------------|
| **1. Walkthrough** | 30–45 min live demo of the running house. No SKU. | Everyone. Qualifies 2 vs 3. | **$0** |
| **2. Software on their iron** | Install + wire the house on GPUs they already have. | They have boxes. | Project fee (not VRAM) |
| **3. Turnkey station** | Spec a box **they buy and own**, then path 2 on it. Hardware pass-through (or small kit margin). Fee is standing it up. | They will buy what you tell them. | Hardware at cost/kit + project fee |

Same shape as CWG: simple paths are a conversation; the real house is walk-and-quote.

---

## Floors — edit before you send anything

These are **gut rails so you don’t underquote**, not a catalog. Strike and replace when you have a real BOM.

| Line | Starting rail | Notes |
|------|----------------|-------|
| Selling rate (if you hourly a mushy scope) | **$200 / hr** | House ledger $75/hr is *your* opportunity cost — do not sell at that. |
| Path 2 — clean single-box stand-up | **$4,000–$12,000** | Days of install, Gate, backup, one product-shaped mind (PondWright-class). |
| Path 2 — multi-agent house | **quote after demo** | Face + build + overnight + backups. Do not guess from this table. |
| Path 3 hardware — Spark-class (smallest honest station) | **low thousands, pass-through** | Enough for a product agent, not a full Aetheria house. Confirm live MSRP. |
| Path 3 hardware — two Sparks / Spark + 48 GB workstation | **mid four figures to low five, pass-through** | Serious house. Confirm live MSRP. |
| Path 3 hardware — tower class (your lab) | **five figures of silicon** | Research/ops deploy. Not the first SKU. |
| Ongoing care (optional) | **monthly retainer, not tokens** | Model updates, backup watch, Gate. Set after they are live. |
| Power | **tens of $/mo on Spark-class** | Not the quote. |

Your own stack (2× Quadro, Blackwell, Sparks, EPYC) is the **lab**, not the SKU.

---

## Questions that size the quote (one at a time)

1. Do you already have GPUs, or do you need a station spec?
2. What must never leave the building (PHI, privilege, CUI, nothing-yet)?
3. One product agent (quotes/intake) or a house (several minds + memory)?
4. Who owns the box day-to-day — you, IT, or us on a call?

Until those are answered, there is no honest number.

---

## What Seneca is allowed to say

See `~/soveryn-agent/knowledge.py` §How someone actually buys this. Process only. **Zero dollars.**

---

## Email if they left contact (or you are following up)

Subject: Soveryn — hardware is yours; cost is a written quote after a short demo

> Hardware is yours — we don’t rent you a model. Cost is a quote after I know whether you already have GPUs or need a station spec. Fastest path: 30 minutes, I show you the live system, then I send one of two numbers: install on what you have, or a box + install.
>
> Reply with a time, or write info@soverynintelligence.com.

Do not attach this file. Do not paste the floors table.

---

## 08-23 prospect (IP 89.187.177.74)

Two turns, empty `session_id`, **no name/email/phone**.  
1) “Can this run on our own hardware?” 2) “What would this cost us?”  
IP is **DataCamp / CDN77 NYC** (proxy/VPN, not a firm street address).  
**Not recoverable by email.** Lead stays in `docs/leads/seneca-leads.csv` as open/uncontactable. Next similar chat: Seneca explains process + asks for contact; warm (hardware then cost, non-local IP) emails Jon even without contact.
