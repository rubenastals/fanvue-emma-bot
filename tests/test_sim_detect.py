"""Detectors for mass sim — no DeepSeek / Fanvue."""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from core.sim_detect import detect_reply_failures


def test_flags_robotic_ppv():
    fails = detect_reply_failures(
        "Just for you… this pic of me, $4 — unlock it if you really want to see me like this",
        paid_offer=True,
        media_attached=True,
        msgs_before=5,
    )
    assert any(f["rule"] == "CAPTION" for f in fails)


def test_flags_early_guilt():
    fails = detect_reply_failures(
        "most guys… poof they're gone",
        msgs_before=2,
    )
    assert any(f["rule"] == "EARLY" for f in fails)


def test_ok_filthy_caption():
    fails = detect_reply_failures(
        "look how filthy i look in this… $8 if you wanna see",
        paid_offer=True,
        media_attached=True,
        msgs_before=6,
        lock_active=False,
    )
    hard = [f for f in fails if f.get("severity", 0) >= 3 and f["rule"] == "CAPTION"]
    assert not hard


def test_flags_stock_lang_fallback():
    fails = detect_reply_failures("mmm tell me more…", msgs_before=3)
    assert any(f["rule"] == "FALLBACK" for f in fails)


if __name__ == "__main__":
    test_flags_robotic_ppv()
    test_flags_early_guilt()
    test_ok_filthy_caption()
    test_flags_stock_lang_fallback()
    print("ok")
