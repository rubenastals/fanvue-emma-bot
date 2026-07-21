"""Message → pack routing table (no DeepSeek / no network)."""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from core import packs
from core.intent_router import route


def _mem(**kwargs):
    base = {
        "messages": 10,
        "status": "warm",
        "free_teases_sent": 0,
        "offers_today": 0,
        "total_spent": 0,
        "purchases": 0,
    }
    base.update(kwargs)
    return base


def test_packs_load():
    packs.reload()
    ids = packs.list_pack_ids()
    assert "phase_hook" in ids
    assert "phase_pull" in ids
    body = packs.render("phase_pull")
    assert "TECHNIQUE" in body or "GUILT" in body or "FOMO" in body
    assert len(body) <= packs.budget_chars() + 40


def test_greeting_hook():
    r = route(_mem(messages=2, status="new"), "hola", delivery_truth={})
    assert r.pack_id == "phase_hook"


def test_engacho_spiral():
    r = route(
        _mem(messages=3, status="new", free_teases_sent=0),
        "quiero verte mojada y caliente",
        delivery_truth={},
    )
    assert r.pack_id == "phase_spiral"


def test_engacho_pull_mid():
    r = route(
        _mem(messages=6, status="warm", free_teases_sent=0),
        "estoy duro pensando en ti",
        delivery_truth={},
    )
    assert r.pack_id == "phase_pull"


def test_ppv_unpaid_wins():
    r = route(
        _mem(free_teases_sent=1),
        "hola guapa",
        delivery_truth={"ppv_unpaid": True},
    )
    assert r.pack_id == "ppv_unpaid"
    assert r.decision.allow_price is False


def test_missing_delivery():
    r = route(
        _mem(free_teases_sent=1),
        "no me has mandado ninguna foto",
        delivery_truth={"free_in_chat": False, "ppv_unpaid": False},
    )
    assert r.pack_id == "delivery_missing"


def test_close_after_free_heat():
    # Warm mid-chat without an explicit buy ask → pull/tease, not auto-close
    r = route(
        _mem(messages=12, free_teases_sent=1, status="warm"),
        "jaja que rica",
        delivery_truth={"ppv_unpaid": False},
    )
    assert r.pack_id in ("phase_pull", "tease_heat", "phase_spiral")
    r2 = route(
        _mem(messages=12, free_teases_sent=1, status="warm"),
        "mandame una foto ya",
        delivery_truth={"ppv_unpaid": False},
    )
    assert r2.pack_id in ("phase_close", "escalate_paid", "lock_now")
    assert r2.decision.allow_price is True


def test_price_objection():
    from datetime import datetime, timedelta, timezone

    ago = (datetime.now(timezone.utc) - timedelta(minutes=30)).isoformat()
    r = route(_mem(last_reject_at=ago), "esta muy caro", delivery_truth={})
    assert r.pack_id == "price_objection"


def test_reward_purchase():
    from datetime import datetime, timedelta, timezone

    ago = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
    r = route(_mem(last_purchase_at=ago), "gracias baby", delivery_truth={})
    assert r.pack_id == "reward_purchase"


if __name__ == "__main__":
    packs.reload()
    test_packs_load()
    test_greeting_hook()
    test_engacho_spiral()
    test_engacho_pull_mid()
    test_ppv_unpaid_wins()
    test_missing_delivery()
    test_close_after_free_heat()
    test_price_objection()
    test_reward_purchase()
    print("ALL OK")
