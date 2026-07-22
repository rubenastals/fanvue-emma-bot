"""$0 spenders open cheap; $40 only on explicit hardcore ask."""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from core import offer_selector as osel


_FAKE_VAULT = [
    {"media_uuid": "u1", "level": 1, "price": 4.0, "label": "Lingerie tease", "score": 5},
    {"media_uuid": "u2", "level": 2, "price": 7.0, "label": "Topless smile", "score": 6},
    {"media_uuid": "u3", "level": 3, "price": 10.0, "label": "Soft nude", "score": 7},
    {"media_uuid": "u4", "level": 4, "price": 18.0, "label": "Open nude", "score": 8},
    {"media_uuid": "u5", "level": 5, "price": 27.0, "label": "Fingers", "score": 9},
    {"media_uuid": "u6", "level": 6, "price": 40.0, "label": "Extreme labia spread", "score": 10},
    {"media_uuid": "u7", "level": 7, "price": 60.0, "label": "Hardcore toy", "score": 11},
]


def _zero_mem(**extra):
    m = {
        "purchases": 0,
        "total_spent": 0.0,
        "last_offer": 0,
        "last_offer_level": 0,
        "last_ppv_price": 0,
        "sent_media_uuids": [],
    }
    m.update(extra)
    return m


def test_zero_spend_candidates_are_cheap():
    with patch("core.offer_selector.vault_catalog.load_items", return_value=_FAKE_VAULT):
        cands = osel.candidate_offers(_zero_mem(), "quiero ver otra cosa 😉")
    assert cands
    assert all(int(i["level"]) <= 2 for i in cands)
    assert all(float(i["price"]) < 15 for i in cands)
    assert all(float(i["price"]) < 40 for i in cands)


def test_zero_spend_after_40_reject_stays_cheap():
    mem = _zero_mem(
        last_offer=40.0,
        last_offer_level=6,
        last_ppv_price=40.0,
        last_reject_at=datetime.now(timezone.utc).isoformat(),
    )
    with patch("core.offer_selector.vault_catalog.load_items", return_value=_FAKE_VAULT):
        cands = osel.candidate_offers(mem, "vale enséñamela")
    assert cands
    assert all(float(i["price"]) < 40 for i in cands)
    assert all(int(i["level"]) <= 2 for i in cands)


def test_explicit_hardcore_allows_l6():
    with patch("core.offer_selector.vault_catalog.load_items", return_value=_FAKE_VAULT):
        cands = osel.candidate_offers(
            _zero_mem(),
            "quiero lo más guarro que tengas",
        )
    assert cands
    assert any(int(i["level"]) >= 5 for i in cands)
    assert any(float(i["price"]) >= 40 for i in cands)


def test_emma_promise_alone_does_not_open_40_for_zero_spender():
    """Emma saying 'la más guarra' must not yank a $0 fan to L6 on 'ya sabes'."""
    history = [
        {
            "role": "assistant",
            "content": "la más guarra, baby... tocándome pensando en tu polla",
        }
    ]
    with patch("core.offer_selector.vault_catalog.load_items", return_value=_FAKE_VAULT):
        cands = osel.candidate_offers(
            _zero_mem(last_offer=40.0, last_ppv_price=40.0),
            "ya sabes.. no te hagas la sorprendida",
            history_turns=history,
        )
    assert cands
    assert all(float(i["price"]) < 15 for i in cands)


def test_choose_offer_ceiling_blocks_40_on_zero():
    with patch("core.offer_selector.vault_catalog.load_items", return_value=_FAKE_VAULT):
        # Force AI off → fallback + ceiling
        from config import config

        prev = getattr(config, "OFFER_SELECTOR_AI", True)
        config.OFFER_SELECTOR_AI = False
        try:
            choice = osel.choose_offer(
                _zero_mem(),
                "enséñamela por favor",
                history_turns=[],
            )
        finally:
            config.OFFER_SELECTOR_AI = prev
    assert choice.sell_now
    assert choice.offer is not None
    assert float(choice.offer["price"]) < 15
    assert int(choice.offer["level"]) <= 2


if __name__ == "__main__":
    test_zero_spend_candidates_are_cheap()
    test_zero_spend_after_40_reject_stays_cheap()
    test_explicit_hardcore_allows_l6()
    test_emma_promise_alone_does_not_open_40_for_zero_spender()
    test_choose_offer_ceiling_blocks_40_on_zero()
    print("ok")
