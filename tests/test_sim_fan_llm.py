"""Unit tests for LLM-fan helpers (no API)."""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from core.sim_fan_llm import (
    FAN_ARCHETYPES,
    _parse_fan_json,
    list_archetypes,
    maybe_attach_offer,
)
from core.sim_score import _parse as parse_score


def test_archetypes_exist():
    assert "horny_buyer" in list_archetypes()
    assert len(FAN_ARCHETYPES) >= 4


def test_parse_fan_json():
    raw = 'yeah\n{"text": "send it", "action": "unlock", "reason": "hot"}\n'
    p = _parse_fan_json(raw)
    assert p["action"] == "unlock"
    assert p["text"] == "send it"


def test_maybe_attach_paid_when_asking():
    arch = FAN_ARCHETYPES["horny_buyer"]
    offer = maybe_attach_offer(
        turn_index=3,
        fan_text="send me a private pic please",
        pending_lock=None,
        already_free=False,
        already_paid=False,
        archetype=arch,
    )
    assert offer and float(offer["price"]) > 0


def test_no_stack_second_lock():
    arch = FAN_ARCHETYPES["horny_buyer"]
    offer = maybe_attach_offer(
        turn_index=4,
        fan_text="another one",
        pending_lock={"price": 8, "label": "x"},
        already_free=False,
        already_paid=True,
        archetype=arch,
    )
    assert offer is None


def test_score_parse():
    raw = '{"hook": 7, "human": 8, "sell": 6, "would_unlock": true, "would_return": true, "fan_temperature": "heating", "verdict": "ok", "killers": []}'
    p = parse_score(raw)
    assert p["hook"] == 7


if __name__ == "__main__":
    test_archetypes_exist()
    test_parse_fan_json()
    test_maybe_attach_paid_when_asking()
    test_no_stack_second_lock()
    test_score_parse()
    print("ok")
