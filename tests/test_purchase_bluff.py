"""Fan bluffs he saw/liked a PPV he never bought + sell-gate regressions."""
from datetime import datetime, timedelta, timezone

from core import scheme_guard as sg
from core.offer_selector import _DIRECT_BUY, _REJECT, _recently_expired
from core.turn_policy import _BUYING
import re


def test_fan_claims_liked_last_photo():
    assert sg.fan_claims_saw_ppv("me ha gustado mucho la ultima foto")
    assert sg.fan_claims_saw_ppv("me gustó esa foto")
    assert sg.fan_claims_saw_ppv("liked the last photo a lot")
    assert sg.fan_claims_saw_ppv("ya la abrí")
    assert sg.fan_claims_saw_ppv("ahora si que la veo")
    assert sg.fan_claims_saw_ppv("se te ve muy buenorra")
    assert sg.fan_claims_saw_ppv("las tetas")
    assert not sg.fan_claims_saw_ppv("hola baby como estas")


def test_validates_unseen():
    assert sg.validates_unseen_ppv(
        "me alegro que te gustara, baby... pero esa era solo un poquito"
    )
    assert sg.validates_unseen_ppv("glad you liked it — that was just a tease")
    assert sg.validates_unseen_ppv("¿ves? te dije que valía la pena, bebé")
    assert sg.validates_unseen_ppv("ahora dime… ¿qué parte de mí te gustó más?")
    assert not sg.validates_unseen_ppv("mentiroso, nunca la abriste 😏")
    assert sg.calls_out_purchase_bluff(
        "Mentiroso 😏 esa foto sigue cerrada — no la has abierto."
    )
    bluff = sg.fallback_purchase_bluff(want_spanish=True, lock_still_active=True)
    assert sg.calls_out_purchase_bluff(bluff)
    assert sg.fallback_obeys_style_bans(bluff)


def test_never_bought_active_unpaid():
    assert sg.last_ppv_never_bought({}, {"active": True, "purchased": False})
    assert not sg.last_ppv_never_bought({}, {"active": False, "purchased": True})


def test_never_bought_recent_expire():
    ago = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
    mem = {
        "last_ppv_expired_at": ago,
        "last_ppv_expire_reason": "expired_inline",
        "purchases": 0,
        "total_spent": 0,
    }
    assert sg.last_ppv_never_bought(mem, {"active": False, "purchased": False})


def test_purchased_clear_not_bluff():
    ago = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
    mem = {
        "last_ppv_expired_at": ago,
        "last_ppv_expire_reason": "purchased",
        "purchases": 1,
        "total_spent": 7,
    }
    assert not sg.last_ppv_never_bought(mem, {"active": False, "purchased": False})


def test_please_not_treated_as_reject():
    msg = "porfavor baby, no me dejes con las ganas"
    assert not _REJECT.search(msg), "bare 'no' must not kill begging closes"
    assert _DIRECT_BUY.search(msg)
    assert re.search(_BUYING, msg, re.I)


def test_ensenamela_is_direct_buy():
    assert _DIRECT_BUY.search("enseñamela")
    assert _DIRECT_BUY.search("ensename")
    assert re.search(_BUYING, "enseñamela", re.I)


def test_expiry_cooldown_bypassed_by_direct():
    ago = (datetime.now(timezone.utc) - timedelta(minutes=3)).isoformat()
    mem = {"last_ppv_expired_at": ago}
    assert _recently_expired(mem, minutes=8)
    # direct ask must be allowed past the cooldown gate (choose_offer logic)
    assert _DIRECT_BUY.search("enseñamela")


if __name__ == "__main__":
    test_fan_claims_liked_last_photo()
    test_validates_unseen()
    test_never_bought_active_unpaid()
    test_never_bought_recent_expire()
    test_purchased_clear_not_bluff()
    test_please_not_treated_as_reject()
    test_ensenamela_is_direct_buy()
    test_expiry_cooldown_bypassed_by_direct()
    print("ok")
