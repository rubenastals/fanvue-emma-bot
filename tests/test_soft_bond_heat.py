"""No soft-therapist loops; flirting → heat moves."""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from core.reply_sanitize import _SOFT_BOND_STAMP, apply_post_draft
from core.technique_policy import choose_move, score_move


def test_detects_give_a_damn_stamp():
    text = (
        "just keep talking to me like this... not about photos or proving stuff\n"
        "it's nice having someone actually give a damn about what I'm saying"
    )
    assert _SOFT_BOND_STAMP.search(text)


def test_sanitize_replaces_with_heat():
    assembled = SimpleNamespace(
        messages=[],
        decision=SimpleNamespace(mode="tease", pack_id="phase_pull"),
        pack_id="phase_pull",
        tech_name="PAIN MAP VALIDATE",
        phase_name="",
        want_spanish=False,
        fan_uuid=None,
        fan_handle="tester",
        fan_message="How can I prove it to you, babe?",
        turns=[{"role": "user", "content": "How can I prove it to you, babe?"}],
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
        "just keep talking to me like this... not about photos or proving stuff\n"
        "it's nice having someone actually give a damn about what I'm saying"
    )
    out, _ = apply_post_draft(
        reply, assembled, call=lambda _m: "fuck… keep talking like that, you're getting me wet"
    )
    assert "give a damn" not in out.lower()
    assert "nice having someone" not in out.lower()


def test_flirt_prefers_heat_over_pain_map():
    sig = {
        "msgs": 12,
        "zero_spender": True,
        "frees": 1,
        "buying": False,
        "horny": False,
        "compliment": True,
        "prove_ask": True,
        "venting": False,
        "flirting": True,
        "price_push": False,
        "reject_step": 0,
        "soft_clarify": False,
        "cardish": True,
        "status": "warm",
    }
    sc_hot, why_h = score_move(
        "HOT FLIRT", eff_pack="phase_pull", sig=sig, recent_fams=[]
    )
    sc_pain, why_p = score_move(
        "PAIN MAP VALIDATE", eff_pack="phase_pull", sig=sig, recent_fams=[]
    )
    assert "flirt-heat" in why_h or "hot-flirt-priority" in why_h
    assert "pain-map-not-flirting" in why_p
    assert sc_hot > sc_pain


def test_choose_heat_on_prove_ask():
    mem = {
        "messages": 14,
        "status": "warm",
        "total_spent": 0,
        "purchases": 0,
        "free_teases_sent": 1,
        "name": "Juan",
    }
    move = choose_move(
        "phase_pull",
        fan_uuid="test-heat",
        msgs=14,
        mem=mem,
        fan_message="How can I prove it to you, babe?",
        unpaid=False,
    )
    assert move is not None
    assert move.name in {
        "HOT FLIRT",
        "HEAT",
        "ASK HIS PHOTO",
        "LOVE BOMBING",
        "MICRO COMMITMENT",
    }
    assert "PAIN MAP" not in move.name


if __name__ == "__main__":
    test_detects_give_a_damn_stamp()
    test_sanitize_replaces_with_heat()
    test_flirt_prefers_heat_over_pain_map()
    test_choose_heat_on_prove_ask()
    print("ok")
