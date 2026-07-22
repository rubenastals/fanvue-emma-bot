"""Short replies must finish thoughts — no mid-clause chops."""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from core.reply_engine import (
    looks_incomplete_text,
    split_into_messages,
    _trim_dangling_clause,
)
from core import scheme_guard as sg


def test_incomplete_dangling_words():
    assert looks_incomplete_text("I want to tell you about")
    assert looks_incomplete_text("estaba pensando en ti y")
    assert looks_incomplete_text("come here and")
    assert looks_incomplete_text("mira lo que te tengo,")
    assert not looks_incomplete_text("just got out the shower… still dripping")
    assert not looks_incomplete_text("Fuck… I'm getting wet just reading that.")
    assert not looks_incomplete_text("Ábrela si de verdad quieres verme así 😈")


def test_trim_dangling_keeps_finished_head():
    raw = "Solo para ti, bebé. Quería decirte que"
    out = _trim_dangling_clause(raw)
    assert out.endswith(".")
    assert "Quería" not in out
    assert not looks_incomplete_text(out)


def test_split_does_not_ellipsis_chop():
    long = (
        "Just got out the shower and I'm still dripping thinking about your hands "
        "on me tonight baby. Want me to lock something filthy for you?"
    )
    bubbles = split_into_messages(long, max_len=120, max_bubbles=2)
    assert bubbles
    assert not any(b.endswith("…") and looks_incomplete_text(b) for b in bubbles)
    assert not looks_incomplete_text(bubbles[-1])


def test_thread_beat_uses_recent_turns_not_stale_summary():
    turns = [
        {"role": "user", "content": "my dog is sick today"},
        {"role": "assistant", "content": "aw baby I'm sorry… what's wrong with him?"},
        {"role": "user", "content": "he won't eat"},
        {"role": "assistant", "content": "poor thing… stay with him"},
        {"role": "user", "content": "yeah I'm worried"},
    ]
    mem = {"summary": "He likes cars and soccer", "facts": ["has a dog named Max"]}
    beat = sg.thread_beat_block(turns, mem)
    assert "Recent thread:" in beat
    assert "dog is sick" in beat or "worried" in beat
    assert "He likes cars" not in beat  # stale summary must not lead
    assert "Max" in beat or "Card facts" in beat


if __name__ == "__main__":
    test_incomplete_dangling_words()
    test_trim_dangling_keeps_finished_head()
    test_split_does_not_ellipsis_chop()
    test_thread_beat_uses_recent_turns_not_stale_summary()
    print("ok")
