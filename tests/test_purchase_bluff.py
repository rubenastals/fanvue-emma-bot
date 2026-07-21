"""Fan bluffs he saw/liked a PPV he never bought."""
from datetime import datetime, timedelta, timezone

from core import scheme_guard as sg


def test_fan_claims_liked_last_photo():
    assert sg.fan_claims_saw_ppv("me ha gustado mucho la ultima foto")
    assert sg.fan_claims_saw_ppv("me gustó esa foto")
    assert sg.fan_claims_saw_ppv("liked the last photo a lot")
    assert sg.fan_claims_saw_ppv("ya la abrí")
    assert not sg.fan_claims_saw_ppv("hola baby como estas")


def test_validates_unseen():
    assert sg.validates_unseen_ppv(
        "me alegro que te gustara, baby... pero esa era solo un poquito"
    )
    assert sg.validates_unseen_ppv("glad you liked it — that was just a tease")
    assert not sg.validates_unseen_ppv("mmm mentiroso, nunca la abriste 😏")


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


if __name__ == "__main__":
    test_fan_claims_liked_last_photo()
    test_validates_unseen()
    test_never_bought_active_unpaid()
    test_never_bought_recent_expire()
    test_purchased_clear_not_bluff()
    print("ok")
