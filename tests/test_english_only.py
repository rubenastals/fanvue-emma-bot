"""ENGLISH_ONLY: Emma never chooses Spanish, even if the fan writes Spanish."""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from config import config
from core import language


def test_english_only_flag_on():
    assert getattr(config, "ENGLISH_ONLY", True) is True


def test_fan_wants_spanish_always_false():
    assert language.fan_wants_spanish("hola bebé cómo estás?", {"prefer_spanish": True}) is False
    assert language.fan_wants_spanish("habla español por favor", {}) is False
    assert language.fan_wants_spanish("hey baby whats up", {}) is False


def test_language_block_is_english_only():
    block = language.language_system_block(want_spanish=True)
    assert "ENGLISH ONLY" in block or "English" in block
    assert "FULL correct natural Spanish" not in block


def test_pref_update_forces_english():
    assert language.update_language_pref({}, "hola qué tal") is False


def test_voice_close_english():
    from core import voice_notes as vn
    from core import scheme_guard as sg

    line = vn.forced_voice_close_line(want_spanish=True)
    assert "Ven aquí" not in line
    assert "for you" in line.lower() or "come here" in line.lower()
    assert "Just for you" in sg.forced_paid_sell_line(price=9, want_spanish=True)
    assert "Solo para ti" not in sg.forced_paid_sell_line(price=9, want_spanish=True)


if __name__ == "__main__":
    test_english_only_flag_on()
    test_fan_wants_spanish_always_false()
    test_language_block_is_english_only()
    test_pref_update_forces_english()
    test_voice_close_english()
    print("ok")
