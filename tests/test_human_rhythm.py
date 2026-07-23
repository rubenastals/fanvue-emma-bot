"""Human rhythm: typing delays + short bubble budgets."""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from config import config
from core.reply_sanitize import _char_budgets, split_into_messages
from core.send_timing import human_typing_delay


def test_char_budgets_match_config_defaults():
    max_len, max_bubbles, soft_total = _char_budgets()
    assert max_len == max(60, int(config.BUBBLE_MAX_CHARS))
    assert max_bubbles == max(1, int(config.MAX_BUBBLES))
    assert soft_total >= max_len


def test_split_caps_at_two_bubbles_by_default():
    essay = (
        "hey babe\n"
        "I was just thinking about you and what we talked about earlier\n"
        "and honestly I can't stop smiling about it right now"
    )
    bubbles = split_into_messages(essay)
    assert len(bubbles) <= int(config.MAX_BUBBLES)


def test_typing_delay_first_bubble_slower_than_instant():
    delay = human_typing_delay("hey", first=True)
    assert delay >= 8.0


def test_typing_delay_longer_text_much_slower():
    short = human_typing_delay("hey", first=True)
    long = human_typing_delay("x" * 120, first=True)
    assert long > short + 10


def test_typing_delay_second_bubble_still_human_paced():
    first = human_typing_delay("x" * 40, first=True)
    second = human_typing_delay("ok", first=False, prev_text="x" * 40)
    assert second >= 5.0
    assert first > second or first >= 8.0
