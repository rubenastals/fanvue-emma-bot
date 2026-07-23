"""Tests for new-account onboarding gates."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from core.account_onboard import (
    classify_membership,
    evaluate_welcome,
    repesca_appropriate,
    thread_is_live,
)

CREATOR = "creator-uuid"
FAN = "fan-uuid"
NOW = datetime(2026, 7, 23, 14, 0, tzinfo=timezone.utc)


def _msg(sender: str, text: str, minutes_ago: int) -> dict:
    ts = NOW - timedelta(minutes=minutes_ago)
    return {
        "sender": {"uuid": sender},
        "text": text,
        "createdAt": ts.isoformat(),
    }


def test_classify_active_subscriber():
    assert (
        classify_membership({"status": "subscriber"}, in_active_sub_list=True)
        == "active_sub"
    )


def test_classify_expired_not_in_list():
    assert (
        classify_membership({"status": "expired"}, in_active_sub_list=False)
        == "expired"
    )


def test_classify_follower_skipped_for_welcome():
    assert (
        classify_membership({"status": "follower"}, in_active_sub_list=False)
        == "follower"
    )


def test_thread_live_when_fan_spoke_last():
    messages = [_msg(FAN, "hey", 2)]
    assert thread_is_live(messages, FAN, CREATOR, now=NOW)


def test_thread_live_when_fan_recent():
    messages = [
        _msg(CREATOR, "hi", 1),
        _msg(FAN, "hey", 5),
    ]
    assert thread_is_live(messages, FAN, CREATOR, now=NOW)


def test_welcome_active_unopened():
    decision = evaluate_welcome(
        fan_uuid=FAN,
        handle="fan1",
        creator_uuid=CREATOR,
        messages=[],
        mem={},
        insights={"status": "subscriber"},
        in_active_sub_list=True,
        source="subscriber",
    )
    assert decision.action == "welcome"
    assert decision.membership == "active_sub"
    assert decision.text


def test_welcome_skip_expired():
    decision = evaluate_welcome(
        fan_uuid=FAN,
        handle="fan1",
        creator_uuid=CREATOR,
        messages=[],
        mem={},
        insights={"status": "expired"},
        in_active_sub_list=False,
        source="subscriber",
    )
    assert decision.action == "skip"
    assert decision.reason == "expired_no_welcome"


def test_welcome_skip_when_fan_already_wrote():
    messages = [_msg(FAN, "wait", 3)]
    decision = evaluate_welcome(
        fan_uuid=FAN,
        handle="fan1",
        creator_uuid=CREATOR,
        messages=messages,
        mem={},
        insights={"status": "subscriber"},
        in_active_sub_list=True,
        source="chat",
    )
    assert decision.action == "skip"
    assert decision.reason == "fan_already_chatted"


def test_repesca_skip_negative_fan():
    messages = [
        _msg(CREATOR, "hey", 20),
        _msg(FAN, "you are a fake bot", 25),
    ]
    ok, reason = repesca_appropriate(messages, FAN, CREATOR, {"messages": 3}, now=NOW)
    assert not ok
    assert reason == "fan_negative"


def test_repesca_ok_after_creator_last():
    messages = [
        _msg(CREATOR, "so what do you think?", 90),
        _msg(FAN, "idk", 120),
    ]
    ok, reason = repesca_appropriate(messages, FAN, CREATOR, {"messages": 5}, now=NOW)
    assert ok
    assert reason == "ok"


def test_repesca_skip_live_thread():
    messages = [
        _msg(CREATOR, "ok", 2),
        _msg(FAN, "wait", 5),
    ]
    ok, reason = repesca_appropriate(messages, FAN, CREATOR, {"messages": 4}, now=NOW)
    assert not ok
    assert reason == "thread_live"
