"""Regression for sim-learn loop fixes (lang / purchase reward / crisis timing)."""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from core import language, scheme_guard as sg
from core.reply_sanitize import apply_post_draft
from core.technique_policy import score_move


def test_english_me_no_not_mixed():
    assert not language.is_mixed_or_wrong(
        "you got me smiling and i want you so bad",
        want_spanish=False,
    )
    assert language.is_mixed_or_wrong(
        "Ay mira bebé esto está muy caliente para ti",
        want_spanish=False,
    )


def test_just_purchased_fallback():
    line = sg.fallback_just_purchased(want_spanish=False)
    assert "yours" in line.lower() or "babe" in line.lower()
    assert "don't have anything sitting" not in line.lower()


def test_invented_lock_after_purchase_rewards():
    assembled = SimpleNamespace(
        messages=[{"role": "user", "content": "unlocked"}],
        decision=SimpleNamespace(mode="tease", pack_id="reward_purchase"),
        pack_id="reward_purchase",
        tech_name="LOVE BOMBING (REWARD)",
        phase_name="reward",
        want_spanish=False,
        fan_uuid=None,
        fan_handle="sim",
        fan_message="i unlocked it babe",
        usable_name="",
        name_confirmed=False,
        name_max_uses=0,
        turns=[{"role": "user", "content": "i unlocked it babe"}],
        offer=None,
        ppv_status={"active": False, "purchased": True},
        delivery_truth={"ppv_unpaid": False},
        voice_will_send=False,
        lock_active=False,
        no_lock=True,
        status_active=False,
        unpaid_gate=False,
        never_bought=False,
        fan_saw_bluff=False,
        ghost_free_ban=False,
        turn_action=None,
    )
    out, _ = apply_post_draft(
        "unlock that photo above baby it's waiting for you",
        assembled,
        call=lambda _m: "x",
    )
    assert "don't have anything sitting" not in out.lower()
    assert "yours" in out.lower() or "babe" in out.lower()


def test_fake_emergency_penalized_early_unpaid():
    sig = {
        "msgs": 5,
        "reject_step": 0,
        "price_push": True,
        "horny": False,
        "buying": False,
        "flirting": False,
        "venting": False,
        "cardish": False,
        "prove_ask": False,
        "soft_clarify": False,
        "shy_short": False,
        "zero_spender": True,
        "status": "warm",
        "spent": 0,
        "purchases": 0,
    }
    score_crisis, why = score_move(
        "FAKE EMERGENCY",
        eff_pack="ppv_unpaid",
        sig=sig,
        recent_fams=[],
        unpaid=True,
        no_lock=False,
    )
    score_scar, why2 = score_move(
        "SCARCITY + FOMO",
        eff_pack="ppv_unpaid",
        sig=sig,
        recent_fams=[],
        unpaid=True,
        no_lock=False,
    )
    assert score_scar > score_crisis, (score_scar, why2, score_crisis, why)
    assert "crisis-banned" in why or "unpaid-crisis-banned" in why


def test_ppv_unpaid_catalog_no_guilt_crisis():
    from core import manipulation

    names = {n for n, _ in manipulation._TECH_BY_PACK["ppv_unpaid"]}
    assert "FAKE EMERGENCY" not in names
    assert not any("GUILT" in n for n in names)
    assert "SCARCITY + FOMO" in names


def test_rival_banned_after_purchase():
    sig = {
        "msgs": 20,
        "reject_step": 2,
        "price_push": False,
        "horny": False,
        "buying": False,
        "flirting": False,
        "venting": False,
        "cardish": True,
        "prove_ask": False,
        "soft_clarify": False,
        "shy_short": False,
        "zero_spender": False,
        "status": "spender",
        "spent": 20,
        "purchases": 1,
    }
    score, why = score_move(
        "RIVAL TIP FOMO",
        eff_pack="ppv_unpaid",
        sig=sig,
        recent_fams=[],
        unpaid=True,
        no_lock=False,
    )
    assert score < 0 or "rival-after-purchase-banned" in why


if __name__ == "__main__":
    test_english_me_no_not_mixed()
    test_just_purchased_fallback()
    test_invented_lock_after_purchase_rewards()
    test_fake_emergency_penalized_early_unpaid()
    test_ppv_unpaid_catalog_no_guilt_crisis()
    test_rival_banned_after_purchase()
    print("ok")
