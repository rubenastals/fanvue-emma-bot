"""Persona + author rails push WhatsApp-informal texting."""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from core import language, prompt_core


def test_persona_whatsapp_block():
    p = prompt_core.get_active_persona()
    assert "WHATSAPP VOICE" in p
    assert "q, xq" in p or "q, xq, tb" in p.lower() or "xq" in p
    assert "HARD BAN essay voice" in p


def test_grammar_rewrite_keeps_chat_tone():
    instr = language.grammar_rewrite_instruction()
    assert "WhatsApp" in instr or "whatsapp" in instr.lower()
    assert "abreviaturas" in instr.lower() or "q, xq" in instr
    assert "libro" in instr.lower() or "atención" in instr.lower()


def test_prompt_version_bumped():
    assert "whatsapp" in prompt_core.PROMPT_VERSION.lower()


if __name__ == "__main__":
    test_persona_whatsapp_block()
    test_grammar_rewrite_keeps_chat_tone()
    test_prompt_version_bumped()
    print("ok")
