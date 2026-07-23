"""Farewell / conversation-close detection — no re-engage after goodbye."""
from __future__ import annotations

from core.farewell import (
    conversation_closed,
    fan_closed_in_messages,
    fan_reopened_conversation,
    fan_text_is_farewell,
    fan_text_is_robot_complaint,
    mark_conversation_closed,
    pause_reengage_until_fan_writes,
    reengage_paused,
)


def test_tommy_work_farewell_detected():
    assert fan_text_is_farewell("Well babe. Have to get ready for work")


def test_have_to_go_variants():
    assert fan_text_is_farewell("gotta go babe talk later")
    assert fan_text_is_farewell("I need to run, ttyl")


def test_flirt_not_farewell():
    assert not fan_text_is_farewell("I keep thinking about your hot ass honestly")


def test_closed_blocks_reengage_after_soft_reply():
    fan = "fan-uuid"
    creator = "creator-uuid"
    messages = [
        {
            "sender": {"uuid": creator},
            "text": "come find me when you're free, baby... I'll be right here",
        },
        {
            "sender": {"uuid": fan},
            "text": "Well babe. Have to get ready for work",
        },
        {
            "sender": {"uuid": creator},
            "text": "come find me when you're free, baby...",
        },
    ]
    assert conversation_closed(messages, fan, creator, {})


def test_question_mark_does_not_reopen():
    assert not fan_reopened_conversation("?")
    assert not fan_reopened_conversation("...")
    assert fan_reopened_conversation("hey sorry about earlier")


def test_robot_complaint_detected():
    assert fan_text_is_robot_complaint("Babe turn off the robot")
    assert fan_text_is_robot_complaint("Stop using the AI feature")


def test_reengage_paused_blocks_closed():
    fan = "fan-uuid"
    creator = "creator-uuid"
    mem = {"reengage_paused_until_fan_writes": True}
    assert reengage_paused(mem)
    assert conversation_closed([], fan, creator, mem)


def test_pause_until_fan_writes_persists():
    fan = "test-pause-fan"
    pause_reengage_until_fan_writes(fan, reason="turn off the robot")
    from core import fan_memory

    mem = fan_memory.get(fan) or {}
    assert mem.get("reengage_paused_until_fan_writes")


def test_mark_and_persist_closed():
    from core.farewell import clear_conversation_closed

    fan = "test-farewell-fan"
    mark_conversation_closed(fan, reason="have to get ready for work")
    from core import fan_memory

    mem = fan_memory.get(fan) or {}
    assert mem.get("conversation_closed_at")
    clear_conversation_closed(fan)
    mem2 = fan_memory.get(fan) or {}
    assert not (mem2.get("conversation_closed_at") or "").strip()
