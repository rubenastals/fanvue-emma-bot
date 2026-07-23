"""Re-engagement nudges should not loop the same guilt / visto lines."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from core import reengagement


def test_templates_have_distinct_angles():
    assert "share_moment" in reengagement._TEMPLATES
    assert "curious_hook" in reengagement._TEMPLATES
    assert "flirty_tease" in reengagement._TEMPLATES
    guilt = "Me dejaste con el mensaje en visto y te fuiste… qué malo eres 😒"
    for style, langs in reengagement._TEMPLATES.items():
        for line in langs["es"]:
            assert line != guilt, style


def test_pick_avoids_recent_texts():
    pool = reengagement._TEMPLATES["soft_checkin"]["es"]
    used = pool[:3]
    mem = {"last_nudge_texts": used}
    with patch("core.reengagement.random.choice", side_effect=lambda xs: xs[0]):
        line = reengagement._pick_nudge_template("soft_checkin", True, mem)
    assert line not in used


def test_pick_angle_skips_recent_styles():
    mem = {
        "last_nudge_style": "soft_checkin",
        "last_nudge_styles": ["soft_checkin", "curious_hook"],
    }
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    # Force deterministic: only one candidate left for step 1 after avoid
    with patch.object(
        reengagement,
        "NUDGE_ANGLES",
        {
            "soft_checkin": {"steps": (1,), "weight": 10},
            "curious_hook": {"steps": (1,), "weight": 10},
            "share_moment": {"steps": (1,), "weight": 1},
        },
    ):
        angle = reengagement.pick_nudge_angle(mem, 1, now, victim_ok=False)
    assert angle == "share_moment"


def test_victim_weight_lower_than_share():
    assert reengagement.NUDGE_ANGLES["victim_soft"]["weight"] < (
        reengagement.NUDGE_ANGLES["share_moment"]["weight"]
    )


def test_fan_active_recently_blocks_nudge_window():
    from datetime import datetime, timedelta, timezone

    fan = "fan-uuid"
    now = datetime.now(timezone.utc)
    messages = [
        {
            "sender": {"uuid": fan},
            "sentAt": (now - timedelta(minutes=5)).isoformat(),
            "text": "hey",
        },
        {
            "sender": {"uuid": "creator"},
            "sentAt": (now - timedelta(minutes=3)).isoformat(),
            "text": "hi",
        },
    ]
    assert reengagement._fan_active_recently(messages, fan, minutes=25)
