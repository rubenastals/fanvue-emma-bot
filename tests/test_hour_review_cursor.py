"""Hour review is Cursor-cloud based — no DeepSeek audit path."""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from core import hour_review


def test_prompt_mentions_cursor_not_deepseek_auditor():
    src = (_ROOT / "core" / "hour_review.py").read_text(encoding="utf-8")
    assert "Cursor" in src or "CURSOR" in src
    assert "OpenAI" not in src
    assert "DEEPSEEK_API_KEY" not in src
    assert "launch_cloud_hour_review" in src


def test_build_hour_prompt_includes_frame():
    frames = [
        {
            "handle": "tester",
            "turns": [
                {
                    "fan_message": "How do you look in the photo?",
                    "reply": "i don't do discounts",
                    "pack_id": "ppv_unpaid",
                    "technique": "HOLD FRAME",
                    "lock_active": True,
                }
            ],
        }
    ]
    prompt = hour_review.build_hour_prompt(frames)
    assert "How do you look in the photo?" in prompt
    assert "HOLD FRAME" in prompt or "tech=HOLD FRAME" in prompt
    assert "technique_playbook" in prompt


def test_runner_mjs_uses_cloud():
    js = (_ROOT / "tools" / "fixer" / "run_hour_review.mjs").read_text(encoding="utf-8")
    assert "cloud:" in js or "cloud =" in js
    assert "autoCreatePR" in js
    assert "local:" not in js.split("Agent.prompt")[1][:400]
