"""Voice note must close after pídemelo stall — no beg loop."""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from core import voice_notes as vn
from core import scheme_guard as sg


def test_emma_owed_voice_pidemelo():
    history = [
        {
            "role": "assistant",
            "content": "quieres un audio sucio? pídemelo bien baby…",
        }
    ]
    assert vn.emma_owed_voice(history)
    assert vn.fan_complied_for_voice("por favor")
    assert vn.fan_complied_for_voice("dale mándamelo")


def test_should_send_owed_bypasses_unpaid():
    history = [
        {"role": "assistant", "content": "déjame grabarte algo… pídemelo"},
        {"role": "user", "content": "por favor"},
    ]
    mem = {"messages": 20, "voice_notes_today": 0}
    decision = SimpleNamespace(mode="tease")
    # Force enabled path without ElevenLabs by patching
    ok_orig = vn._enabled
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
            apply_roll=False,
            history_turns=history,
        )
        assert ok, why
        assert "owed" in why or "pídemelo" in why
    finally:
        vn._enabled = ok_orig  # type: ignore


def test_should_send_random_please_without_owed_stays_off():
    history = [
        {"role": "assistant", "content": "how was your day baby?"},
    ]
    mem = {"messages": 20}
    decision = SimpleNamespace(mode="tease")
    ok_orig = vn._enabled
    vn._enabled = lambda: True  # type: ignore
    try:
        ok, why = vn.should_send(
            fan_message="por favor",
            mem=mem,
            decision=decision,
            pack_id="phase_spiral",
            unpaid=False,
            media_sent_this_turn=False,
            barged=False,
            apply_roll=False,
            history_turns=history,
        )
        assert not ok
    finally:
        vn._enabled = ok_orig  # type: ignore


def test_strip_ghost_keeps_coherent_flirt():
    raw = "estoy tan mojada baby… dame un segundo y te preparo algo"
    stripped = sg.strip_ghost_promise_phrases(raw)
    assert "mojada" in stripped.lower()
    assert not sg.ghost_media_promise(stripped, media_attached=False)


def test_thread_beat_flags_pidemelo_loop():
    turns = [
        {"role": "assistant", "content": "pídemelo bien si quieres el audio"},
        {"role": "user", "content": "por favor"},
    ]
    beat = sg.thread_beat_block(turns, {})
    assert "pídemelo loop" in beat.lower() or "Voice/stall debt" in beat


if __name__ == "__main__":
    test_emma_owed_voice_pidemelo()
    test_should_send_owed_bypasses_unpaid()
    test_should_send_random_please_without_owed_stays_off()
    test_strip_ghost_keeps_coherent_flirt()
    test_thread_beat_flags_pidemelo_loop()
    print("ok")
