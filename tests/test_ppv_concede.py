"""Defend expensive unpaid PPV, then concede to cheaper L1–L2."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from core import ppv_concede as pc


_FAKE_VAULT = [
    {"media_uuid": "c1", "level": 1, "price": 4.0, "label": "Lingerie", "score": 5},
    {"media_uuid": "c2", "level": 2, "price": 7.0, "label": "Topless", "score": 6},
    {"media_uuid": "c6", "level": 6, "price": 40.0, "label": "Extreme", "score": 10},
]


def _mem_expensive(**extra):
    m = {
        "purchases": 0,
        "total_spent": 0.0,
        "last_ppv_price": 40.0,
        "last_offer": 40.0,
        "last_offer_level": 6,
        "last_ppv_pending": True,
        "last_ppv_message_uuid": "msg-expensive-1",
        "price_defend_hits": 0,
        "price_concede_done": False,
        "sent_media_uuids": ["c6"],
    }
    m.update(extra)
    return m


def test_asks_cheaper_detects_es():
    assert pc.fan_asks_cheaper("está muy caro bebé")
    assert pc.fan_asks_cheaper("tienes algo más barato?")
    assert pc.fan_asks_cheaper("por 5 quiero lo mejor")
    assert pc.fan_asks_cheaper("no puedo permitirmelo")
    assert not pc.fan_asks_cheaper("me encantas")


def test_first_cheaper_ask_defends():
    # Fresh $0 with no bruise → default 2 defend hits
    plan = pc.evaluate(
        mem=_mem_expensive(last_offer=0, last_ppv_price=40.0, last_reject_at=None),
        fan_message="es muy caro",
        unpaid=True,
        ppv_status={"active": True, "price": 40, "message_uuid": "msg-expensive-1"},
    )
    # Bruised (last_offer 40) → need=1, so first ask still defends (hits=1)
    assert plan.phase == pc.PHASE_DEFEND
    assert plan.hits == 1


def test_bruised_zero_spender_concedes_on_second_ask():
    """$0 + prior $40 pitch → only 1 defend, then concede."""
    mem = _mem_expensive(
        price_defend_hits=1,
        last_reject_at="2026-07-22T12:00:00+00:00",
    )
    with patch("core.offer_selector.vault_catalog.load_items", return_value=_FAKE_VAULT):
        with patch("core.ppv_concede.vault_catalog.load_items", return_value=_FAKE_VAULT):
            plan = pc.evaluate(
                mem=mem,
                fan_message="algo más barato porfa",
                unpaid=True,
                ppv_status={
                    "active": True,
                    "price": 40,
                    "message_uuid": "msg-expensive-1",
                },
            )
    assert plan.phase == pc.PHASE_CONCEDE, plan.reason
    assert plan.cheap_offer is not None
    assert float(plan.cheap_offer["price"]) < 40


def test_buying_current_does_not_concede():
    plan = pc.evaluate(
        mem=_mem_expensive(price_defend_hits=5),
        fan_message="ok vale la compro",
        unpaid=True,
        ppv_status={"active": True, "price": 40, "message_uuid": "msg-expensive-1"},
    )
    assert plan.phase == pc.PHASE_NONE


def test_already_cheap_lock_skips_fsm():
    plan = pc.evaluate(
        mem=_mem_expensive(last_ppv_price=7.0, last_offer=7.0),
        fan_message="más barato",
        unpaid=True,
        ppv_status={"active": True, "price": 7, "message_uuid": "msg-cheap"},
    )
    assert plan.phase == pc.PHASE_NONE


def test_already_conceded_skips():
    plan = pc.evaluate(
        mem=_mem_expensive(price_concede_done=True, price_defend_hits=5),
        fan_message="más barato",
        unpaid=True,
        ppv_status={"active": True, "price": 40, "message_uuid": "msg-expensive-1"},
    )
    assert plan.phase == pc.PHASE_NONE


def test_pick_cheaper_undercuts():
    with patch("core.offer_selector.vault_catalog.load_items", return_value=_FAKE_VAULT):
        with patch("core.ppv_concede.vault_catalog.load_items", return_value=_FAKE_VAULT):
            offer = pc.pick_cheaper_offer(
                _mem_expensive(),
                current_price=40.0,
                fan_message="más barato",
            )
    assert offer is not None
    assert float(offer["price"]) < 15


def test_zero_spender_can_repost_cheap_already_marked_sent():
    """Expired L1/L2 pitches still in sent_media must be re-offerable on concede."""
    mem = _mem_expensive(
        sent_media_uuids=["c1", "c2", "c6"],
        last_ppv_media_uuid="c6",
        purchases=0,
        total_spent=0.0,
    )
    with patch("core.offer_selector.vault_catalog.load_items", return_value=_FAKE_VAULT):
        with patch("core.ppv_concede.vault_catalog.load_items", return_value=_FAKE_VAULT):
            offer = pc.pick_cheaper_offer(
                mem, current_price=40.0, fan_message="más barato"
            )
    assert offer is not None
    assert offer["media_uuid"] in ("c1", "c2")
    assert offer["media_uuid"] != "c6"


if __name__ == "__main__":
    test_asks_cheaper_detects_es()
    test_first_cheaper_ask_defends()
    test_second_cheaper_ask_still_defends_default()
    test_third_cheaper_ask_concedes()
    test_already_cheap_lock_skips_fsm()
    test_already_conceded_skips()
    test_pick_cheaper_undercuts()
    print("ok")
