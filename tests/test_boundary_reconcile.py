"""Boundary reconcile — warm fan after friction gets BOND not SOFT EXIT loop."""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from core.fan_pushback import (
    boundary_reconciling,
    is_boundary_warm_message,
    pick_boundary_fallback,
)
from core import technique_playbook as pb


def test_warm_apology_detected():
    assert is_boundary_warm_message("I'm very sorryyyy I'm a bit busy")
    assert is_boundary_warm_message("what do you like to do in your free time")


def test_reconcile_after_warm_streak():
    mem = {"fan_boundary_active": True, "boundary_warm_streak": 1}
    assert boundary_reconciling("why would you call me mystery man", mem)


def test_reconcile_normal_question():
    mem = {"photo_refusal_active": True, "fan_boundary_active": False}
    assert boundary_reconciling("not really...", mem)


def test_playbook_reconcile_picks_bond_not_soft_exit():
    sig = {
        "boundary_reconciling": True,
        "compliment": True,
        "flirting": True,
        "msgs": 20,
    }
    move, why = pb.pick_playbook_move(
        pack_id="phase_pull",
        sig=sig,
        unpaid=False,
        recent_techs=["SOFT EXIT", "SOFT EXIT"],
    )
    assert move.name in ("BOND", "HEAT")
    assert why.startswith("reconcile")


def test_boundary_fallback_varies_for_hobbies():
    a = pick_boundary_fallback("what do you like to do in your free time")
    b = pick_boundary_fallback("okay thanks you're sweet")
    assert a != b
    assert "game" not in a.lower()
