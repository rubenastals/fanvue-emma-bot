"""
Structured conversation log — the data the learning loop feeds on.

Persists to Postgres (conversation_events) when DATABASE_URL is set,
and always mirrors to logs/conversations/<fan_uuid>.jsonl.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from db import convo_store


def log_turn(
    fan_uuid: str,
    *,
    fan_handle: str,
    fan_message: str,
    reply: str,
    bubbles: int,
    mode: str,
    mode_reason: str,
    offer: Optional[Dict[str, Any]] = None,
) -> None:
    convo_store.append_event(
        fan_uuid,
        "turn",
        {
            "handle": fan_handle,
            "fan_message": fan_message,
            "reply": reply,
            "bubbles": bubbles,
            "mode": mode,
            "mode_reason": mode_reason,
            "offer": (
                {
                    "media_uuid": offer.get("media_uuid"),
                    "level": offer.get("level"),
                    "price": offer.get("price"),
                    "label": offer.get("label"),
                }
                if offer
                else None
            ),
        },
    )


def log_offer_outcome(
    fan_uuid: str,
    outcome: str,
    *,
    amount: Optional[float] = None,
    detail: str = "",
) -> None:
    """outcome: purchased | rejected | ignored"""
    convo_store.append_event(
        fan_uuid,
        "offer_outcome",
        {
            "outcome": outcome,
            "amount": amount,
            "detail": detail,
        },
    )


def log_critic(fan_uuid: str, payload: Dict[str, Any]) -> None:
    """Optional helper — critic may still call append via type in payload."""
    convo_store.append_event(fan_uuid, "critic", payload)


def read_recent(fan_uuid: str, *, max_records: int = 40) -> List[Dict[str, Any]]:
    return convo_store.read_recent(fan_uuid, max_records=max_records)


def all_fan_uuids() -> List[str]:
    return convo_store.all_fan_uuids()
