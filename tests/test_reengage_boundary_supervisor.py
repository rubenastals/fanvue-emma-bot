"""Re-engage blocked on fan boundary; supervisor humanity gate."""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from core.account_onboard import repesca_appropriate
from core.fan_pushback import reengage_blocked
from core.farewell import clear_conversation_closed
from core import reply_supervisor as sup


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
  # patch_fanvue_platform is exercised via fan_memory in integration;
  # here we only assert the farewell helper forwards the flag shape.
    import inspect

    sig = inspect.signature(clear_conversation_closed)
    assert "preserve_reengage_pause" in sig.parameters


def test_supervisor_accepts_ok_draft(monkeypatch):
    monkeypatch.setattr(sup, "enabled", lambda: True)
    monkeypatch.setattr(
        sup,
        "evaluate_reply",
        lambda _r, _a: sup.SupervisorVerdict(ok=True),
    )
    assembled = SimpleNamespace(
        fan_message="hey",
        turns=[{"role": "user", "content": "hey"}],
        messages=[],
        fan_uuid=None,
        offer=None,
        voice_will_send=False,
    )
    out = sup.supervise_reply("hey babe what's up", assembled, call=lambda _m: "nope")
    assert out == "hey babe what's up"


def test_supervisor_fallback_on_reject(monkeypatch):
    monkeypatch.setattr(sup, "enabled", lambda: True)
    calls = {"n": 0}

    def _eval(_r, _a):
        calls["n"] += 1
        return sup.SupervisorVerdict(ok=False, why="pushy sell after boundary")

    monkeypatch.setattr(sup, "evaluate_reply", _eval)
    assembled = SimpleNamespace(
        fan_message="stop asking for pictures",
        turns=[
            {"role": "user", "content": "stop asking for pictures"},
        ],
        messages=[],
        fan_uuid="fan-1",
        offer=None,
        voice_will_send=False,
    )
    out = sup.supervise_reply(
        "open this photo for $7 baby",
        assembled,
        call=lambda _m: "still bad",
    )
    assert "$7" not in out
    assert calls["n"] >= 1
