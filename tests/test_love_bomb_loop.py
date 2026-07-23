"""Love-bomb validation stamp loop (Dan: only girl / got me soft)."""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from core.reply_sanitize import apply_post_draft


def test_repeated_love_bomb_stamp_replaced():
    turns = [
        {"role": "assistant", "content": "glad you're here… only girl in the world rn"},
        {"role": "user", "content": "Absolutely"},
    ]
    assembled = SimpleNamespace(
        messages=[],
        decision=SimpleNamespace(mode="rapport", pack_id="phase_pull"),
        pack_id="phase_pull",
        tech_name="BOND",
        phase_name="",
        want_spanish=False,
        fan_uuid="test-fan",
        fan_handle="dan",
        fan_message="Absolutely",
        turns=turns,
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
    reply = "mm I like having you here dan… feeling soft and special 💕"
    out, _ = apply_post_draft(
        reply,
        assembled,
        call=lambda _m: "fuck… keep talking like that",
    )
    assert "only girl" not in out.lower()
    assert "soft and special" not in out.lower()
