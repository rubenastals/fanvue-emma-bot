"""
No-regression matrix for the SIMPLE live brain.

Covers the break-prone seams from the architecture audit:
unpaid/bluff, sell-commit, style bans on fallbacks, persona conflicts, budgets.
"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from core import prompt_core, prompt_layers, scheme_guard as sg, strategy_prompt
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


def test_persona_has_priority_ladder():
    persona = prompt_core.get_active_persona()
    assert "PRIORITY THIS TURN" in persona
    assert "SELL STATUS" in persona
    assert "ATTACHING" in persona
    # Examples must not teach banned openers
    assert "Emma: Mmm" not in persona
    assert "Never start messages with \"Ay…\", \"Mmm…\"" in persona
    # Technique engine is conditional
    assert "only when he is WARM or HOT" in persona
    assert "caro" in persona.lower() and "papi" in persona.lower()


def test_truth_state_cooling_skips_technique():
    ts = strategy_prompt.truth_state(cooling=True, lock_active=False)
    assert "COOLING" in ts
    assert "skip TECHNIQUE ENGINE" in ts


def test_fallbacks_obey_style_bans():
    samples = [
        sg.fallback_purchase_bluff(want_spanish=True, lock_still_active=True),
        sg.fallback_purchase_bluff(want_spanish=False, lock_still_active=False),
        sg.fallback_no_lock(want_spanish=True),
        sg.fallback_no_lock(want_spanish=False),
        sg.fallback_photos_only(want_spanish=True, real_price=7.0),
        sg.fallback_photos_only(want_spanish=False, real_price=None),
        sg.fallback_ghost_promise(want_spanish=True),
        sg.fallback_ghost_promise(want_spanish=False),
        sg.fallback_blame_own_it(want_spanish=True),
        sg.fallback_blame_own_it(want_spanish=False),
        sg.forced_paid_sell_line(price=9, want_spanish=True, label="tits"),
        sg.forced_paid_sell_line(price=9, want_spanish=False, label="ass"),
    ]
    for text in samples:
        assert sg.fallback_obeys_style_bans(text), text
        assert not text.lower().startswith("mmm")
        assert not text.lower().startswith("ay")


def test_sell_commit_alignment():
    assert sg.paid_offer_reply_aligned(
        "Solo para ti… esta foto mía, $8 — ábrela si de verdad quieres verme así"
    )
    assert not sg.paid_offer_reply_aligned(
        "mándame una foto tuya primero baby"
    )
    line = sg.forced_paid_sell_line(price=8, want_spanish=True, label="tits")
    assert sg.paid_offer_reply_aligned(line)
    assert "$8" in line or "$8" in line.replace(" ", "")


def test_unpaid_gate_pack():
    r = route(
        _mem(free_teases_sent=1),
        "hola",
        delivery_truth={"ppv_unpaid": True},
    )
    assert r.pack_id == "ppv_unpaid"
    assert r.facts.hard_pack == "ppv_unpaid"
    assert r.decision.allow_price is False


def test_prompt_layers_budget_and_order():
    messages, sizes = prompt_layers.build_system_layers(
        card_block="CLIENT CARD:\nname=Test",
        language_block="LANGUAGE: English",
        time_block="TIME: afternoon",
        name_block="ADDRESSING: baby",
        turn_blocks=[
            "TRUTH STATE THIS TURN:\n- NO lock",
            "SELL STATUS: NONE",
            "AUDIO THIS TURN: NO voice note",
        ],
        core_prompt="CORE PERSONA TEXT",
    )
    assert messages[0]["content"].startswith("CORE")
    assert any("CLIENT CARD" in m["content"] for m in messages)
    assert sizes["turn"] <= prompt_layers.BUDGET_TURN_SYSTEM
    assert sizes["core"] <= prompt_layers.BUDGET_CORE


def test_banned_fallback_open_detector():
    assert not sg.fallback_obeys_style_bans("Mmm… mentiroso 😏")
    assert not sg.fallback_obeys_style_bans("Ay bebé ven aquí")
    assert not sg.fallback_obeys_style_bans("hola papi qué tal")
    assert sg.fallback_obeys_style_bans("Mentiroso 😏 no la abriste")


if __name__ == "__main__":
    test_persona_has_priority_ladder()
    test_truth_state_cooling_skips_technique()
    test_fallbacks_obey_style_bans()
    test_sell_commit_alignment()
    test_unpaid_gate_pack()
    test_prompt_layers_budget_and_order()
    test_banned_fallback_open_detector()
    print("ok")
