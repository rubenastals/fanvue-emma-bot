"""Parse Fanvue Standard-Webhooks payloads for side effects (reactions, etc.)."""
from __future__ import annotations

from typing import Optional, Tuple


def parse_message_reaction(data: dict) -> Tuple[Optional[str], str, str]:
    """
    creator.message.reaction → (fan_uuid, emoji, message_uuid).
    fan_uuid is the actor when they are not the creator.
    """
    if (data or {}).get("type") != "creator.message.reaction":
        return None, "", ""
    payload = data.get("data") or {}
    emoji = str(payload.get("emoji") or "").strip()
    msg_uuid = str(payload.get("message_uuid") or "").strip()
    actor = (payload.get("actor") or {}).get("uuid")
    creator = (payload.get("creator") or {}).get("uuid")
    if not actor:
        return None, emoji, msg_uuid
    fan_uuid = actor if actor != creator else None
    return fan_uuid, emoji, msg_uuid
