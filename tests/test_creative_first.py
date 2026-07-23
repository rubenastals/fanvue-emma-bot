"""Creative-first — ACTIVE MOVE always on; no personality loop belts."""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from core import creative_first


def test_never_skip_active_move():
    assert not creative_first.skip_active_move(
        pack_id="phase_pull", unpaid=False, fan_pushback=False
    )
    assert not creative_first.skip_active_move(
        pack_id="phase_hook", unpaid=False, fan_pushback=True
    )


def test_no_loop_belts():
    assert creative_first.keep_loop_belts() is False
