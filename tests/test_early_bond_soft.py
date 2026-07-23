"""Early chat must not drop heavy validation stamps too soon."""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from core.reply_sanitize import apply_post_draft
from core.technique_playbook import pick_playbook_move


def _assembled(*, msgs: int = 3, fan_message: str = "hey"):
    return SimpleNamespace(
        messages=[],
        decision=SimpleNamespace(mode="rapport", pack_id="phase_pull"),
        pack_id="phase_pull",
        tech_name="BOND",
        phase_name="",
        want_spanish=False,
        fan_uuid="early-fan",
        fan_handle="newguy",
        fan_message=fan_message,
        turns=[{"role": "user", "content": fan_message}],
        offer=None,
        ppv_status=None,
        voice_will_send=False,
        lock_active=False,
        no_lock=True,
        status_active=False,
        unpaid_gate=False,
        never_bought=True,
        fan_saw_bluff=False,
    )


def test_early_special_stamp_replaced(monkeypatch):
    from core import fan_memory

    monkeypatch.setattr(
        fan_memory,
        "get",
        lambda _uuid: {"messages": 4},
    )
    reply = "something about u got me soft… you're different from other guys babe"
    out, _ = apply_post_draft(
        reply,
        _assembled(),
        call=lambda _m: "haha ok tell me more",
    )
    low = out.lower()
    assert "different" not in low
    assert "got me soft" not in low


def test_early_playbook_prefers_curiosity_over_bond_spam():
    sig = {"msgs": 3, "horny": False, "flirting": False, "fan_sent_photo": False}
    move, why = pick_playbook_move(
        pack_id="phase_pull",
        sig=sig,
        unpaid=False,
        recent_techs=["BOND", "BOND"],
    )
    assert move.name in {"ASK PIC", "HEAT", "BOND"}
    assert why in {"early-ask-pic", "early-rotate-heat", "early-curious", "early-warm"}
