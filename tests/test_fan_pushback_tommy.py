"""Tommy-thread regressions — vision hallucination, AI complaint, flattery skeptic."""
from __future__ import annotations

from core import technique_playbook as pb
from core.fan_pushback import (
    fan_has_pushback,
    is_ai_complaint,
    is_flattery_skeptic,
    is_vision_correction,
    pick_pushback_fallback,
    reply_invents_sunglasses,
)
from core.technique_policy import _fan_signals
from core.turn_policy import decide_turn


def test_ai_complaint_detected():
    assert is_ai_complaint("Stop using the AI feature")
    assert is_ai_complaint("I want to talk to you, not the automated chat")
    assert fan_has_pushback("Stop using the AI feature")


def test_flattery_skeptic_detected():
    assert is_flattery_skeptic("That's what you tell all the boys lol")
    assert fan_has_pushback("That's what you tell all the boys lol")


def test_vision_correction_detected():
    assert is_vision_correction("Girl, neither pic has me in sunglasses?")
    assert fan_has_pushback("Girl, neither pic has me in sunglasses?")


def test_sunglasses_invented_when_vision_has_none():
    vision = "A man with gray hair and stubble, mountains behind him. CLASS: fan_male_sfw"
    reply = "send me one without the sunglasses babe"
    assert reply_invents_sunglasses(reply, vision)


def test_sunglasses_ok_when_vision_mentions_them():
    vision = "Man wearing sunglasses and a cap. CLASS: fan_male_sfw"
    reply = "take those sunglasses off for me"
    assert not reply_invents_sunglasses(reply, vision)


def test_playbook_skips_ask_pic_after_fan_photo():
    sig = {
        "msgs": 6,
        "fan_sent_photo": True,
        "compliment": True,
        "horny": False,
        "flirting": True,
        "buying": False,
        "reject_step": 0,
    }
    move, why = pb.pick_playbook_move(
        pack_id="phase_pull",
        sig=sig,
        unpaid=False,
        recent_techs=["ASK PIC", "BOND"],
    )
    assert move.name != "ASK PIC"
    assert why.startswith("post-photo")


def test_playbook_pushback_is_bond():
    sig = _fan_signals({}, "Stop using the AI feature")
    move, why = pb.pick_playbook_move(
        pack_id="phase_pull",
        sig=sig,
        unpaid=False,
        recent_techs=[],
    )
    assert move.name == "BOND"
    assert why == "fan-pushback-bond"


def test_turn_policy_one_bubble_on_pushback():
    mem = {"messages": 8, "status": "warm", "total_spent": 0}
    d = decide_turn(mem, "That's what you tell all the boys lol")
    assert d.max_bubbles == 1
    assert "pushback" in d.reason


def test_pushback_fallback_not_empty():
    line = pick_pushback_fallback("Stop using the AI feature")
    assert line and len(line) > 10
