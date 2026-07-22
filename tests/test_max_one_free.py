"""Max one free L0 tease per fan — never gift liberally."""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from core.turn_policy import _free_tease_ok, decide_turn


def test_second_free_blocked():
    mem = {
        "messages": 20,
        "status": "warm",
        "free_teases_sent": 1,
        "last_free_at": datetime.now(timezone.utc).isoformat(),
        "sent_media_uuids": ["already-sent"],
        "total_spent": 0,
        "purchases": 0,
    }
    with patch("core.vault_catalog.l0_remaining", return_value=3):
        assert not _free_tease_ok(mem, msgs=20, now=datetime.now(timezone.utc))
        d = decide_turn(mem, "send me a free pic please")
        assert d.allow_free_tease is False
        assert d.allow_price is True


def test_first_free_ok_after_rapport():
    mem = {
        "messages": 12,
        "status": "warm",
        "free_teases_sent": 0,
        "last_free_at": None,
        "sent_media_uuids": [],
        "total_spent": 0,
        "purchases": 0,
    }
    with patch("core.vault_catalog.l0_remaining", return_value=3):
        assert _free_tease_ok(mem, msgs=12, now=datetime.now(timezone.utc))


def test_early_chat_no_free():
    mem = {
        "messages": 3,
        "status": "new",
        "free_teases_sent": 0,
        "sent_media_uuids": [],
        "total_spent": 0,
        "purchases": 0,
    }
    with patch("core.vault_catalog.l0_remaining", return_value=3):
        assert not _free_tease_ok(mem, msgs=3, now=datetime.now(timezone.utc))


if __name__ == "__main__":
    test_second_free_blocked()
    test_first_free_ok_after_rapport()
    test_early_chat_no_free()
    print("ok")
