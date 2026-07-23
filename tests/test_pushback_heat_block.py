"""Pushback mode blocks sexual heat even when fan message is short."""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from core.fan_pushback import is_sexual_heat_reply, thread_in_pushback_mode
from core.reply_sanitize import apply_post_draft
from core.send_timing import human_typing_delay


def test_sports_bra_is_sexual():
    assert is_sexual_heat_reply(
        "fuck... now I'm just sitting here in my sports bra wondering what you'd do"
    )


def test_thread_pushback_from_history():
    turns = [
        {"role": "user", "content": "Babe turn off the robot"},
        {"role": "assistant", "content": "hey…"},
        {"role": "user", "content": "?"},
    ]
    assert thread_in_pushback_mode("?", turns, {})


def test_pushback_strips_sexual_draft():
    turns = [
        {"role": "user", "content": "Stop using the AI feature"},
    ]
    assembled = SimpleNamespace(
        messages=[],
        decision=SimpleNamespace(mode="rapport", pack_id="phase_pull"),
        pack_id="phase_pull",
        tech_name="HEAT",
        phase_name="",
        want_spanish=False,
        fan_uuid="pb-fan",
        fan_handle="tommy",
        fan_message="Stop using the AI feature",
        turns=turns,
        offer=None,
        ppv_status=None,
        voice_will_send=False,
        lock_active=False,
        no_lock=True,
        status_active=False,
        unpaid_gate=False,
        never_bought=True,
        fan_saw_bluff=False,
    )
    bad = (
        "fuck... now I'm just sitting here in my sports bra "
        "wondering what you'd do if you were actually next to me 😈"
    )
    out, _ = apply_post_draft(bad, assembled, call=lambda _m: "ok")
    low = out.lower()
    assert "sports bra" not in low
    assert "wondering what you'd do" not in low


def test_typing_delay_scales_with_length():
    short = human_typing_delay("hey", first=True)
    long = human_typing_delay("x" * 120, first=True)
    assert long > short + 5
