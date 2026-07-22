"""Clear 'no / not now' on unpaid lock → reconnect, not unlock chase."""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from core.intent_router import route
from core.technique_policy import choose_move


def _mem(**kw):
    base = {
        "messages": 12,
        "status": "warm",
        "total_spent": 0,
        "purchases": 0,
        "free_teases_sent": 1,
    }
    base.update(kw)
    return base


def test_no_sorry_routes_friction_not_ppv_unpaid():
    r = route(
        _mem(),
        "no, sorry",
        delivery_truth={"ppv_unpaid": True, "free_in_chat": False},
    )
    assert r.pack_id == "phase_pull"
    assert r.decision.allow_ppv_talk is False


def test_another_moment_routes_friction():
    r = route(
        _mem(),
        "maybe in another moment, i am not so horny for spend my money on this",
        delivery_truth={"ppv_unpaid": True},
    )
    assert r.pack_id == "phase_pull"


def test_choose_move_soft_decline_is_soft_exit():
    m = choose_move(
        "ppv_unpaid",
        unpaid=True,
        msgs=14,
        mem=_mem(),
        fan_message="no, sorry",
    )
    assert m is not None
    assert m.name == "SOFT EXIT"
