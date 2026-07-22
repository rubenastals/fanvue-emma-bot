"""Unpaid PPV pitches must not block re-sell — only free + purchased count as sent."""
from __future__ import annotations

import sys
import uuid
from pathlib import Path
from unittest.mock import patch

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from core import fan_memory, offer_selector


_FAKE = [
    {
        "media_uuid": "pay-a",
        "level": 1,
        "price": 4.0,
        "label": "Lingerie",
        "score": 5,
    },
    {
        "media_uuid": "pay-b",
        "level": 2,
        "price": 7.0,
        "label": "Topless",
        "score": 6,
    },
]


def test_set_last_offer_does_not_mark_sent():
    fid = f"test-fan-{uuid.uuid4().hex[:12]}"
    fan_memory.set_last_offer(
        fid,
        40.0,
        fan_handle="tester",
        level=6,
        media_uuid="pay-a",
        label="Lingerie",
        message_uuid="msg-1",
    )
    mem = fan_memory.get(fid) or {}
    assert "pay-a" not in (mem.get("sent_media_uuids") or [])
    assert mem.get("last_ppv_pending") is True
    assert mem.get("last_ppv_media_uuid") == "pay-a"


def test_mark_ppv_purchased_marks_sent():
    fid = f"test-fan-{uuid.uuid4().hex[:12]}"
    fan_memory.set_last_offer(
        fid,
        4.0,
        fan_handle="tester",
        level=1,
        media_uuid="pay-a",
        label="Lingerie",
    )
    fan_memory.mark_ppv_purchased(
        fid, "pay-a", fan_handle="tester", label="Lingerie", level=1
    )
    mem = fan_memory.get(fid) or {}
    assert "pay-a" in (mem.get("sent_media_uuids") or [])


def test_scrub_frees_unpaid_for_zero_spender():
    fid = f"test-fan-{uuid.uuid4().hex[:12]}"
    # Simulate legacy bug: pitch marked sent
    with fan_memory._LOCK:
        mem = fan_memory.get(fid) or fan_memory._blank("tester")
        mem["handle"] = "tester"
        mem["purchases"] = 0
        mem["total_spent"] = 0.0
        mem["sent_media_uuids"] = ["pay-a", "pay-b", "free-1"]
        mem["sent_content"] = [
            {"uuid": "pay-a", "level": 1, "kind": "ppv", "label": "x"},
            {"uuid": "free-1", "level": 0, "kind": "free", "label": "y"},
        ]
        fan_memory._put(fid, mem)

    catalog = {
        "pay-a": _FAKE[0],
        "pay-b": _FAKE[1],
        "free-1": {
            "media_uuid": "free-1",
            "level": 0,
            "price": 0,
            "label": "Free",
            "score": 1,
        },
    }
    with patch("core.fan_memory._catalog_lookup", return_value=catalog):
        n = fan_memory.scrub_unseen_ppv_from_sent(fid, fan_handle="tester")
    mem = fan_memory.get(fid) or {}
    assert n >= 2
    assert "pay-a" not in (mem.get("sent_media_uuids") or [])
    assert "pay-b" not in (mem.get("sent_media_uuids") or [])
    assert "free-1" in (mem.get("sent_media_uuids") or [])


def test_merge_skips_unpaid_lock_in_chat():
    fid = f"test-fan-{uuid.uuid4().hex[:12]}"
    creator = "creator-1"
    messages = [
        {
            "sender": {"uuid": creator},
            "mediaUuids": ["pay-locked"],
            "pricing": {"USD": {"price": 4000}},
            # unpaid — no purchasedAt
        },
        {
            "sender": {"uuid": creator},
            "mediaUuids": ["free-seen"],
            "text": "😏",
        },
        {
            "sender": {"uuid": creator},
            "mediaUuids": ["pay-bought"],
            "pricing": {"USD": {"price": 700}},
            "purchasedAt": "2026-07-22T12:00:00Z",
        },
    ]
    n = fan_memory.merge_sent_from_chat(
        fid, messages, creator, fan_handle="tester"
    )
    mem = fan_memory.get(fid) or {}
    sent = set(mem.get("sent_media_uuids") or [])
    assert "pay-locked" not in sent
    assert "free-seen" in sent
    assert "pay-bought" in sent
    assert n >= 2


def test_zero_spender_candidates_include_previously_pitched():
    mem = {
        "purchases": 0,
        "total_spent": 0.0,
        "sent_media_uuids": [],  # after scrub
        "last_ppv_pending": False,
        "failed_media_uuids": [],
    }
    with patch("core.offer_selector.vault_catalog.load_items", return_value=_FAKE):
        cands = offer_selector.candidate_offers(mem, "quiero ver")
    assert any(c["media_uuid"] == "pay-a" for c in cands)


if __name__ == "__main__":
    test_set_last_offer_does_not_mark_sent()
    test_mark_ppv_purchased_marks_sent()
    test_scrub_frees_unpaid_for_zero_spender()
    test_merge_skips_unpaid_lock_in_chat()
    test_zero_spender_candidates_include_previously_pitched()
    print("ok")
