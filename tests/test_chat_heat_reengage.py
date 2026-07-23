"""Chat heat score + re-engagement timing."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from core import reengagement
from core.chat_heat import chat_heat_score, heat_label, is_hot_score


def _mem(spent=0, status="warm", **extra):
    base = {"total_spent": spent, "status": status, "messages": 10}
    base.update(extra)
    return base


def _msgs(fan_uuid, texts):
    return [
        {
            "sender": {"uuid": fan_uuid},
            "text": t,
            "sentAt": datetime.now(timezone.utc).isoformat(),
        }
        for t in texts
    ]


def test_heat_score_high_on_flirty_thread():
    fan = "fan-1"
    mem = _mem()
    msgs = _msgs(fan, ["you're so hot", "hard for you babe", "fuck"])
    score = chat_heat_score(msgs, fan, mem, is_read=True)
    assert score >= 40
    assert heat_label(score) in ("HOT", "BLAZING", "WARM")


def test_hot_seen_nudge_faster_than_cold():
    now = datetime.now(timezone.utc)
    mem = _mem(
        last_seen_by_fan_at=(now - timedelta(minutes=5)).isoformat(),
    )
    silence = timedelta(minutes=5)
    step = reengagement._nudge_step_for_silence(
        silence,
        mem,
        heat_score=55,
        is_read=True,
        now=now,
    )
    assert step == 1

    step_cold = reengagement._nudge_step_for_silence(
        silence,
        {"nudge_episode_count": 0},
        heat_score=10,
        is_read=False,
        now=now,
    )
    assert step_cold is None


def test_reaction_fast_path():
    now = datetime.now(timezone.utc)
    mem = _mem(
        last_fan_reaction_at=(now - timedelta(minutes=4)).isoformat(),
        last_fan_reaction_emoji="❤️",
    )
    step = reengagement._nudge_step_for_silence(
        timedelta(minutes=5),
        mem,
        heat_score=30,
        is_read=True,
        now=now,
    )
    assert step == 1


def test_webhook_reaction_parse():
    from core.webhook_events import parse_message_reaction

    data = {
        "type": "creator.message.reaction",
        "data": {
            "emoji": "❤️",
            "message_uuid": "msg-1",
            "actor": {"uuid": "fan-abc"},
            "creator": {"uuid": "creator-xyz"},
        },
    }
    fan, emoji, mid = parse_message_reaction(data)
    assert fan == "fan-abc"
    assert emoji == "❤️"
    assert mid == "msg-1"
