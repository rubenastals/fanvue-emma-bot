"""Dan-thread fixes: bills / can't right now / sell cooldown."""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from core import fan_memory
from core.intent_router import route
from core.sell_gate import chill_turn, should_attach_ppv
from core.soft_decline import is_broke_soft, is_soft_decline
from core.technique_playbook import pick_playbook_move, VICTIM
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


def test_sell_pressure_paused_never_hard_blocks():
    mem = _mem(
        last_reject_at=(datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(),
        price_objection_step=1,
    )
    assert fan_memory.sell_pressure_paused(mem) is False


def test_playbook_hot_unpaid_presses_sell_lock():
    move, why = pick_playbook_move(
        pack_id="ppv_unpaid",
        sig={"msgs": 40, "horny": True, "buying": False},
        unpaid=True,
        recent_techs=[],
    )
    assert move.name == "SELL LOCK"
    assert "hot" in why


def test_playbook_victim_after_sell_streak():
    move, why = pick_playbook_move(
        pack_id="ppv_unpaid",
        sig={"msgs": 40, "horny": True, "buying": False, "reject_step": 0},
        unpaid=True,
        recent_techs=["SELL LOCK", "SELL LOCK"],
    )
    assert move.name == VICTIM.name
    assert "victim" in why


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


def test_bills_chill_turn_only():
    mem = _mem()
    msg = "I can't open it yet, as I need to pay my bills first"
    assert chill_turn(mem, msg)
    attach, _ = should_attach_ppv(mem, msg)
    assert not attach


def test_horny_return_attaches_despite_prior_reject():
    mem = _mem(
        last_reject_at=(datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(),
    )
    msg = "fuck baby spread your legs for me"
    attach, _ = should_attach_ppv(mem, msg)
    assert attach


def test_unpaid_explicit_horny_routes_ppv_unpaid_not_pull():
    mem = _mem(
        last_reject_at=(datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(),
    )
    r = route(
        mem,
        "fuck baby spread your legs for me",
        delivery_truth={"ppv_unpaid": True},
    )
    assert r.pack_id == "ppv_unpaid"
    assert r.decision.allow_ppv_talk is True
