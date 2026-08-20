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
        agent="vett",
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
        agent="vett",
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
        agent="vett",
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
        agent="vett",
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
        agent="vett",
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
]
