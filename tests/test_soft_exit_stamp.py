"""Ban SOFT EXIT PPV stamp when no lock."""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from core.reply_sanitize import _soft_exit_stamp_without_lock


def test_stamp_blocked_without_lock():
    msg = "ok babe… no pressure at all. you know where to find me when you're ready 😘"
    assert _soft_exit_stamp_without_lock(msg, lock_active=False)
    assert not _soft_exit_stamp_without_lock(msg, lock_active=True)
