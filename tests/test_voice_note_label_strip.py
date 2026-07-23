"""[Voice Note: (breathy, soft)] / *voice note plays* must never reach the fan."""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from core.reply_sanitize import (
    _sanitize_reply,
    is_voice_stage_only_bubble,
    looks_like_voice_script_dump,
    strip_voice_stage_leaks,
)
from core import voice_notes as vn


LEAK = (
    "[Voice Note: (breathy, soft)] Esa foto, bebé… solo yo, desnuda, "
    "mojada, tocándome pensando en ti. Es íntima, distinta.."
)


def test_detects_voice_note_label():
    assert looks_like_voice_script_dump(LEAK)
    assert looks_like_voice_script_dump("Voice Note: (whispering) hola")
    assert looks_like_voice_script_dump("(breathy, soft) ven aquí")
    assert looks_like_voice_script_dump("*voice note plays*")
    assert looks_like_voice_script_dump("*sends a voice note*")
    assert not looks_like_voice_script_dump("Ven aquí un segundo… esto es solo para ti")


def test_strip_removes_label_keeps_tease_when_no_audio():
    out = strip_voice_stage_leaks(LEAK)
    assert "Voice Note" not in out
    assert "breathy" not in out.lower()
    assert "[" not in out
    assert "Esa foto" in out or "desnuda" in out


def test_strip_voice_note_plays():
    assert strip_voice_stage_leaks("*voice note plays*") == ""
    assert is_voice_stage_only_bubble("*voice note plays*")
    assert is_voice_stage_only_bubble("voice note plays")
    mixed = strip_voice_stage_leaks("wait…\n*voice note plays*")
    assert "plays" not in mixed.lower()
    assert "wait" in mixed.lower()


def test_sanitize_with_voice_replaces_dump():
    out = _sanitize_reply(LEAK, want_spanish=True, voice_will_send=True)
    assert "Voice Note" not in out
    assert "breathy" not in out.lower()
    assert "desnuda" not in out.lower()
    assert out == vn.forced_voice_close_line(want_spanish=True)


def test_sanitize_without_voice_strips_label_only():
    out = _sanitize_reply(LEAK, want_spanish=True, voice_will_send=False)
    assert "Voice Note" not in out
    assert "breathy" not in out.lower()
    assert "desnuda" in out.lower() or "foto" in out.lower()


def test_forced_close_not_a_dump():
    line = vn.forced_voice_close_line(want_spanish=True)
    assert not looks_like_voice_script_dump(line)


if __name__ == "__main__":
    test_detects_voice_note_label()
    test_strip_removes_label_keeps_tease_when_no_audio()
    test_strip_voice_note_plays()
    test_sanitize_with_voice_replaces_dump()
    test_sanitize_without_voice_strips_label_only()
    test_forced_close_not_a_dump()
    print("ok")
