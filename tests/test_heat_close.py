"""Heat-close path — explicit RP should attach + steer sell, not 'fuck baby…'."""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from core.chat_heat import (
    explicit_horny_now,
    heat_close_eligible,
    hot_unpaid_nudge_eligible,
)
from core.offer_selector import choose_offer


def _mem(**kw):
    base = {
        "messages": 20,
        "status": "warm",
        "total_spent": 0.0,
        "purchases": 0,
        "free_teases_sent": 1,
        "sent_media_uuids": [],
    }
    base.update(kw)
    return base


def _paused_mem():
    return _mem(
        last_reject_at=(datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(),
    )


def test_explicit_rp_is_heat_close_eligible():
    msg = "He'd ram his huge cock into you so hard it left you dry."
    assert heat_close_eligible(_mem(), msg)


def test_heat_close_blocked_when_sell_paused_on_warm_msg():
    msg = "hey"
    assert not heat_close_eligible(_paused_mem(), msg, sell_paused=True)


def test_heat_close_bypasses_sell_pause_on_explicit_horny():
    msg = "He'd ram his huge cock into you so hard it left you dry."
    assert heat_close_eligible(_paused_mem(), msg, sell_paused=True)


def test_hot_unpaid_nudge_when_unpaid_lock_and_explicit():
    msg = "fuck baby I want to see you spread wide for me"
    assert hot_unpaid_nudge_eligible(_mem(), msg)
    assert not heat_close_eligible(_mem(), msg, unpaid=True)


def test_only_this_with_horny_history_attaches(monkeypatch):
    """Dan-style: weak this turn but thread was explicit → still close."""
    monkeypatch.setattr("config.config.OFFER_SELECTOR_AI", False)
    monkeypatch.setattr("config.config.DEEPSEEK_API_KEY", "")
    fake_item = {
        "media_uuid": "test-uuid-heat",
        "level": 2,
        "price": 8.0,
        "label": "bed tease",
        "score": 7,
    }
    monkeypatch.setattr(
        "core.offer_selector.candidate_offers",
        lambda *a, **k: [fake_item],
    )
    history = [
        {"role": "user", "content": "I'd fuck you so hard you'd be dripping"},
        {"role": "assistant", "content": "mm tell me more"},
        {"role": "user", "content": "only this?"},
    ]
    choice = choose_offer(_mem(), "only this?", history_turns=history)
    assert choice.sell_now is True
    assert choice.source == "code"


def test_choose_offer_attaches_on_explicit_rp(monkeypatch):
    """Code-first attach even when selector AI is off."""
    monkeypatch.setattr("config.config.OFFER_SELECTOR_AI", False)
    monkeypatch.setattr("config.config.DEEPSEEK_API_KEY", "")
    fake_item = {
        "media_uuid": "test-uuid-heat",
        "level": 2,
        "price": 8.0,
        "label": "bed tease",
        "score": 7,
    }
    monkeypatch.setattr(
        "core.offer_selector.candidate_offers",
        lambda *a, **k: [fake_item],
    )
    msg = "He'd ram his huge cock into you so hard it left you dry."
    choice = choose_offer(_mem(), msg, history_turns=[{"role": "user", "content": msg}])
    assert choice.sell_now is True
    assert choice.offer is not None
    assert choice.source == "code"


def test_explicit_horny_now_detects_rp():
    assert explicit_horny_now("fuck me harder with that huge cock")
    assert not explicit_horny_now("hey")
