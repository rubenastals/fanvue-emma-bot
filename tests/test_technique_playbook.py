"""Slim 6-move playbook — WHEN tree + signals."""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from core import technique_playbook as pb
from core import technique_policy


def test_playbook_has_six_moves():
    assert set(pb.PLAYBOOK) == {
        "BOND",
        "HEAT",
        "ASK PIC",
        "SELL LOCK",
        "HOLD FRAME",
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


def test_reward_pack():
    move = technique_policy.choose_move(
        "reward_purchase",
        mem={"messages": 20, "total_spent": 15, "purchases": 1},
        turn_action=SimpleNamespace(action="flirt"),
    )
    assert move is not None
    assert move.name == "REWARD"


def test_early_bond_or_ask_pic():
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
