"""Dan-thread fixes: bills / can't right now / sell cooldown."""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from core import fan_memory
from core.intent_router import route
from core.soft_decline import is_broke_soft, is_soft_decline
from core.technique_playbook import pick_playbook_move
from core.technique_policy import choose_move


def _mem(**kw):
    base = {
        "messages": 30,
        "status": "warm",
        "total_spent": 0,
        "purchases": 0,
        "free_teases_sent": 1,
    }
    base.update(kw)
    return base


def test_bills_and_cant_right_now_are_soft_decline():
    assert is_soft_decline("I can't open it yet, as I need to pay my bills first")
    assert is_soft_decline("I can't right now")
    assert is_broke_soft("need to pay my bills first")


def test_bills_routes_friction_not_ppv_unpaid():
    r = route(
        _mem(),
        "I need to pay my bills first",
        delivery_truth={"ppv_unpaid": True},
    )
    assert r.pack_id == "phase_pull"
    assert r.decision.allow_ppv_talk is False


def test_sell_paused_after_recent_reject():
    mem = _mem(
        last_reject_at=(datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(),
        price_objection_step=1,
    )
    assert fan_memory.sell_pressure_paused(mem)
    r = route(
        mem,
        "Absolutely",
        delivery_truth={"ppv_unpaid": True},
    )
    assert r.pack_id == "phase_pull"


def test_playbook_sell_paused_skips_sell_lock():
    move, why = pick_playbook_move(
        pack_id="ppv_unpaid",
        sig={"msgs": 40, "horny": True, "buying": False, "sell_paused": True},
        unpaid=True,
        recent_techs=[],
    )
    assert move.name == "HEAT"
    assert "cooldown" in why


def test_choose_move_cant_right_now_soft_exit():
    m = choose_move(
        "ppv_unpaid",
        unpaid=True,
        msgs=40,
        mem=_mem(),
        fan_message="I can't right now",
    )
    assert m is not None
    assert m.name == "SOFT EXIT"


def test_sell_paused_injects_sell_window_turn_line(monkeypatch):
    from core.reply_assemble import assemble_emma_turn

    mem = _mem(
        last_reject_at=(datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(),
    )
    monkeypatch.setattr(fan_memory, "get", lambda _u: mem)
    monkeypatch.setattr(fan_memory, "sell_pressure_paused", lambda _m, **kw: True)
    assembled = assemble_emma_turn(
        "hey",
        history_turns=[{"role": "user", "content": "hey"}],
        fan_uuid="fan-sell-pause",
        fan_handle="dan",
    )
    blob = "\n".join(m["content"] for m in assembled.messages if m["role"] == "system")
    assert "SELL WINDOW: CLOSED" in blob
