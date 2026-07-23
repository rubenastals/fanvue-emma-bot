"""Tiered re-engagement policy — timing, single bubble, farewell cooldown."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from core import reengagement


def _mem(**extra):
    base = {"messages": 10, "nudge_episode_count": 0}
    base.update(extra)
    return base


def test_cold_needs_15_minutes():
    now = datetime.now(timezone.utc)
    plan = reengagement.plan_reengage(
        timedelta(minutes=14),
        _mem(),
        heat_score=10,
        is_read=False,
        now=now,
    )
    assert plan is None

    plan2 = reengagement.plan_reengage(
        timedelta(minutes=16),
        _mem(),
        heat_score=10,
        is_read=False,
        now=now,
    )
    assert plan2 is not None
    assert plan2.tier == "cold"
    assert plan2.style in reengagement._TIER_STYLES["cold"]


def test_hot_visto_faster_than_cold():
    now = datetime.now(timezone.utc)
    mem = _mem(
        last_seen_by_fan_at=(now - timedelta(minutes=5)).isoformat(),
    )
    plan = reengagement.plan_reengage(
        timedelta(minutes=5),
        mem,
        heat_score=55,
        is_read=True,
        now=now,
    )
    assert plan is not None
    assert plan.tier == "hot"
    assert plan.style in ("hot_pullback", "flirty_tease", "unfinished_thread")


def test_farewell_blocked_under_4h():
    now = datetime.now(timezone.utc)
    plan = reengagement.plan_reengage(
        timedelta(hours=2),
        _mem(),
        heat_score=50,
        is_read=True,
        now=now,
        farewell=True,
    )
    assert plan is None


def test_farewell_allowed_after_4h():
    now = datetime.now(timezone.utc)
    plan = reengagement.plan_reengage(
        timedelta(hours=5),
        _mem(),
        heat_score=20,
        is_read=False,
        now=now,
        farewell=True,
    )
    assert plan is not None
    assert plan.tier == "farewell"


def test_only_one_nudge_per_episode():
    now = datetime.now(timezone.utc)
    mem = _mem(nudge_episode_count=1)
    plan = reengagement.plan_reengage(
        timedelta(minutes=60),
        mem,
        heat_score=60,
        is_read=True,
        now=now,
    )
    assert plan is None


def test_warm_around_10_minutes():
    now = datetime.now(timezone.utc)
    plan = reengagement.plan_reengage(
        timedelta(minutes=11),
        _mem(),
        heat_score=30,
        is_read=False,
        now=now,
    )
    assert plan is not None
    assert plan.tier == "warm"
