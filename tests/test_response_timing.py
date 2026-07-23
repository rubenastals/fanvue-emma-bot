"""Response timing + daily_state — human pickup latency."""
from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from core import daily_state
from core.response_timing import TimingPlan, plan_reply_timing, timing_context_line


def test_daily_state_stable_intraday():
    d1 = daily_state.get_day("emma")
    d2 = daily_state.get_day("emma")
    assert d1 == d2
    assert d1["date"]


def test_daily_state_differs_by_account():
    a = daily_state.get_day("emma")
    b = daily_state.get_day("sophia")
    assert a["morning"] or b["morning"]


def test_asleep_holds_until_wake():
    la = ZoneInfo("America/Los_Angeles")
    at_3am = datetime(2026, 7, 23, 3, 30, tzinfo=la)
    plan = plan_reply_timing(last_emma_reply_at=None, now=at_3am)
    assert plan.hold_until is not None
    assert plan.mode == "wake"
    assert plan.hold_until > at_3am


def test_session_mode_when_recent_reply():
    la = ZoneInfo("America/Los_Angeles")
    noon = datetime(2026, 7, 23, 14, 0, tzinfo=la)
    last = noon - timedelta(minutes=2)
    plan = plan_reply_timing(last_emma_reply_at=last, now=noon, heat="stable")
    assert plan.mode == "session"
    assert plan.delay_seconds < 60
    assert plan.hold_until is None


def test_timing_context_after_long_gap():
    plan = TimingPlan(mode="normal")
    line = timing_context_line(plan, gap_minutes=52.0)
    assert "52" in line
    assert "TIMING FACT" in line


def test_wake_context_line():
    plan = TimingPlan(mode="wake")
    assert "woke up" in timing_context_line(plan, None).lower()


def test_heating_never_slow_pickup_gate():
    """Hot threads must not get 20m+ response_gate (Dan/Sophia regression)."""
    la = ZoneInfo("America/Los_Angeles")
    afternoon = datetime(2026, 7, 23, 14, 5, tzinfo=la)
    last = afternoon - timedelta(hours=2)
    plan = plan_reply_timing(
        last_emma_reply_at=last,
        now=afternoon,
        heat="heating",
    )
    assert plan.hold_until is None
    assert plan.mode == "session"
    assert plan.delay_seconds <= 60
