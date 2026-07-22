"""Never accuse the fan of going quiet on an active reply turn."""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from core.reply_sanitize import _SILENCE_REPROACH, apply_post_draft
from core.technique_policy import score_move
from core import manipulation


def test_detects_live_silence_guilt():
    live = "because I actually opened up and now you're just... quiet? 💔"
    assert _SILENCE_REPROACH.search(live)


def test_detects_poof_theyre_gone_loop():
    live = (
        "most guys don't even make it this far tbh... "
        "I say something real and poof they're gone"
    )
    assert _SILENCE_REPROACH.search(live)


def test_sanitize_replaces_silence_guilt():
    assembled = SimpleNamespace(
        messages=[],
        decision=SimpleNamespace(mode="tease", pack_id="phase_pull"),
        pack_id="phase_pull",
        tech_name="GUILT TRIP + RECIPROCITY",
        phase_name="",
        want_spanish=False,
        fan_uuid=None,
        fan_handle="tester",
        fan_message="I was just joking... I get nervous around a girl as hot as you.",
        turns=[
            {
                "role": "user",
                "content": "I was just joking... I get nervous around a girl as hot as you.",
            }
        ],
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
    reply = "because I actually opened up and now you're just... quiet? 💔"
    out, _ = apply_post_draft(reply, assembled, call=MagicMock())
    assert "quiet" not in out.lower()
    assert _SILENCE_REPROACH.search(out) is None


def test_midchat_guilt_heavily_penalized():
    sig = {
        "msgs": 10,
        "zero_spender": True,
        "frees": 1,
        "buying": False,
        "horny": False,
        "price_push": False,
        "reject_step": 0,
        "soft_clarify": False,
        "cardish": False,
    }
    sc_guilt, why_g = score_move(
        "GUILT TRIP + RECIPROCITY",
        eff_pack="phase_pull",
        sig=sig,
        recent_fams=[],
        unpaid=False,
    )
    sc_loyal, why_l = score_move(
        "LOYALTY PROVE",
        eff_pack="phase_pull",
        sig=sig,
        recent_fams=[],
        unpaid=False,
    )
    assert "ban-midchat-abandonment-guilt" in why_g
    assert "free-given-reciprocity" in why_l
    assert sc_loyal > sc_guilt


def test_guilt_removed_from_phase_pull():
    names = [n for n, _ in manipulation._TECH_BY_PACK.get("phase_pull", [])]
    assert "GUILT TRIP + RECIPROCITY" not in names


def test_sanitize_replaces_poof_gone():
    assembled = SimpleNamespace(
        messages=[],
        decision=SimpleNamespace(mode="tease", pack_id="phase_pull"),
        pack_id="phase_pull",
        tech_name="LOYALTY PROVE",
        phase_name="",
        want_spanish=False,
        fan_uuid=None,
        fan_handle="tester",
        fan_message="haha you're funny",
        turns=[{"role": "user", "content": "haha you're funny"}],
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
    reply = (
        "most guys don't even make it this far tbh... "
        "I say something real and poof they're gone"
    )
    out, _ = apply_post_draft(reply, assembled, call=MagicMock())
    assert "poof" not in out.lower()
    assert "make it this far" not in out.lower()


if __name__ == "__main__":
    test_detects_live_silence_guilt()
    test_detects_poof_theyre_gone_loop()
    test_sanitize_replaces_silence_guilt()
    test_midchat_guilt_heavily_penalized()
    test_guilt_removed_from_phase_pull()
    test_sanitize_replaces_poof_gone()
    print("ok")
