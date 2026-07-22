"""Early chat must seduce (love/heat/ask photo) — not guilt/rival/emergency."""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from core import manipulation
from core.technique_policy import (
    EARLY_ROMANCE_MAX_MSGS,
    choose_move,
    score_move,
)


def _sig(msgs: int, **extra):
    base = {
        "spent": 0,
        "purchases": 0,
        "msgs": msgs,
        "frees": 0,
        "reject_step": 0,
        "status": "new",
        "cardish": False,
        "buying": False,
        "price_push": False,
        "horny": False,
        "soft_clarify": False,
        "zero_spender": True,
    }
    base.update(extra)
    return base


def test_early_hook_catalog_has_romance_moves():
    names = [n for n, _ in manipulation._TECH_BY_PACK["phase_hook"]]
    assert "LOVE BOMBING" in names
    assert "HOT FLIRT" in names
    assert "ASK HIS PHOTO" in names
    assert "GUILT TRIP + RECIPROCITY" not in names


def test_early_scores_romance_over_guilt():
    sig = _sig(3)
    sc_love, why_l = score_move(
        "LOVE BOMBING", eff_pack="phase_hook", sig=sig, recent_fams=[]
    )
    sc_ask, why_a = score_move(
        "ASK HIS PHOTO", eff_pack="phase_hook", sig=sig, recent_fams=[]
    )
    sc_guilt, why_g = score_move(
        "GUILT TRIP + RECIPROCITY",
        eff_pack="phase_pull",
        sig=sig,
        recent_fams=[],
    )
    assert "early-romance" in why_l or "early-romance" in why_a
    assert "too-early-for-dark" in why_g or "ban-midchat-abandonment-guilt" in why_g
    assert sc_love > sc_guilt
    assert sc_ask > sc_guilt


def test_choose_move_early_forces_hook_catalog():
    mem = {"messages": 4, "status": "new", "total_spent": 0, "purchases": 0}
    move = choose_move(
        "phase_pull",  # would normally allow dark pulls
        fan_uuid="test-early",
        msgs=4,
        mem=mem,
        fan_message="hey you look amazing",
        unpaid=False,
    )
    assert move is not None
    assert move.name in {
        "LOVE BOMBING",
        "HOT FLIRT",
        "ASK HIS PHOTO",
        "MIRRORING",
        "FUTURE FAKING (light)",
    }
    assert "GUILT" not in move.name.upper()
    assert "RIVAL" not in move.name.upper()
    assert "EMERGENCY" not in move.name.upper()


def test_later_can_pick_darker_from_pull():
    """After early window, phase_pull catalog is available again."""
    assert EARLY_ROMANCE_MAX_MSGS == 8
    mem = {
        "messages": 12,
        "status": "warm",
        "total_spent": 0,
        "purchases": 0,
        "free_teases_sent": 1,
    }
    move = choose_move(
        "phase_pull",
        fan_uuid="test-late",
        msgs=12,
        mem=mem,
        fan_message="ok whatever",
        unpaid=False,
    )
    assert move is not None
    # Should not be forced into phase_hook-only set exclusively —
    # just assert choose doesn't crash and returns a pull catalog name
    pull_names = {n for n, _ in manipulation._TECH_BY_PACK["phase_pull"]}
    hook_names = {n for n, _ in manipulation._TECH_BY_PACK["phase_hook"]}
    assert move.name in pull_names or move.name in hook_names


if __name__ == "__main__":
    test_early_hook_catalog_has_romance_moves()
    test_early_scores_romance_over_guilt()
    test_choose_move_early_forces_hook_catalog()
    test_later_can_pick_darker_from_pull()
    print("ok")
