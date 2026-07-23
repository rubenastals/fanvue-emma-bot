"""Emoji variety — no 🥵🥵🥵 stamps."""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from core import scheme_guard as sg


def test_emoji_rotate_block_lists_recent():
    turns = [
        {"role": "assistant", "content": "fuck baby 🥵"},
        {"role": "user", "content": "hey"},
        {"role": "assistant", "content": "so hot 🥵"},
    ]
    block = sg.emoji_rotate_turn_block(turns, n_bubbles=2)
    assert "🥵" in block
    assert "EMOJI ROTATE" in block
    assert "overused" in block


def test_vary_stale_emojis_swaps_repeat():
    turns = [
        {"role": "assistant", "content": "mm 🥵"},
        {"role": "user", "content": "more"},
    ]
    out, changed = sg.vary_stale_emojis("you make me 🥵", turns)
    assert changed
    assert "🥵" not in out
    assert out.strip()
