"""Earned sell pressure — aggressive unpaid only on hot/rapport threads."""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from core.sell_pressure import earned_sell_pressure, victim_pressure_eligible
from core.technique_playbook import pick_playbook_move


def _hot_mem(**kw):
    base = {
        "messages": 40,
        "recent_techniques": ["HEAT", "SELL LOCK", "HEAT", "BOND"],
    }
    base.update(kw)
    return base


def _cold_mem(**kw):
    base = {
        "messages": 5,
        "recent_techniques": ["BOND", "ASK PIC"],
    }
    base.update(kw)
    return base


def test_cold_early_unpaid_not_earned():
    assert not earned_sell_pressure(
        _cold_mem(),
        "hey",
        history_turns=[{"role": "user", "content": "hey"}],
    )


def test_hot_thread_earned():
    assert earned_sell_pressure(
        _hot_mem(),
        "I need to pay my bills first",
        history_turns=[
            {"role": "user", "content": "fuck baby spread your legs"},
            {"role": "assistant", "content": "mm yes"},
        ],
    )


def test_playbook_cold_unpaid_bonds_not_victim():
    move, why = pick_playbook_move(
        pack_id="ppv_unpaid",
        sig={
            "msgs": 5,
            "soft_decline": True,
            "reject_step": 3,
            "earned_pressure": False,
        },
        unpaid=True,
        recent_techs=["BOND"],
    )
    assert move.name == "SOFT EXIT"
    assert "cold" in why


def test_playbook_hot_unpaid_bills_is_victim():
    move, why = pick_playbook_move(
        pack_id="ppv_unpaid",
        sig={
            "msgs": 40,
            "soft_decline": True,
            "reject_step": 3,
            "victim_beat": True,
            "earned_pressure": True,
        },
        unpaid=True,
        recent_techs=["HEAT", "SELL LOCK", "HEAT"],
    )
    assert move.name == "VICTIM"
    assert "victim" in why


def test_victim_pressure_requires_heat_not_just_reject():
    assert not victim_pressure_eligible(
        _cold_mem(price_objection_step=3),
        "not now sorry",
        history_turns=[{"role": "user", "content": "hey"}],
    )
