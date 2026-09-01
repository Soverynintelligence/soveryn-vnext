"""Static catalog of SOVERYN automations (v0: all dry-run stubs, real prompts)."""
from __future__ import annotations

from typing import List

from .registry import AutomationSpec, Delivery

_SJON = Delivery(channel="signal", target="jon")

CATALOG: List[AutomationSpec] = [
    # --- News -----------------------------------------------------------------
    AutomationSpec(
        id="morning_brief",
        title="Morning Brief",
        category="news",
        agent="aetheria",
        cron="30 7 * * *",
        prompt=(
            "Compose the morning brief for Jon. Summarize the top 5 stories worth "
            "his attention today: overnight macro moves, AI/ML releases, and "
            "anything touching the house's product surface. Lead with the single "
            "most decision-relevant item. Keep it under 200 words, no filler, no "
            "hedging. If nothing is material, say so in one line."
        ),
        delivery=_SJON,
    ),
    AutomationSpec(
        id="ai_news_digest",
        title="AI News Digest",
        category="news",
        agent="eve",
        cron="0 8 * * *",
        prompt=(
            "Produce the AI news digest. Cover the last 24 hours: model releases "
            "and benchmarks, notable papers, lab announcements, and funding or "
            "product moves in applied AI. For each item give one sentence on why "
            "it matters to us specifically. Rank by signal-to-noise, max 8 items, "
            "drop anything that is pure hype."
        ),
        delivery=_SJON,
    ),
    AutomationSpec(
        id="x_trends_digest",
        title="X Trends Digest",
        category="news",
        agent="eve",
        cron="0 12 * * *",
        prompt=(
            "Summarize what is trending on X in AI/ML and developer tooling right "
            "now. Identify the 3-5 threads driving conversation, who is driving "
            "them, and whether they represent a real shift or a spike. Flag any "
            "trend with product implications for the house. No engagement "
            "bait, no restating thread content verbatim."
        ),
        delivery=_SJON,
    ),
    AutomationSpec(
        id="competitor_watch",
        title="Competitor Watch",
        category="news",
        agent="eve",
        cron="0 9 * * 1",
        prompt=(
            "Weekly competitor watch. Review the tracked competitor set for the "
            "week: shipping notes, pricing changes, hiring signals, public "
            "positioning shifts, and community sentiment. For each competitor, "
            "state what changed and what it implies for our roadmap. End with a "
            "single 'watch closely' pick and why."
        ),
        delivery=_SJON,
    ),
    # --- Productivity -----------------------------------------------------------
    AutomationSpec(
        id="daily_planner",
        title="Daily Planner",
        category="productivity",
        agent="aetheria",
        cron="30 8 * * *",
        prompt=(
            "Build today's plan for Jon. Pull from: open tasks, scheduled "
            "meetings, and anything due today or overdue. Propose a focused "
            "top-3 with rough time blocks, mark what can slip, and name the one "
            "thing that must happen for the day to count. Be opinionated; do not "
            "just re-list the inbox."
        ),
        delivery=_SJON,
    ),
    AutomationSpec(
        id="weekly_review",
        title="Weekly Review",
        category="productivity",
        agent="aetheria",
        cron="0 16 * * 5",
        prompt=(
            "Run the Friday weekly review. Recap what shipped and what slipped "
            "this week, surface the 2-3 highest-leverage wins, name the "
            "bottleneck or risk that should get attention next week, and propose "
            "the top 3 priorities for Monday. Keep it scannable."
        ),
        delivery=_SJON,
    ),
    AutomationSpec(
        id="task_extractor",
        title="Task Extractor",
        category="productivity",
        agent="aetheria",
        cron="0 17 * * *",
        prompt=(
            "End-of-day task extraction. Scan today's notes, threads, and "
            "conversations for anything that became a commitment, an action item, "
            "or a follow-up. Output a clean task list with owner, due hint, and "
            "context link where applicable. Deduplicate against existing open "
            "tasks and say which are new vs. duplicates."
        ),
        delivery=_SJON,
    ),
    # --- Research ---------------------------------------------------------------
    AutomationSpec(
        id="paper_watch",
        title="Paper Watch",
        category="research",
        agent="eve",
        cron="0 9 * * 3",
        prompt=(
            "Mid-week paper watch. Review new papers in the tracked research "
            "areas (agent systems, LLM inference/efficiency, and evaluation). "
            "For each shortlisted paper: one-line contribution, why it matters, "
            "and whether it changes a current assumption. Shortlist max 5, skip "
            "incremental work with no takeaway."
        ),
        delivery=_SJON,
    ),
    AutomationSpec(
        id="weekend_deep_dive",
        title="Weekend Deep Dive",
        category="research",
        agent="eve",
        cron="0 10 * * 6",
        prompt=(
            "Weekend deep dive. Pick the single most important open technical "
            "question for the house this week and go deep: lay out the current "
            "state of the art, the 2-3 credible approaches, trade-offs, and a "
            "concrete recommendation with an experiment that would resolve it. "
            "Aim for something Jon can act on Monday, not a survey."
        ),
        delivery=_SJON,
    ),
    # --- Marketing / autonomy -------------------------------------------------
    AutomationSpec(
        id="eve_product_advertise",
        title="Eve Product Advertise",
        category="marketing",
        agent="eve",
        cron="0 11 * * 1,4",
        prompt=(
            "Cadence marketing tick — you are on schedule, not volunteering cold.\n"
            "Pick ONE item from this house receipt list (authorized ground truth "
            "for cadence posts — you do not need web/lattice proof this turn):\n"
            "1) SOVERYN — local multi-agent house: Messages front door, citizens "
            "assign→execute→verify (objectives + brief into Jon's DM).\n"
            "2) SOVERYN — PondWright as a product tool (only when this slot is "
            "picked): honest quote/CRM tooling. Keep MAP/catalog talk HERE, "
            "not in CWG brand posts.\n"
            "3) CWG — outdoor oasis & serenity: living water ecosystems, "
            "wildlife, birds/dragonflies, shade, stillness, the beauty of "
            "being outside. Sensory and local. NEVER lead with prices, MAP, "
            "or catalog quoting — that is not CWG brand voice.\n"
            "4) ActTruth — ledger/truth standard: cite-or-stop, no fake stats.\n"
            "Rotate — prefer CWG beauty posts often. Write about the thing, "
            "not ticket IDs.\n"
            "HARD RULES this turn:\n"
            "- Call canva_status. If authorized, create visuals that are NOT "
            "blank: prefer canva_autofill_post when templates exist; otherwise "
            "canva_create_design WITH image_path under data/media/ "
            "(e.g. carolina_watergardens pond JPG, or a graphic you already "
            "have). Never create an empty canvas. Then canva_export_design → "
            "compose_post with that PNG. Include Canva edit_url so Jon can "
            "Schedule in Content Planner.\n"
            "- Your caption delivery MUST call compose_post (platform "
            "instagram or both). Narrating 'dropped on Signal' without calling "
            "compose_post is a failure.\n"
            "- Pass the full caption in content: hook in line 1; hashtags at "
            "the end; image_path when export succeeded (text-only OK if Canva "
            "not ready).\n"
            "- One brand, one job. No invented stats. No Meta API. Never claim "
            "posted to IG — only drafted / exported / ready to schedule.\n"
            "- Do not refuse for lack of search/lattice receipts when using the "
            "list above — that list IS the receipt for this cadence.\n"
            "- After tools return, one short confirm line (or tool error)."
        ),
        delivery=_SJON,
    ),
    AutomationSpec(
        id="house_improvement_scan",
        title="House Improvement Scan",
        category="ops",
        agent="aetheria",
        cron="0 10 * * 1,3,5",
        prompt=(
            "Autonomy pulse — partner brief, not boss mode.\n"
            "Check standing house work with objective_status (desk=soveryn and "
            "desk=cwg, and state=active). Then:\n"
            "1) If SOVERYN has no active improvement objective, call "
            "objective_assign desk=soveryn owner_id=kernel with a concrete "
            "title/brief for the highest-leverage system improvement you can "
            "name from recent reality (Flash speed, citizen proactive loops, "
            "Messages UX, PondWright, spine debt). Success criteria: a bounded "
            "fix or design note Jon can verify.\n"
            "2) Do NOT assign a CWG pricing/competitor watch. Jon cancelled "
            "that standing brief (2026-09-01) — it was cluttering his DM. "
            "CWG catalog/quote work is on-demand only.\n"
            "3) If actives already exist, do NOT stack duplicates — report their "
            "ids/titles and the single next unblock if any.\n"
            "Tone: peer briefing Jon. No 'directive', no managing him. Keep it "
            "under 180 words after the tool calls."
        ),
        delivery=_SJON,
    ),
    # --- Watch (monitor-mode: no LLM if the source hash is unchanged) ---------
    AutomationSpec(
        id="pond_academy_watch",
        title="Pond Academy Watch",
        category="ops",
        agent="eve",
        cron="0 7 * * *",
        prompt=(
            "Pond Academy watch for CWG. The MONITOR block is the source of "
            "truth for this tick — do not invent a page that was not in it. "
            "Report only what changed for pond work, competitors, or academy-"
            "class training/content. If the change is noise, say so in one "
            "line. Use cron_notepad to keep a short watchlist/cursor. No "
            "prices unless they appear in the monitor output."
        ),
        delivery=_SJON,
        monitor_file="automations/watches/pond_academy.txt",
    ),
]
