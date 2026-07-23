"""Slim 6-move playbook — WHEN tree + signals."""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from core import technique_playbook as pb
from core import technique_policy


def test_playbook_has_core_moves():
    assert set(pb.PLAYBOOK) >= {
        "BOND",
        "HEAT",
        "ASK PIC",
        "SELL LOCK",
        "HOLD FRAME",
        "SOFT EXIT",
        "VICTIM",
        "REWARD",
    }


def test_unpaid_picks_sell_lock():
    move = technique_policy.choose_move(
        "ppv_unpaid",
        unpaid=True,
        mem={"messages": 12, "total_spent": 0},
        turn_action=SimpleNamespace(action="flirt"),
    )
    assert move is not None
    assert move.name == "SELL LOCK"


def test_price_objection_holds_frame():
    move = technique_policy.choose_move(
        "price_objection",
        unpaid=True,
        reject_count=0,
        turn_action=SimpleNamespace(action="flirt"),
    )
    assert move is not None
    assert move.name == "HOLD FRAME"
    assert "GUILT" not in move.name
    assert "EMERGENCY" not in move.name


def test_price_objection_victim_after_rejects():
    move = technique_policy.choose_move(
        "price_objection",
        unpaid=True,
        reject_count=3,
        turn_action=SimpleNamespace(action="flirt"),
    )
    assert move is not None
    assert move.name == "VICTIM"


def test_victim_after_hold_frame_streak():
    move, why = pb.pick_playbook_move(
        pack_id="ppv_unpaid",
        sig={"msgs": 14, "reject_step": 1, "price_push": True},
        unpaid=True,
        recent_techs=["HOLD FRAME", "HOLD FRAME"],
    )
    assert move.name == "VICTIM"
    assert "victim" in why


def test_ask_how_you_look_is_sell_lock_not_hold():
    move, why = pb.pick_playbook_move(
        pack_id="ppv_unpaid",
        sig={
            "msgs": 14,
            "reject_step": 2,
            "price_push": False,
            "ask_lock_tease": True,
        },
        unpaid=True,
        recent_techs=["HOLD FRAME", "HOLD FRAME"],
    )
    assert move.name == "SELL LOCK"
    assert "describe" in why


def test_reject_step_alone_does_not_force_hold():
    move, why = pb.pick_playbook_move(
        pack_id="ppv_unpaid",
        sig={"msgs": 14, "reject_step": 2, "price_push": False},
        unpaid=True,
        recent_techs=["HOLD FRAME"],
    )
    assert move.name == "SELL LOCK"


def test_soft_decline_exits_sell_lock():
    move, why = pb.pick_playbook_move(
        pack_id="ppv_unpaid",
        sig={"msgs": 14, "soft_decline": True, "price_push": False},
        unpaid=True,
        recent_techs=["SELL LOCK", "SELL LOCK"],
    )
    assert move.name == "SOFT EXIT"
    assert "decline" in why


def test_sell_streak_soft_exits():
    move, why = pb.pick_playbook_move(
        pack_id="ppv_unpaid",
        sig={"msgs": 14, "soft_decline": False, "buying": False, "horny": False},
        unpaid=True,
        recent_techs=["SELL LOCK", "SELL LOCK"],
    )
    assert move.name == "SOFT EXIT"


def test_after_soft_exit_bonds_not_resell():
    move, why = pb.pick_playbook_move(
        pack_id="ppv_unpaid",
        sig={"msgs": 14, "soft_decline": False},
        unpaid=True,
        recent_techs=["SOFT EXIT"],
    )
    assert move.name == "BOND"
    assert "post-exit" in why


def test_shy_graduates_to_heat_after_rapport(monkeypatch):
    monkeypatch.setattr("core.creative_first.enabled", lambda: False)
    move = technique_policy.choose_move(
        "phase_pull",
        msgs=9,
        mem={"messages": 9, "total_spent": 0, "free_teases_sent": 1},
        no_lock=True,
        fan_message="ok cute",
        turn_action=SimpleNamespace(action="flirt"),
    )
    assert move is not None
    assert move.name in {"HEAT", "BOND", "ASK PIC"}


def test_reward_pack(monkeypatch):
    monkeypatch.setattr("core.creative_first.enabled", lambda: False)
    move = technique_policy.choose_move(
        "reward_purchase",
        mem={"messages": 20, "total_spent": 15, "purchases": 1},
        turn_action=SimpleNamespace(action="flirt"),
    )
    assert move is not None
    assert move.name == "REWARD"


def test_early_bond_or_ask_pic(monkeypatch):
    monkeypatch.setattr("core.creative_first.enabled", lambda: False)
    move = technique_policy.choose_move(
        "phase_hook",
        msgs=3,
        mem={"messages": 3, "total_spent": 0},
        no_lock=True,
        turn_action=SimpleNamespace(action="flirt"),
        fan_message="hey",
    )
    assert move is not None
    assert move.name in {"BOND", "ASK PIC", "HEAT"}


def test_turn_block_has_when_never():
    block = technique_policy.turn_block(
        technique_policy.ActiveMove(
            name="HEAT",
            how="dirty-sweet",
            why="flirt-heat",
            family_id="2.1",
            principle="sexual charge",
        )
    )
    assert "ACTIVE MOVE THIS TURN" in block
    assert "HEAT" in block
    assert "WHEN:" in block
    assert "NEVER:" in block
    assert "Example beat" in block


def test_reply_hits_playbook_signals():
    assert technique_policy.reply_hits_move(
        "fuck… you're getting me warm just reading that",
        "HEAT",
    )
    assert technique_policy.reply_hits_move(
        "that one's still sitting there… fuck i look filthy in it",
        "SELL LOCK",
    )
    assert not technique_policy.reply_hits_move(
        "jaja bb qué haces",
        "SELL LOCK",
    )


def test_legacy_name_maps_to_playbook_signals():
    assert technique_policy.reply_hits_move(
        "glad you're here… you're different",
        "LOVE BOMBING",
    )
