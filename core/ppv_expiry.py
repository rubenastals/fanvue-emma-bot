"""
Timed unpaid PPV — unsend after PPV_EXPIRE_MINUTES if not purchased.

Creates scarcity ("this won't sit forever") and keeps chat + bot state clean
so we never stack ghost locks.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Optional

from config import config
from core import fan_memory

if TYPE_CHECKING:
    from api.fanvue_connector import FanvueConnector


def _parse_iso(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except ValueError:
        return None


def _effective_expires(mem: dict, now: datetime) -> Optional[datetime]:
    """Explicit expires_at, or last_ppv_at + PPV_EXPIRE_MINUTES for legacy locks."""
    expires = _parse_iso(mem.get("last_ppv_expires_at"))
    if expires:
        return expires
    sent = _parse_iso(mem.get("last_ppv_at"))
    if not sent:
        return None
    mins = int(getattr(config, "PPV_EXPIRE_MINUTES", 30) or 30)
    return sent + timedelta(minutes=mins)


def _extract_msg_uuid(resp: Optional[dict]) -> Optional[str]:
    if not isinstance(resp, dict):
        return None
    for key in ("uuid", "messageUuid", "message_uuid", "id"):
        v = resp.get(key)
        if v:
            return str(v)
    data = resp.get("data")
    if isinstance(data, dict):
        for key in ("uuid", "messageUuid", "id"):
            v = data.get(key)
            if v:
                return str(v)
    return None


def resolve_ppv_message_uuid(
    fv: "FanvueConnector",
    fan_uuid: str,
    *,
    creator_uuid: str,
    media_uuid: str,
    send_resp: Optional[dict] = None,
    aliases: Optional[list] = None,
) -> Optional[str]:
    """Prefer API send response; fall back to chat history lookup."""
    uid = _extract_msg_uuid(send_resp)
    if uid:
        return uid
    return fv.find_message_uuid_for_media(
        fan_uuid,
        media_uuid,
        creator_uuid=creator_uuid,
        aliases=aliases,
    )


def run_pass(fv: "FanvueConnector", creator_uuid: str) -> int:
    """
    Unsend expired unpaid locks. Returns how many were deleted.
    Purchased locks are left alone (API refuses delete; we clear tracking).
    """
    if not getattr(config, "PPV_EXPIRE_ENABLED", True):
        return 0

    now = datetime.now(timezone.utc)
    deleted = 0

    for fan_uuid, mem in fan_memory.pending_ppv_candidates():
        expires = _effective_expires(mem, now)
        msg_uuid = (mem.get("last_ppv_message_uuid") or "").strip()
        media_uuid = (mem.get("last_ppv_media_uuid") or "").strip()
        handle = mem.get("handle") or ""

        # No expiry clock → skip
        if not expires:
            continue
        if expires > now:
            continue

        # Resolve message uuid from history if memory lost it
        if not msg_uuid and media_uuid:
            try:
                msg_uuid = fv.find_message_uuid_for_media(
                    fan_uuid, media_uuid, creator_uuid=creator_uuid
                ) or ""
            except Exception:
                msg_uuid = ""

        if not msg_uuid:
            # Can't unsend without id — clear tracking so we don't soft-lock forever
            fan_memory.clear_pending_ppv(
                fan_uuid, fan_handle=handle, reason="expired_no_message_uuid"
            )
            print(
                f"   ⏳ PPV expire @{handle or fan_uuid[:8]}: "
                f"no message uuid — cleared tracking"
            )
            continue

        # Still in chat + already purchased? keep it, clear timer
        try:
            msgs = fv.get_messages(fan_uuid, size=25)
        except Exception as e:
            print(f"   ⚠️ PPV expire fetch @{handle}: {e}")
            continue

        target = None
        for m in msgs:
            if m.get("uuid") == msg_uuid:
                target = m
                break
            # Fallback: match by media if uuid drifted
            if media_uuid and media_uuid in (m.get("mediaUuids") or []):
                if m.get("pricing"):
                    target = m
                    msg_uuid = m.get("uuid") or msg_uuid
                    break

        if target is None:
            # Already gone from chat
            fan_memory.clear_pending_ppv(
                fan_uuid, fan_handle=handle, reason="already_gone"
            )
            print(f"   ⏳ PPV expire @{handle}: already gone from chat")
            continue

        if target.get("purchasedAt"):
            fan_memory.clear_pending_ppv(
                fan_uuid, fan_handle=handle, reason="purchased"
            )
            print(f"   ⏳ PPV expire @{handle}: purchased — left in place")
            continue

        try:
            fv.delete_message(fan_uuid, msg_uuid)
            fan_memory.clear_pending_ppv(
                fan_uuid, fan_handle=handle, reason="expired_unsent"
            )
            deleted += 1
            label = (mem.get("last_ppv_label") or "")[:40]
            print(
                f"   ⏳ PPV expired/unsent @{handle}: {label} "
                f"(msg {msg_uuid[:8]}…)"
            )
        except Exception as e:
            err = str(e)
            # Purchased race / forbidden
            if "400" in err or "purchased" in err.lower():
                fan_memory.clear_pending_ppv(
                    fan_uuid, fan_handle=handle, reason="purchased_or_forbidden"
                )
                print(f"   ⏳ PPV expire @{handle}: cannot delete ({e})")
            else:
                print(f"   ❌ PPV expire delete @{handle}: {type(e).__name__}: {e}")

    return deleted
