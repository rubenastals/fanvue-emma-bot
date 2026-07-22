"""No theatrical quotation marks when echoing the fan."""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from core import scheme_guard


def test_strip_double_echo_quotes():
    raw = '"putilla"... mira quién habla, el que me está rogando ver las tetas a las 6am 😤'
    out = scheme_guard.strip_echo_quotes(raw)
    assert '"putilla"' not in out
    assert '"' not in out
    assert "putilla" in out
    assert "mira quién habla" in out


def test_strip_guillemets():
    raw = "«putilla»… mira quién habla"
    out = scheme_guard.strip_echo_quotes(raw)
    assert "«" not in out and "»" not in out
    assert out.startswith("putilla")


def test_keeps_contractions():
    raw = "don't leave me babe it's fine"
    assert scheme_guard.strip_echo_quotes(raw) == raw


def test_curly_quotes():
    raw = "“puto”… en serio?"
    out = scheme_guard.strip_echo_quotes(raw)
    assert "puto" in out
    assert "“" not in out and "”" not in out
