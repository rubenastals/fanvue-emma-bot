"""PPV forced captions must sound filthy WhatsApp — not store copy."""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from core import scheme_guard as sg


def test_no_robotic_just_for_you_stamp():
    for _ in range(20):
        line = sg.forced_paid_sell_line(price=4, want_spanish=False, label="ass tits")
        assert "Just for you… this pic of me" not in line
        assert "unlock it if you really want to see me like this" not in line
        assert "$4" in line
        assert sg.paid_offer_reply_aligned(line)
        assert sg.fallback_obeys_style_bans(line)


def test_spicy_has_filth_energy():
    hits = 0
    for _ in range(30):
        line = sg.forced_paid_sell_line(price=7, want_spanish=False, label="pussy thong")
        low = line.lower()
        if any(
            w in low
            for w in ("filthy", "slut", "whore", "nasty", "bent", "look how")
        ):
            hits += 1
    assert hits >= 15, "spicy labels should usually get dirty teases"


if __name__ == "__main__":
    test_no_robotic_just_for_you_stamp()
    test_spicy_has_filth_energy()
    print("ok")
