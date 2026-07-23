"""Fan boundary — no pic pressure / PPV when upset or private."""
from __future__ import annotations

from core.fan_pushback import (
    is_fan_boundary,
    is_photo_refusal,
    thread_in_boundary_mode,
)
from core.technique_playbook import pick_playbook_move


def test_stop_asking_pictures_is_boundary():
    t = "being pushy like that could be reported, please stop asking me for pictures of"
    assert is_photo_refusal(t)
    assert is_fan_boundary(t)


def test_pushy_reported_is_boundary():
    assert is_fan_boundary("you're being too pushy")


def test_boundary_blocks_ask_pic_move():
    sig = {
        "msgs": 5,
        "fan_boundary": True,
        "photo_refusal": True,
        "horny": True,
        "flirting": True,
    }
    move, why = pick_playbook_move(
        pack_id="phase_pull", sig=sig, unpaid=True, recent_techs=[]
    )
    assert move.name == "SOFT EXIT"
    assert "boundary" in why


def test_boundary_persists_in_thread():
    turns = [
        {"role": "user", "content": "sorry i like to keep myself private"},
        {"role": "assistant", "content": "okay fair"},
        {"role": "user", "content": "okay 🙂"},
    ]
    assert thread_in_boundary_mode("okay 🙂", turns, {})
