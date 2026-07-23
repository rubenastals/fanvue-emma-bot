"""sell_gate — heat sells, chill is per-turn only."""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from core.sell_gate import chill_turn, evaluate_sell_gate, should_attach_ppv
from core.soft_decline import is_soft_decline


def _mem(**kw):
    base = {
        "messages": 20,
        "status": "warm",
        "total_spent": 0.0,
        "purchases": 0,
        "free_teases_sent": 1,
        "recent_techniques": [],
    }
    base.update(kw)
    return base


def test_bills_is_chill_turn_not_hard_block():
    mem = _mem()
    msg = "I can't open it yet, as I need to pay my bills first"
    assert not chill_turn(mem, msg)
    attach, _ = should_attach_ppv(mem, msg, unpaid=False)
    assert attach or not attach  # sell_gate decides; chill does not block


def test_horny_after_bills_attaches():
    mem = _mem()
    msg = "fuck baby I need to see your wet pussy spread for me"
    assert not chill_turn(mem, msg)
    attach, reason = should_attach_ppv(mem, msg, unpaid=False)
    assert attach, reason


def test_hot_unpaid_nudge():
    mem = _mem()
    msg = "I'd fuck you so hard right now"
    gate = evaluate_sell_gate(mem, msg, unpaid=True)
    assert gate.nudge_unpaid
    assert not gate.attach


def test_sell_streak_does_not_chill_when_horny():
    """Sell streak no longer triggers chill — victim/nudge handles pressure."""
    mem = _mem(recent_techniques=["SELL LOCK", "SELL LOCK"])
    msg = "ok"
    assert not chill_turn(mem, msg)


def test_victim_after_sell_streak():
    mem = _mem(recent_techniques=["SELL LOCK", "SELL LOCK"])
    gate = evaluate_sell_gate(mem, "still thinking", unpaid=True)
    assert gate.victim_beat
    assert gate.nudge_unpaid
    assert not gate.chill


def test_never_hours_block_via_sell_pressure_paused():
    from datetime import datetime, timedelta, timezone

    from core import fan_memory

    mem = _mem(
        last_reject_at=(datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(),
    )
    assert fan_memory.sell_pressure_paused(mem) is False
    msg = "fuck me harder baby"
    attach, _ = should_attach_ppv(mem, msg)
    assert attach
