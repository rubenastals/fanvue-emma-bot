"""Opportunistic voice must respect daily cap + cooldown (Dan spam fix)."""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from core import voice_notes as vn


def test_opportunistic_respects_cooldown_and_daily_cap():
    decision = SimpleNamespace(mode="tease")
    now = datetime.now(timezone.utc).isoformat()
    mem = {
        "messages": 20,
        "voice_notes_day": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "voice_notes_today": 0,
        "last_voice_at": now,  # fresh → cooldown
        "open_commitment": None,
    }
    orig = vn._enabled
    vn._enabled = lambda: True  # type: ignore
    try:
        ok, why = vn.should_send(
            fan_message="I will grab your ass and fuck you",
            mem=mem,
            decision=decision,
            pack_id="phase_close",
            unpaid=False,
            media_sent_this_turn=False,
            barged=False,
            apply_roll=False,
            history_turns=[],
        )
        assert not ok, why
        assert "cooldown" in why

        mem2 = {
            "messages": 20,
            "voice_notes_day": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "voice_notes_today": 2,
            "last_voice_at": (datetime.now(timezone.utc) - timedelta(hours=10)).isoformat(),
            "open_commitment": None,
        }
        ok2, why2 = vn.should_send(
            fan_message="I will grab your ass and fuck you",
            mem=mem2,
            decision=decision,
            pack_id="phase_close",
            unpaid=False,
            media_sent_this_turn=False,
            barged=False,
            apply_roll=False,
            history_turns=[],
        )
        assert not ok2, why2
        assert "daily cap" in why2
    finally:
        vn._enabled = orig  # type: ignore


def test_fsm_commitment_still_bypasses_cooldown():
    """Fan is owed a voice — send even if we just sent (debt path)."""
    decision = SimpleNamespace(mode="tease")
    mem = {
        "messages": 20,
        "open_commitment": {"type": "voice", "hits": 1},
        "voice_notes_today": 5,
        "voice_notes_day": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "last_voice_at": datetime.now(timezone.utc).isoformat(),
    }
    orig = vn._enabled
    vn._enabled = lambda: True  # type: ignore
    try:
        ok, why = vn.should_send(
            fan_message="ok",
            mem=mem,
            decision=decision,
            pack_id="phase_pull",
            unpaid=False,
            media_sent_this_turn=False,
            barged=False,
            apply_roll=False,
            history_turns=[],
        )
        assert ok, why
        assert "FSM open_voice" in why
    finally:
        vn._enabled = orig  # type: ignore
