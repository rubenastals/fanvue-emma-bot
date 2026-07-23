"""Heat-close path — explicit RP should attach + steer sell, not 'fuck baby…'."""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from core.chat_heat import heat_close_eligible
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


def test_explicit_rp_is_heat_close_eligible():
    msg = "He'd ram his huge cock into you so hard it left you dry."
    assert heat_close_eligible(_mem(), msg)


def test_heat_close_blocked_when_sell_paused():
    from datetime import datetime, timedelta, timezone

    mem = _mem(
        last_reject_at=(datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(),
    )
    msg = "He'd ram his huge cock into you so hard"
    assert not heat_close_eligible(mem, msg, sell_paused=True)


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
