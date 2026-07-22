"""No cold PPV drops — Juan-style 'fotos para mi?' / emotional unpaid."""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from core.intent_router import route
from core.offer_selector import choose_offer, _CLARIFY_NO_SELL


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


def test_fotos_para_mi_is_clarify_not_buy():
    assert _CLARIFY_NO_SELL.search("pero fotos para mi?")
    r = route(_mem(), "pero fotos para mi?", delivery_truth={"ppv_unpaid": False})
    assert r.facts.buying is False
    assert r.decision.allow_price is False
    assert r.pack_id in ("phase_pull", "phase_spiral", "ask_free_first")


def test_warm_msgs_alone_does_not_allow_price():
    r = route(_mem(), "jaja ok", delivery_truth={"ppv_unpaid": False})
    assert r.decision.allow_price is False


def test_real_ask_still_buys():
    r = route(_mem(), "mandame fotos ya", delivery_truth={"ppv_unpaid": False})
    assert r.facts.buying is True
    assert r.decision.allow_price is True


def test_ensename_typo_and_tetitas_count():
    r = route(
        _mem(),
        "a ver, eseñame esas tetitas",
        delivery_truth={"ppv_unpaid": False},
    )
    assert r.facts.buying or r.facts.horny
    assert r.decision.allow_price is True


def test_unpaid_emotional_reconnect():
    r = route(
        _mem(),
        "prefieres hablar antes? te molestó mucho tu mama?",
        delivery_truth={"ppv_unpaid": True},
    )
    assert r.pack_id == "phase_pull"
    assert r.decision.allow_ppv_talk is False


def test_unpaid_bare_si_reconnect():
    r = route(_mem(), "si", delivery_truth={"ppv_unpaid": True})
    assert r.pack_id == "phase_pull"
    assert r.decision.allow_ppv_talk is False


def test_choose_offer_blocks_clarify():
    # Empty catalog path may return exhausted — still must not sell
    choice = choose_offer(
        _mem(),
        "pero fotos para mi?",
        history_turns=[
            {"role": "assistant", "content": "tengo que irme a grabar"},
            {"role": "user", "content": "pero fotos para mi?"},
        ],
    )
    assert choice.sell_now is False
