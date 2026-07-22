"""20-msg audio beg loop must force send + ban another pídemelo."""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from core import voice_notes as vn


def _long_audio_loop():
    turns = []
    for i in range(10):
        turns.append(
            {
                "role": "assistant",
                "content": "quieres un audio sucio? pídemelo bien baby…",
            }
        )
        turns.append({"role": "user", "content": "por favor ya"})
    return turns


def test_thread_debt_detects_long_loop():
    debt, why = vn.thread_voice_debt(_long_audio_loop(), lookback=20)
    assert debt, why
    assert "debt" in why or "stall" in why or "fan=" in why


def test_kill_beg_loop_forces_send():
    history = _long_audio_loop()
    mem = {"messages": 40}
    decision = SimpleNamespace(mode="tease")
    orig = vn._enabled
    vn._enabled = lambda: True  # type: ignore
    try:
        ok, why = vn.should_send(
            fan_message="por favor",
            mem=mem,
            decision=decision,
            pack_id="ppv_unpaid",
            unpaid=True,
            media_sent_this_turn=False,
            barged=False,
            apply_roll=True,  # must still fire even with roll
            history_turns=history,
        )
        assert ok, why
        assert "FSM open_voice" in why or "open_voice" in why, why
    finally:
        vn._enabled = orig  # type: ignore


def test_reply_voice_beg_detected():
    assert vn.reply_is_voice_beg("pídemelo bien si quieres el audio")
    assert vn.reply_is_voice_beg("quieres un audio baby?")
    assert not vn.reply_is_voice_beg("ven aquí un segundo… esto es solo para ti")


def test_forced_close_not_beg():
    line = vn.forced_voice_close_line(want_spanish=True)
    assert not vn.reply_is_voice_beg(line)


def test_debt_clears_after_delivery_stub():
    history = _long_audio_loop()
    history.append(
        {"role": "assistant", "content": "mmm [you sent a VOICE NOTE — free audio, not a photo]"}
    )
    debt, why = vn.thread_voice_debt(history, lookback=24)
    assert not debt, why


if __name__ == "__main__":
    test_thread_debt_detects_long_loop()
    test_kill_beg_loop_forces_send()
    test_reply_voice_beg_detected()
    test_forced_close_not_beg()
    test_debt_clears_after_delivery_stub()
    print("ok")
