"""TTS must not speak stage labels like 'Bajito' / 'suspiro'."""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from utils.elevenlabs_client import scrub_tts_stage_directions


def test_live_bajito_prefix():
    raw = "Bajito, solo para ti… no te imaginas lo que haría si estuvieras aquí ahora mismo"
    out = scrub_tts_stage_directions(raw)
    assert not out.lower().startswith("bajito")
    assert "solo para ti" in out.lower()
    assert "imaginas" in out.lower()


def test_suspiro_paren_and_brackets():
    out = scrub_tts_stage_directions(
        "[whispers] (suspiro) Mmm... me tienes en la cabeza *sigh*"
    )
    assert "whisper" not in out.lower()
    assert "suspiro" not in out.lower()
    assert "sigh" not in out.lower()
    assert "me tienes" in out.lower()


def test_keeps_dialogue_bajito():
    # Real dirty line — not a leading stage label
    raw = "házmelo bajito bebé... así..."
    out = scrub_tts_stage_directions(raw)
    assert "bajito" in out.lower()
    assert "házmelo" in out.lower() or "hazmelo" in out.lower()


def test_ellipsis_lone_stage():
    out = scrub_tts_stage_directions("Mmm... suspiro... ven aquí")
    assert "suspiro" not in out.lower()
    assert "ven aquí" in out.lower() or "ven aqui" in out.lower()


if __name__ == "__main__":
    test_live_bajito_prefix()
    test_suspiro_paren_and_brackets()
    test_keeps_dialogue_bajito()
    test_ellipsis_lone_stage()
    print("ok")
