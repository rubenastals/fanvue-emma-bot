"""Re-engage blocked on fan boundary; supervisor humanity gate."""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from core.account_onboard import repesca_appropriate
from core.fan_pushback import pick_boundary_fallback, reengage_blocked
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


def test_supervisor_rewrite_not_blocked_by_exhausted_budget(monkeypatch):
    """move-hit can spend sanitize budget; supervisor rewrite must still run."""
    monkeypatch.setattr(sup, "enabled", lambda: True)
    evals = {"n": 0}

    def _eval(reply, _a):
        evals["n"] += 1
        if "fixed" in (reply or "").lower():
            return sup.SupervisorVerdict(ok=True)
        return sup.SupervisorVerdict(ok=False, why="off topic")

    monkeypatch.setattr(sup, "evaluate_reply", _eval)
    assembled = SimpleNamespace(
        fan_message="what do you like in your free time",
        turns=[{"role": "user", "content": "what do you like in your free time"}],
        messages=[],
        fan_uuid="fan-1",
        offer=None,
        voice_will_send=False,
    )
    out = sup.supervise_reply(
        "open this photo baby",
        assembled,
        call=lambda _m: "fixed — gym and music mostly lol",
    )
    assert "fixed" in out.lower()
    assert evals["n"] >= 2


def test_supervisor_rejects_bad_static_fallback(monkeypatch):
    monkeypatch.setattr(sup, "enabled", lambda: True)
    monkeypatch.setattr(
        sup,
        "evaluate_reply",
        lambda reply, _a: sup.SupervisorVerdict(
            ok="gym" in (reply or "").lower(),
            why="off topic" if "game" in (reply or "").lower() else "",
        ),
    )
    monkeypatch.setattr(
        sup,
        "_pick_fallback",
        lambda *_a, **_k: "tell me more about that game then",
    )
    monkeypatch.setattr(
        sup,
        "_contextual_fallback_llm",
        lambda _a, hint="": "honestly gym and music lol… you?",
    )
    assembled = SimpleNamespace(
        fan_message="what do you like in your free time",
        turns=[],
        messages=[],
        fan_uuid="fan-1",
        offer=None,
        voice_will_send=False,
    )
    out = sup.supervise_reply("bad draft", assembled, call=lambda _m: "still bad")
    assert "game" not in out.lower()
    assert "gym" in out.lower()


def test_supervisor_fallback_on_reject(monkeypatch):
    monkeypatch.setattr(sup, "enabled", lambda: True)
    calls = {"n": 0}

    def _eval(_r, _a):
        calls["n"] += 1
        return sup.SupervisorVerdict(ok=False, why="pushy sell after boundary")

    monkeypatch.setattr(sup, "evaluate_reply", _eval)
    monkeypatch.setattr(
        sup,
        "_contextual_fallback_llm",
        lambda _a, hint="": "honestly gym and scrolling my phone lol… you?",
    )
    assembled = SimpleNamespace(
        fan_message="what do you like to do in your free time",
        turns=[
            {"role": "user", "content": "what do you like to do in your free time"},
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
    assert "game" not in out.lower()
    assert calls["n"] >= 1
