"""PPV expire must not poll-loop on test-fan junk UUIDs."""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from core import fan_memory


def test_real_uuid_ok():
    assert fan_memory.is_real_fan_uuid("351076d9-61f1-4ea3-8a24-41230cf174d4")


def test_test_fan_rejected():
    assert not fan_memory.is_real_fan_uuid("test-fan-f95f90b4f4e4")
    assert not fan_memory.is_real_fan_uuid("test-fan-5f3bf43eb6d2")
    assert not fan_memory.is_real_fan_uuid("")


if __name__ == "__main__":
    test_real_uuid_ok()
    test_test_fan_rejected()
    print("ok")
