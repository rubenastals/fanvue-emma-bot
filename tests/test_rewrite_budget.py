"""R2: hard lies use strip/fallback — never a multi-LLM rewrite cascade."""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from core.reply_engine import (
    RewriteBudget,
    _enforce_delivery_truth,
    _fix_invented_wait_minutes,
    _strip_wrong_prices,
)
from core import scheme_guard as sg


def test_rewrite_budget_caps_llm_calls():
    calls = []

    def fake_call(msgs):
        calls.append(msgs)
        return "ok"

    rw = RewriteBudget(max_extra=1)
    assert rw.spend("lang", fake_call, [{"role": "user", "content": "a"}]) == "ok"
    assert rw.spend("grammar", fake_call, [{"role": "user", "content": "b"}]) is None
    assert len(calls) == 1
    assert rw.used == 1
    assert rw.log == ["lang"]


def test_hard_lies_deterministic_no_llm_needed():
    from core.reply_engine import _claims_unconfirmed_delivery

    # Delivery lie → strip/fallback (no LLM rewrite)
    dirty = "Ya te envié la foto, está en tu bandeja 😏"
    assert _claims_unconfirmed_delivery(dirty)
    clean = _enforce_delivery_truth(dirty, media_attached=False, want_spanish=True)
    assert not _claims_unconfirmed_delivery(clean)
    assert len(clean) >= 12

    # Sell misaligned → forced line
    line = sg.forced_paid_sell_line(price=40, want_spanish=True, label="tits")
    assert sg.paid_offer_reply_aligned(line)
    assert "$40" in line

    # Bluff / invent lock / video / ghost / blame → fallbacks
    bluff = sg.fallback_purchase_bluff(want_spanish=True, lock_still_active=True)
    assert "Mentiroso" in bluff or "no la has abierto" in bluff.lower()
    assert sg.fallback_obeys_style_bans(bluff)

    no_lock = sg.fallback_no_lock(want_spanish=True)
    assert not sg.invented_lock_claim(no_lock, lock_active=False)
    assert sg.fallback_obeys_style_bans(no_lock)

    photos = sg.fallback_photos_only(want_spanish=True, real_price=None)
    assert not sg.invented_video_claim(photos)
    photos_priced = sg.fallback_photos_only(want_spanish=True, real_price=12.0)
    assert not sg.invented_video_claim(photos_priced)

    ghost = sg.fallback_ghost_promise(want_spanish=True)
    assert not sg.ghost_media_promise(ghost, media_attached=False)

    blame = sg.fallback_blame_own_it(want_spanish=True)
    assert not sg.blame_after_ghost(blame, media_attached=False)

    # Price belt
    stripped = _strip_wrong_prices("Ábrela por $9 bebé", real_price=40.0)
    assert "$40" in stripped
    assert "$9" not in stripped


def test_fix_invented_wait_clamps_without_llm():
    raw = "Llevo 27 minutos esperando que abras el candado 😏"
    out = _fix_invented_wait_minutes(raw, minutes_ago=4)
    assert "27" not in out
    assert "4" in out
    assert not sg.invented_lock_wait_minutes(out, minutes_ago=4)


if __name__ == "__main__":
    test_rewrite_budget_caps_llm_calls()
    test_hard_lies_deterministic_no_llm_needed()
    test_fix_invented_wait_clamps_without_llm()
    print("ok")
