"""Re-engage blocked on fan boundary; contextual boundary fallbacks."""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from core.account_onboard import repesca_appropriate
from core.fan_pushback import pick_boundary_fallback, reengage_blocked
from core.farewell import clear_conversation_closed


def test_reengage_blocked_on_boundary_memory():
    assert reengage_blocked({"fan_boundary_active": True})
    assert reengage_blocked({"photo_refusal_active": True})
    assert reengage_blocked({"pushback_active": True})
    assert not reengage_blocked({})


def test_repesca_skips_boundary_memory():
    ok, reason = repesca_appropriate(
        [{"sender": {"uuid": "fan"}, "text": "hey"}],
        "fan",
        "creator",
        {"messages": 5, "fan_boundary_active": True},
    )
    assert not ok
    assert reason == "fan_boundary"


def test_clear_closed_preserves_reengage_pause():
    import inspect

    sig = inspect.signature(clear_conversation_closed)
    assert "preserve_reengage_pause" in sig.parameters


def test_boundary_fallback_answers_free_time_question():
    msg = "okayy thankss\nyou are sweet 😊\nwhat do you like to do in your free time"
    out = pick_boundary_fallback(msg)
    assert "game" not in out.lower()
    assert "umamusume" not in out.lower()
    assert any(
        w in out.lower()
        for w in ("gym", "chill", "you", "sweet", "phone", "home", "tiktok")
    )


def test_boundary_fallback_thanks_not_game():
    out = pick_boundary_fallback("okay thanks you're sweet")
    assert "game" not in out.lower()
    assert any(w in out.lower() for w in ("sweet", "thank", "cute", "smile"))
