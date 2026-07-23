"""Memory callbacks — unprompted recall of card facts."""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from core import fan_memory, memory_callbacks


def _mem(*, facts=None, hours_old: float = 24.0, **kw):
    now = datetime(2026, 7, 23, 12, 0, tzinfo=timezone.utc)
    card_at = now - timedelta(hours=hours_old)
    base = {
        "facts": facts or ["job interview on Thursday"],
        "interaction_digest_at": card_at.isoformat(timespec="seconds"),
        "callback_usage": {},
    }
    base.update(kw)
    return base, now


def test_reconnect_fires_callback(monkeypatch):
    mem, now = _mem()
    usage_store: dict = {}

    monkeypatch.setattr(
        fan_memory, "get_callback_usage", lambda u: dict(usage_store.get(u, {}))
    )

    def _record(u, fid, item, **kw):
        usage_store.setdefault(u, {})[fid] = {
            "uses": 1,
            "last_at": now.isoformat(timespec="seconds"),
        }
        usage_store[u]["_last_fire_at"] = now.isoformat(timespec="seconds")

    monkeypatch.setattr(fan_memory, "record_callback_fire", _record)

    line = memory_callbacks.pick(
        "fan-cb-reconnect",
        mem,
        gap_minutes=120,
        sell_open=False,
        mode="BOND",
        now=now,
    )
    assert line is not None
    assert "CALLBACK THIS TURN" in line
    assert "interview" in line.lower()


def test_sensitive_blocked_when_sell_open(monkeypatch):
    mem, now = _mem(facts=["got laid off last week"])
    monkeypatch.setattr(fan_memory, "get_callback_usage", lambda _u: {})
    monkeypatch.setattr(fan_memory, "record_callback_fire", lambda *a, **k: None)

    line = memory_callbacks.pick(
        "fan-cb-sensitive",
        mem,
        gap_minutes=120,
        sell_open=True,
        mode="OFFER_OK",
        now=now,
    )
    assert line is None


def test_sensitive_warmth_line_in_bond(monkeypatch):
    mem, now = _mem(facts=["got laid off last week"], hours_old=30.0)
    monkeypatch.setattr(fan_memory, "get_callback_usage", lambda _u: {})
    monkeypatch.setattr(fan_memory, "record_callback_fire", lambda *a, **k: None)

    line = memory_callbacks.pick(
        "fan-cb-warmth",
        mem,
        gap_minutes=120,
        sell_open=False,
        mode="BOND",
        now=now,
    )
    assert line is not None
    assert "warmth only" in line.lower()


def test_repeat_cooldown_blocks_same_fact(monkeypatch):
    mem, now = _mem()
    fid = memory_callbacks._fid(mem["facts"][0])
    usage = {
        fid: {
            "uses": 1,
            "last_at": (now - timedelta(days=1)).isoformat(timespec="seconds"),
        }
    }
    monkeypatch.setattr(fan_memory, "get_callback_usage", lambda _u: dict(usage))
    monkeypatch.setattr(fan_memory, "record_callback_fire", lambda *a, **k: None)

    line = memory_callbacks.pick(
        "fan-cb-cooldown",
        mem,
        gap_minutes=120,
        sell_open=False,
        mode="BOND",
        now=now,
    )
    assert line is None


def test_quiet_bond_turn_probabilistic():
    mem, now = _mem()
    with patch.object(memory_callbacks.random, "random", return_value=0.99):
        line = memory_callbacks.pick(
            "fan-cb-quiet",
            mem,
            gap_minutes=5,
            sell_open=False,
            mode="BOND",
            now=now,
        )
    assert line is None


def test_assemble_wires_callback_on_reconnect(monkeypatch):
    from core.reply_assemble import assemble_emma_turn

    mem, now = _mem()
    monkeypatch.setattr(fan_memory, "get", lambda _u: mem)
    monkeypatch.setattr(fan_memory, "sell_pressure_paused", lambda _m, **kw: False)
    monkeypatch.setattr(
        fan_memory, "get_callback_usage", lambda _u: dict(mem.get("callback_usage") or {})
    )

    def _record(u, fid, item, **kw):
        usage = mem.setdefault("callback_usage", {})
        usage[fid] = {"uses": 1, "last_at": now.isoformat(timespec="seconds")}
        usage["_last_fire_at"] = now.isoformat(timespec="seconds")

    monkeypatch.setattr(fan_memory, "record_callback_fire", _record)

    assembled = assemble_emma_turn(
        "hey",
        history_turns=[{"role": "user", "content": "hey"}],
        fan_uuid="fan-assemble-cb",
        fan_handle="dan",
        fan_message_age_minutes=120.0,
    )
    blob = "\n".join(m["content"] for m in assembled.messages if m["role"] == "system")
    assert "CALLBACK THIS TURN" in blob
