"""Audit R1: dumb voice FSM — open_voice → send, no clever gates."""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from core import voice_notes as vn


def test_fsm_db_commitment_any_message_sends():
    """Once commitment is open, 'ok' alone is enough — no need to say audio."""
    mem = {"open_commitment": {"type": "voice", "hits": 4}, "messages": 30}
    decision = SimpleNamespace(mode="hard_sell")  # would block opportunistic
    orig = vn._enabled
    vn._enabled = lambda: True  # type: ignore
    try:
        ok, why = vn.should_send(
            fan_message="ok",
            mem=mem,
            decision=decision,
            pack_id="ppv_unpaid",
            unpaid=True,
            media_sent_this_turn=False,
            barged=False,
            apply_roll=True,
            history_turns=[],
        )
        assert ok, why
        assert "FSM open_voice" in why
    finally:
        vn._enabled = orig  # type: ignore


def test_fsm_reject_still_blocks():
    mem = {"open_commitment": {"type": "voice", "hits": 2}, "messages": 30}
    orig = vn._enabled
    vn._enabled = lambda: True  # type: ignore
    try:
        ok, why = vn.should_send(
            fan_message="no quiero audio luego",
            mem=mem,
            decision=SimpleNamespace(mode="tease"),
            pack_id="phase_spiral",
            unpaid=False,
            media_sent_this_turn=False,
            barged=False,
            history_turns=[],
        )
        assert not ok
        assert "reject" in why
    finally:
        vn._enabled = orig  # type: ignore


def test_fsm_no_commitment_does_not_force_on_ok():
    mem = {"messages": 30, "open_commitment": None}
    orig = vn._enabled
    vn._enabled = lambda: True  # type: ignore
    try:
        ok, why = vn.should_send(
            fan_message="ok",
            mem=mem,
            decision=SimpleNamespace(mode="tease"),
            pack_id="phase_spiral",
            unpaid=False,
            media_sent_this_turn=False,
            barged=False,
            apply_roll=False,
            history_turns=[{"role": "assistant", "content": "how was your day?"}],
        )
        assert not ok
    finally:
        vn._enabled = orig  # type: ignore


if __name__ == "__main__":
    test_fsm_db_commitment_any_message_sends()
    test_fsm_reject_still_blocks()
    test_fsm_no_commitment_does_not_force_on_ok()
    print("ok")
