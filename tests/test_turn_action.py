"""R5: one TurnAction resolver — priority before LLM."""
from __future__ import annotations

import sys
import uuid
from pathlib import Path
from types import SimpleNamespace

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from core import fan_memory, voice_notes as vn
from core.turn_action import (
    ACTION_ATTACH_FREE,
    ACTION_ATTACH_PPV,
    ACTION_COMFORT,
    ACTION_FLIRT,
    ACTION_SEND_VOICE,
    action_prompt_line,
    classify_turn_action,
    plan_turn_action,
    wants_comfort,
)
from core.turn_policy import MODE_CHILL, MODE_SOFT_SELL


def test_priority_voice_beats_paid_offer():
    offer = {"price": 40, "level": 2, "label": "tits", "media_uuid": "x"}
    ta = classify_turn_action(
        voice_ok=True,
        voice_why="FSM open_voice → send",
        blocks_photo=True,
        offer=offer,
        comfort=False,
    )
    assert ta.action == ACTION_SEND_VOICE
    assert ta.offer is None
    assert ta.blocks_photo
    assert ta.voice_will_send


def test_priority_comfort_beats_sell():
    offer = {"price": 9, "level": 1, "label": "ass", "media_uuid": "y"}
    ta = classify_turn_action(
        voice_ok=False,
        blocks_photo=False,
        offer=offer,
        comfort=True,
    )
    assert ta.action == ACTION_COMFORT
    assert ta.offer is None
    assert ta.blocks_photo


def test_priority_unpaid_no_attach():
    offer = {"price": 9, "level": 1, "label": "ass", "media_uuid": "y"}
    ta = classify_turn_action(
        voice_ok=False,
        unpaid=True,
        offer=offer,
        comfort=False,
    )
    assert ta.action == ACTION_FLIRT
    assert ta.offer is None
    assert "unpaid" in ta.reason.lower()


def test_classify_paid_and_free():
    paid = classify_turn_action(
        voice_ok=False,
        offer={"price": 12, "level": 2, "label": "x", "media_uuid": "m"},
    )
    assert paid.action == ACTION_ATTACH_PPV
    assert paid.attaches_photo

    free = classify_turn_action(
        voice_ok=False,
        offer={"price": 0, "level": 0, "label": "tease", "media_uuid": "m"},
    )
    assert free.action == ACTION_ATTACH_FREE

    flirt = classify_turn_action(voice_ok=False, offer=None)
    assert flirt.action == ACTION_FLIRT


def test_voice_debt_blocks_photo_without_send():
    ta = classify_turn_action(
        voice_ok=False,
        voice_why="photo-blocked (debt)",
        blocks_photo=True,
        offer={"price": 40, "level": 2, "label": "t", "media_uuid": "m"},
    )
    assert ta.action == ACTION_FLIRT
    assert ta.blocks_photo
    assert ta.offer is None


def test_wants_comfort_heavy_vent_and_chill():
    assert wants_comfort("estoy muy mal quiero llorar")
    assert wants_comfort(
        "hola",
        decision=SimpleNamespace(mode=MODE_CHILL),
    )
    assert not wants_comfort(
        "quiero ver tus tetas",
        decision=SimpleNamespace(mode=MODE_SOFT_SELL),
    )
    facts = SimpleNamespace(heavy_vent=True)
    assert wants_comfort("ok", facts=facts)


def test_action_prompt_lines():
    comfort = classify_turn_action(voice_ok=False, comfort=True)
    line = action_prompt_line(comfort)
    assert "comfort" in line.lower()
    assert "ACTION" in line

    ppv = classify_turn_action(
        voice_ok=False,
        offer={"price": 40, "level": 2, "label": "t", "media_uuid": "m"},
    )
    assert "$40" in action_prompt_line(ppv)

    voice = classify_turn_action(voice_ok=True, voice_why="ask")
    vline = action_prompt_line(
        voice, mem={"open_commitment": {"type": "voice", "hits": 2}}
    )
    assert "pídemelo" in vline.lower() or "COMMITMENT" in vline


def test_plan_turn_action_voice_over_sell():
    fid = f"test-fan-{uuid.uuid4().hex[:12]}"
    fan_memory.set_commitment(
        fid, ctype="voice", source="prior", fan_handle="tester", bump=False
    )
    mem = fan_memory.get(fid)
    history = [
        {"role": "assistant", "content": "pídemelo bien"},
        {"role": "user", "content": "por favor"},
    ]
    orig = vn._enabled
    vn._enabled = lambda: True  # type: ignore
    try:
        ta = plan_turn_action(
            fan_uuid=fid,
            fan_handle="tester",
            fan_message="por favor",
            mem=mem,
            decision=SimpleNamespace(mode="soft_sell", allow_price=True),
            pack_id="phase_close",
            unpaid=False,
            history_turns=history,
            want_sell=True,
            want_free=False,
            facts=None,
        )
        assert ta.action == ACTION_SEND_VOICE, ta.reason
        assert ta.offer is None
        assert ta.blocks_photo
    finally:
        vn._enabled = orig  # type: ignore
        fan_memory.clear_commitment(fid, ctype="voice", fan_handle="tester")


def test_plan_turn_action_comfort_skips_sell():
    fid = f"test-fan-{uuid.uuid4().hex[:12]}"
    mem = fan_memory.get(fid) or {}
    orig = vn._enabled
    vn._enabled = lambda: True  # type: ignore
    try:
        ta = plan_turn_action(
            fan_uuid=fid,
            fan_handle="tester",
            fan_message="se me murió mi perro estoy muy mal",
            mem=mem,
            decision=SimpleNamespace(mode="soft_sell", allow_price=True),
            pack_id="phase_close",
            unpaid=False,
            history_turns=[],
            want_sell=True,
            want_free=False,
            facts=SimpleNamespace(heavy_vent=True),
        )
        assert ta.action == ACTION_COMFORT, ta.reason
        assert ta.offer is None
    finally:
        vn._enabled = orig  # type: ignore


if __name__ == "__main__":
    test_priority_voice_beats_paid_offer()
    test_priority_comfort_beats_sell()
    test_priority_unpaid_no_attach()
    test_classify_paid_and_free()
    test_voice_debt_blocks_photo_without_send()
    test_wants_comfort_heavy_vent_and_chill()
    test_action_prompt_lines()
    test_plan_turn_action_voice_over_sell()
    test_plan_turn_action_comfort_skips_sell()
    print("ok")
