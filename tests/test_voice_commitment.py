"""Action-first voice: DB commitment owns protocol, not the prompt."""
from __future__ import annotations

import sys
import uuid
from pathlib import Path
from types import SimpleNamespace

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from core import fan_memory, voice_notes as vn
from core.turn_action import commitment_prompt_line


def _fan():
    return f"test-fan-{uuid.uuid4().hex[:12]}"


def test_set_clear_commitment():
    fid = _fan()
    c = fan_memory.set_commitment(
        fid, ctype="voice", source="fan_ask", fan_handle="tester"
    )
    assert c["type"] == "voice"
    assert fan_memory.get_commitment(fid)["hits"] >= 1
    fan_memory.set_commitment(
        fid, ctype="voice", source="fan_ask", fan_handle="tester", bump=True
    )
    assert fan_memory.get_commitment(fid)["hits"] >= 2
    fan_memory.clear_commitment(fid, ctype="voice", fan_handle="tester")
    assert fan_memory.get_commitment(fid) is None


def test_record_voice_clears_commitment():
    fid = _fan()
    fan_memory.set_commitment(
        fid, ctype="voice", source="stall", fan_handle="tester"
    )
    fan_memory.record_voice_note(fid, fan_handle="tester", script="hi")
    assert fan_memory.get_commitment(fid) is None


def test_sync_sets_commitment_from_pidemelo_thread():
    fid = _fan()
    history = [
        {"role": "assistant", "content": "quieres un audio? pídemelo"},
        {"role": "user", "content": "por favor"},
    ]
    c = vn.sync_commitment_from_thread(
        fid,
        fan_handle="tester",
        fan_message="por favor",
        history_turns=history,
    )
    assert c and c["type"] == "voice"


def test_resolve_forces_send_with_db_commitment():
    fid = _fan()
    fan_memory.set_commitment(
        fid, ctype="voice", source="prior", fan_handle="tester", bump=False
    )
    mem = fan_memory.get(fid)
    history = [
        {"role": "assistant", "content": "pídemelo bien"},
        {"role": "user", "content": "por favor"},
    ]
    orig = vn._enabled
    vn._enabled = lambda: True  # type: ignore
    try:
        ok, why, mem2 = vn.resolve_voice_action(
            fan_uuid=fid,
            fan_handle="tester",
            fan_message="por favor",
            mem=mem,
            decision=SimpleNamespace(mode="tease"),
            pack_id="ppv_unpaid",
            unpaid=True,
            history_turns=history,
        )
        assert ok, why
        assert "commitment" in why.lower() or "beg-loop" in why or "owed" in why
        assert (mem2.get("open_commitment") or {}).get("type") == "voice"
    finally:
        vn._enabled = orig  # type: ignore


def test_commitment_prompt_line_short():
    line = commitment_prompt_line(
        {"open_commitment": {"type": "voice", "hits": 5}},
        voice_will_send=True,
    )
    assert "COMMITMENT" in line
    assert "pídemelo" in line.lower()
    assert len(line) < 400


if __name__ == "__main__":
    test_set_clear_commitment()
    test_record_voice_clears_commitment()
    test_sync_sets_commitment_from_pidemelo_thread()
    test_resolve_forces_send_with_db_commitment()
    test_commitment_prompt_line_short()
    print("ok")
