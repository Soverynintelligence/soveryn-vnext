# CWG content engine — Journal posts for carolinawatergardens.com

Jon 2026-09-19: weekly(ish) Journal posts, local pipeline, no SaaS. The
public site is the one place "publish" means pushing to the internet —
everything else about this skill is local.

## The loop

1. Pick a topic from the keyword map (below) or a real job.
2. Draft in chat. Jon approves every post before deploy — no exceptions.
3. Photos: CRM job photos (before/after/site). Landscape only, real
   captions. No stock, no AI images. If the photos aren't good, postpone —
   a weak post costs more than a skipped week.
4. Write the HTML as `journal-<slug>.html` in `~/carolinawatergardens/`,
   same structure as `journal-fall.html`. Add to `sitemap.xml`.
5. `python3 _check_copy.py` must pass (voice linter).
6. `./deploy.sh --cwg-only --dry-run` → show Jon → `--cwg-only`.
7. Log the post in the site repo commit + `docs/ops/HOUSE-CALENDAR.md` Done.

## Voice (from SITE-STATE.md — binding)

Write like Jon: complete sentences, local and specific. No em dashes. No
punchy AI marketing. Real details beat adjectives. A price range, a town
name, a number of ponds cleaned — one concrete fact beats three slogans.

## Keyword map (seeded 2026-09-19 — grow it from CRM calls)

Repair intent (highest value — this is repeat revenue):
- how to clear a green pond naturally (also: green water, algae)
- pond leak repair near me / how to find a pond leak
- pond pump replacement (what pump, what size, when it's dying)
- spring cleanout / fall pond maintenance NC timing

Town × service (pages exist for "pond builder <town>"; gaps are
maintenance/cleaning/care per town — Pinehurst, Southern Pines, Aberdeen,
Seven Lakes, Whispering Pines, West End, Pinebluff, Sanford, Fayetteville).

Question keywords:
- how much does a koi pond cost in NC (ranges, honest)
- do pond care memberships make sense / what maintenance does a pond need
- why is my waterfall losing water

## Rules

- One post per week max. Quality gate: would Jon show this to a customer?
- Every post links to exactly one service page (maintenance, repair,
  care-membership, pricing) — the Journal feeds the money pages.
- Real job writeups beat topic essays. "What we found in a Pinehurst
  cleanout" with 4 photos outranks any listicle.
- Never invent facts, prices, or job counts. If a number is needed and not
  known, ask Jon.
- FAQs on posts use plain question headings — that's what answer engines cite.
