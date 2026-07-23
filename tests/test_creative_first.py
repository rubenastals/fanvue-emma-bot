"""Creative-first mode — no ACTIVE MOVE on normal chat."""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from core import creative_first


def test_skip_move_on_normal_chat():
    assert creative_first.skip_active_move(
        pack_id="phase_pull", unpaid=False, fan_pushback=False
    )


def test_keep_move_on_unpaid():
    assert not creative_first.skip_active_move(
        pack_id="ppv_unpaid", unpaid=True, fan_pushback=False
    )
