"""EN lang cleanup must not loop the sticky 'look at me when I'm talking' stamp."""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from core import language
from core.reply_sanitize import (
    _force_english_cleanup,
    _lang_fallback,
    _norm_bubble,
)

STAMP = "Hey... look at me when I'm talking to you."


def test_coerce_sendable_replaces_stamp():
    from core.reply_sanitize import coerce_sendable_reply, is_banned_reply_stamp

    bad = "Hey... look at me when I'm talking to you."
    assert is_banned_reply_stamp(bad)
    out = coerce_sendable_reply(bad, want_spanish=False, history_turns=[])
    assert "look at me when" not in out.lower()


def test_scrub_history_replaces_poison():
    from core.reply_sanitize import scrub_banned_assistant_turns

    turns = [
        {"role": "user", "content": "yea"},
        {"role": "assistant", "content": "Hey... look at me when I'm talking to you."},
    ]
    out = scrub_banned_assistant_turns(turns)
    assert "look at me when" not in out[-1]["content"].lower()


def test_birbo_stamp_blocked_by_regex():
    """Exact line from live Sophia/Birbo thread must never ship."""
    from core.reply_sanitize import _RETIRED_LOOK_AT_ME

    bad = "Hey... look at me when I'm talking to you."
    assert _RETIRED_LOOK_AT_ME.search(bad)


def test_stamp_never_returned():
    history = [{"role": "assistant", "content": STAMP}]
    out = _force_english_cleanup(
        "Ay bebé mira esto qué rico estás",
        history_turns=history,
    )
    assert _norm_bubble(out) != _norm_bubble(STAMP)
    assert "look at me when" not in out.lower()


def test_salvages_english_after_strip():
    out = _force_english_cleanup(
        "come here bebé… you drive me crazy",
        history_turns=[],
    )
    assert "come here" in out.lower()
    assert "crazy" in out.lower()
    assert "bebé" not in out.lower() and "bebe" not in out.lower()


def test_fallback_avoids_recent_duplicate():
    used = "hey… don't go quiet on me now"
    history = [{"role": "assistant", "content": used}]
    # Many draws — none should equal the banned recent bubble
    for _ in range(20):
        out = _lang_fallback(want_spanish=False, history_turns=history)
        assert _norm_bubble(out) != _norm_bubble(used)


def test_en_mixed_needs_more_than_one_cognate():
    # Single pet-name crumb with English glue — strip path, not full rewrite
    assert not language.is_mixed_or_wrong(
        "come here baby you drive me crazy",
        want_spanish=False,
    )
    assert language.is_mixed_or_wrong(
        "Ay mira bebé esto está muy caliente para ti",
        want_spanish=False,
    )


if __name__ == "__main__":
    test_stamp_never_returned()
    test_salvages_english_after_strip()
    test_fallback_avoids_recent_duplicate()
    test_en_mixed_needs_more_than_one_cognate()
    print("ok")
