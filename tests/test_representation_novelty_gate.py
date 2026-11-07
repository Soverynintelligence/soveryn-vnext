"""Tests for the LIVE representation novelty gate (Jon's rules, 2026-11-06)."""
from __future__ import annotations

from datetime import date, datetime, timedelta

from soveryn.agents.representation.novelty_gate import (
    TZ, ConclusionRec, evaluate, is_novel, is_traceable,
)

TODAY = date(2026, 11, 20)  # evaluated through 2026-11-19


def at(d: date, h: int = 12, m: int = 0) -> datetime:
    return datetime(d.year, d.month, d.day, h, m, tzinfo=TZ)


class Turns:
    """Fake conversation store: sid -> list of turn datetimes."""
    def __init__(self):
        self.s: dict[str, list[datetime]] = {}

    def add(self, ts: datetime) -> str:
        sid = f"s{len(self.s)}"
        self.s[sid] = [ts]
        return f"turn:{sid}:0"

    def __call__(self, sid, idx):
        rows = self.s.get(sid, [])
        return rows[idx] if 0 <= idx < len(rows) else None


WORDS = ["alpha", "bravo", "charlie", "delta", "echo", "foxtrot", "golf", "hotel",
         "india", "juliet", "kilo", "lima", "mike", "november", "oscar", "papa"]


def uniq(n: int) -> str:
    # distinct enough that difflib stays far below 0.92
    return " ".join(WORDS[(n * 7 + k * 3) % 16] + str(n * 31 + k) for k in range(6))


def good(turns: Turns, ts: datetime, n: int) -> ConclusionRec:
    return ConclusionRec(f"c{n}", uniq(n), ts, (turns.add(ts - timedelta(hours=1)),))


def week(turns, start_n=0, per_day=5, days=7):
    recs, n = [], start_n
    for i in range(1, days + 1):
        for _ in range(per_day):
            recs.append(good(turns, at(TODAY - timedelta(days=i)), n)); n += 1
    return recs


def test_pass_seven_green_days():
    t = Turns()
    r = evaluate(week(t), t, today=TODAY)
    assert r["streak"] == 7 and r["status"] == "pass"


def test_below_80_percent_day_fails():
    t = Turns()
    recs = week(t)
    d = TODAY - timedelta(days=3)
    # add 2 untraceable to that day's 5 good -> 5/7 = 71%
    recs += [ConclusionRec(f"x{i}", uniq(500 + i), at(d), ("turn:nope:0",)) for i in range(2)]
    r = evaluate(recs, t, today=TODAY)
    row = next(x for x in r["days"] if x["day"] == d.isoformat())
    assert row["total"] == 7 and not row["green"]
    assert r["streak"] == 2 and r["status"] == "fail"


def test_exactly_80_percent_is_green():
    t = Turns()
    recs = week(t, per_day=4)
    d = TODAY - timedelta(days=1)
    recs.append(ConclusionRec("bad", uniq(900), at(d), ()))  # 4/5 = 80%
    assert evaluate(recs, t, today=TODAY)["status"] == "pass"


def test_untraceable_premise():
    t = Turns()
    ts = at(TODAY - timedelta(days=1))
    # node-id premise only, missing session, index out of range, stale turn
    assert not is_traceable(ConclusionRec("a", "x", ts, ("9ad8bf30-uuid",)), t)
    assert not is_traceable(ConclusionRec("a", "x", ts, ("turn:missing:0",)), t)
    p = t.add(ts - timedelta(hours=2))
    assert not is_traceable(ConclusionRec("a", "x", ts, (p[:-1] + "5",)), t)
    old = t.add(ts - timedelta(days=8))
    assert not is_traceable(ConclusionRec("a", "x", ts, (old,)), t)
    future = t.add(ts + timedelta(minutes=5))
    assert not is_traceable(ConclusionRec("a", "x", ts, (future,)), t)
    assert is_traceable(ConclusionRec("a", "x", ts, ("junk", old, p)), t)


def test_near_duplicate_not_novel():
    ts = at(TODAY - timedelta(days=1))
    base = "Jon's communication style is characterized by brevity and high signal density"
    prior = ConclusionRec("p", base, ts - timedelta(days=2))
    near = ConclusionRec("n", base + "!", ts)
    near2 = ConclusionRec("n2", base.replace("high", "very high"), ts)
    exact = ConclusionRec("e", base.upper(), ts)
    assert not is_novel(near, [prior, near])
    assert not is_novel(near2, [prior, near2])
    assert not is_novel(exact, [prior, exact])
    assert is_novel(ConclusionRec("u", uniq(3), ts), [prior])


def test_30_day_window_is_per_conclusion():
    base = uniq(42)
    old = ConclusionRec("old", base, at(date(2026, 10, 20), 12, 0))
    inside = ConclusionRec("in", base, at(date(2026, 11, 19), 11, 59))   # 29d 23h59m later
    outside = ConclusionRec("out", base, at(date(2026, 11, 19), 12, 1))  # 30d 1m later
    recs = [old, inside, outside]
    assert not is_novel(inside, recs)
    # outside: old is beyond its own 30d window, but `inside` is a prior dup
    assert not is_novel(outside, recs)
    assert is_novel(outside, [old, outside])
    # a later conclusion never makes an earlier one non-novel
    assert is_novel(old, recs)


def test_timezone_day_boundary():
    t = Turns()
    recs = week(t)
    d1 = TODAY - timedelta(days=1)
    # 23:30 ET on d1 is 04:30 UTC on TODAY -> must land on d1, not today
    utc = at(d1, 23, 30).astimezone(__import__("datetime").timezone.utc)
    late = ConclusionRec("late", uniq(700), utc.astimezone(TZ), (t.add(utc - timedelta(hours=1)),))
    # 00:30 ET TODAY (an incomplete day) is excluded entirely
    early = ConclusionRec("early", uniq(701), at(TODAY, 0, 30), ())
    r = evaluate(recs + [late, early], t, today=TODAY)
    row = next(x for x in r["days"] if x["day"] == d1.isoformat())
    assert row["total"] == 6
    assert all(x["day"] != TODAY.isoformat() for x in r["days"])
    assert r["status"] == "pass"


def test_empty_day_resets_streak():
    t = Turns()
    recs = [c for c in week(t, days=8) if c.created_at.date() != TODAY - timedelta(days=4)]
    r = evaluate(recs, t, today=TODAY)
    row = next(x for x in r["days"] if x["day"] == (TODAY - timedelta(days=4)).isoformat())
    assert row["total"] == 0 and not row["green"]
    assert r["streak"] == 3 and r["status"] == "fail"  # reset, not paused at 7


def test_empty_yesterday_zero_streak():
    t = Turns()
    recs = [c for c in week(t, days=8) if c.created_at.date() != TODAY - timedelta(days=1)]
    r = evaluate(recs, t, today=TODAY)
    assert r["streak"] == 0 and r["status"] == "fail"
