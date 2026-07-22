"""Voice script must not read the text bubble aloud; cooldown after send."""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from core import voice_notes as vn


def test_script_echoes_verbatim_prefix():
    reply = "porque estaba decidiendo si merecías escucharme después de lo que hiciste..."
    script = "porque estaba decidiendo si merecías escucharme después de lo que hiciste... pero"
    assert vn.script_echoes_reply(script, reply)


def test_script_new_beat_not_echo():
    reply = "porque estaba decidiendo si merecías escucharme después de lo que hiciste..."
    script = "Mmm... cierra los ojos un segundo... quiero susurrarte algo que no me atreví a escribir..."
    assert not vn.script_echoes_reply(script, reply)


def test_post_delivery_stale_thread_ask_does_not_resend():
    """After a successful send, old 'audio' asks in history must not reopen debt."""
    mem = {
        "messages": 40,
        "open_commitment": None,
        "last_voice_at": datetime.now(timezone.utc).isoformat(),
    }
    history = [
        {"role": "user", "content": "mandame un audio"},
        {"role": "assistant", "content": "vale bebé..."},
        {"role": "user", "content": "como has tardado tanto?"},
    ]
    decision = SimpleNamespace(mode="soft_sell")
    orig = vn._enabled
    vn._enabled = lambda: True  # type: ignore
    try:
        ok, why = vn.should_send(
            fan_message="como has tardado tanto?",
            mem=mem,
            decision=decision,
            pack_id="phase_spiral",
            unpaid=False,
            media_sent_this_turn=False,
            barged=False,
            apply_roll=False,
            history_turns=history,
        )
        assert not ok, why
    finally:
        vn._enabled = orig  # type: ignore


def test_post_delivery_fresh_ask_still_sends():
    mem = {
        "messages": 40,
        "open_commitment": None,
        "last_voice_at": datetime.now(timezone.utc).isoformat(),
    }
    orig = vn._enabled
    vn._enabled = lambda: True  # type: ignore
    try:
        ok, why = vn.should_send(
            fan_message="otro audio por favor",
            mem=mem,
            decision=SimpleNamespace(mode="tease"),
            pack_id="phase_spiral",
            unpaid=False,
            media_sent_this_turn=False,
            barged=False,
            apply_roll=False,
            history_turns=[],
        )
        assert ok, why
        assert "post-delivery" in why or "this turn" in why
    finally:
        vn._enabled = orig  # type: ignore


def test_cooldown_expired_allows_thread_debt_again():
    mem = {
        "messages": 40,
        "open_commitment": None,
        "last_voice_at": (
            datetime.now(timezone.utc) - timedelta(hours=7)
        ).isoformat(),
    }
    history = [
        {"role": "assistant", "content": "quieres un audio? pídemelo bien"},
        {"role": "user", "content": "por favor"},
    ]
    orig = vn._enabled
    vn._enabled = lambda: True  # type: ignore
    try:
        ok, why = vn.should_send(
            fan_message="por favor",
            mem=mem,
            decision=SimpleNamespace(mode="tease"),
            pack_id="phase_spiral",
            unpaid=False,
            media_sent_this_turn=False,
            barged=False,
            apply_roll=False,
            history_turns=history,
        )
        assert ok, why
    finally:
        vn._enabled = orig  # type: ignore


if __name__ == "__main__":
    test_script_echoes_verbatim_prefix()
    test_script_new_beat_not_echo()
    test_post_delivery_stale_thread_ask_does_not_resend()
    test_post_delivery_fresh_ask_still_sends()
    test_cooldown_expired_allows_thread_debt_again()
    print("ok")
