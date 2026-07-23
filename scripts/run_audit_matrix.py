#!/usr/bin/env python3
"""
Run the audit no-regression suite (R6).

Usage:
  python scripts/run_audit_matrix.py
"""
from __future__ import annotations

import runpy
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

SUITE = [
    "tests/test_regression_matrix.py",
    "tests/test_historical_sins.py",
    "tests/test_rewrite_budget.py",
    "tests/test_quarantine_dead_brains.py",
    "tests/test_turn_action.py",
    "tests/test_voice_fsm.py",
    "tests/test_voice_commitment.py",
    "tests/test_voice_owed.py",
    "tests/test_voice_beg_loop.py",
    "tests/test_complete_bubbles.py",
    "tests/test_purchase_bluff.py",
    "tests/test_offer_dirty_close.py",
    "tests/test_spanish_grammar.py",
]


def main() -> int:
    failed = []
    for rel in SUITE:
        path = _ROOT / rel
        print(f"\n=== {rel} ===")
        try:
            runpy.run_path(str(path), run_name="__main__")
        except SystemExit as e:
            if e.code not in (0, None):
                failed.append(rel)
                print(f"FAIL {rel}: SystemExit {e.code}")
        except Exception as e:
            failed.append(rel)
            print(f"FAIL {rel}: {type(e).__name__}: {e}")
    print("\n" + "=" * 40)
    if failed:
        print(f"FAILED {len(failed)}/{len(SUITE)}")
        for f in failed:
            print(f"  - {f}")
        return 1
    print(f"OK {len(SUITE)}/{len(SUITE)} audit matrix")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
