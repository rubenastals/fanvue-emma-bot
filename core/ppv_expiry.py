"""
Timed unpaid PPV — scarcity unsend + chat hygiene.

- New locks get last_ppv_expires_at (PPV_EXPIRE_MINUTES, default 30).
- run_pass: unsend expired unpaid locks; drop stacked extras (keep newest only).
- purge_all_unpaid: wipe every unpaid lock in recent chats (clean slate).
- Emma gets LOCK STATUS via build_lock_status() (active + minutes left, or none).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from config import config
from core import fan_memory

if TYPE_CHECKING:
    from api.fanvue_connector import FanvueConnector


def expire_minutes() -> int:
    try:
        return max(1, int(getattr(config, "PPV_EXPIRE_MINUTES", 30) or 30))
    except (TypeError, ValueError):
        return 30


def _parse_iso(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except ValueError:
        return None


def _msg_sent_at(msg: dict) -> Optional[datetime]:
    return _parse_iso(msg.get("sentAt") or msg.get("createdAt"))


def _msg_price_dollars(msg: dict) -> Optional[float]:
    pricing = msg.get("pricing") or {}
    if not pricing:
        return None
    usd = pricing.get("USD") or {}
    if usd.get("price") is not None:
        try:
            return float(usd["price"]) / 100.0
        except (TypeError, ValueError):
            return None
    return None


def _sender_uuid(msg: dict) -> Optional[str]:
    sender = msg.get("sender")
    if isinstance(sender, dict):
        return sender.get("uuid")
    return sender


def _msg_has_pricing(msg: dict) -> bool:
    """True if message is a paid lock (pricing object or legacy price fields)."""
    if msg.get("pricing"):
        return True
    if msg.get("price") not in (None, 0, "0", 0.0):
        return True
    if msg.get("isPaid") or msg.get("isLocked") or msg.get("locked"):
        return True
    return False


def list_unpaid_locks(
    messages: list,
    creator_uuid: str,
    *,
    lookback_hours: Optional[int] = 72,
) -> List[dict]:
    """
    All unpaid priced locks from Emma in this chat (newest first).
    lookback_hours=None → no age filter (use for deep purge of ancient locks).
    """
    now = datetime.now(timezone.utc)
    out: List[dict] = []
    for msg in messages or []:
        if _sender_uuid(msg) != creator_uuid:
            continue
        if not _msg_has_pricing(msg):
            continue
        media = msg.get("mediaUuids") or []
        if not media:
            # some payloads nest media
            for m in msg.get("media") or []:
                if isinstance(m, dict) and m.get("uuid"):
                    media.append(m["uuid"])
        if not media:
            continue
        if msg.get("purchasedAt"):
            continue
        sent = _msg_sent_at(msg)
        if (
            lookback_hours is not None
            and sent
            and now - sent > timedelta(hours=lookback_hours)
        ):
            continue
        uid = (msg.get("uuid") or "").strip()
        if not uid:
            continue
        out.append(
            {
                "message_uuid": uid,
                "media_uuid": media[0],
                "price": _msg_price_dollars(msg),
                "sent_at": sent.isoformat() if sent else None,
                "purchased": False,
            }
        )
    return out


def _effective_expires(mem: dict, sent_at: Optional[datetime] = None) -> Optional[datetime]:
    expires = _parse_iso(mem.get("last_ppv_expires_at"))
    if expires:
        return expires
    sent = sent_at or _parse_iso(mem.get("last_ppv_at"))
    if not sent:
        return None
    return sent + timedelta(minutes=expire_minutes())


def minutes_remaining(expires_at: Optional[datetime], now: Optional[datetime] = None) -> Optional[int]:
    if not expires_at:
        return None
    now = now or datetime.now(timezone.utc)
    secs = (expires_at - now).total_seconds()
    if secs <= 0:
        return 0
    return max(1, int(secs // 60) + (1 if secs % 60 else 0))


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


def build_lock_status(
    *,
    unpaid_locks: List[dict],
    mem: Optional[dict] = None,
    label_hint: str = "",
) -> Dict[str, Any]:
    """
    Single source of truth for Emma's LOCK STATUS block.
    active=True → one waiting timed lock; else none (she may persist toward a new one).
    """
    mem = mem or {}
    now = datetime.now(timezone.utc)
    if not unpaid_locks:
        return {
            "active": False,
            "count": 0,
            "label": "",
            "price": None,
            "minutes_left": None,
            "ago": None,
            "message_uuid": None,
            "media_uuid": None,
        }

    newest = unpaid_locks[0]
    sent = _parse_iso(newest.get("sent_at"))
    expires = _effective_expires(mem, sent)
    # If memory doesn't track this message, still invent a soft clock from sent_at
    if not expires and sent:
        expires = sent + timedelta(minutes=expire_minutes())
    mins = minutes_remaining(expires, now)
    ago = None
    if sent:
        age_m = int((now - sent).total_seconds() // 60)
        ago = f"{age_m} min ago" if age_m < 120 else f"{age_m // 60}h ago"

    label = label_hint or mem.get("last_ppv_label") or ""
    if newest.get("media_uuid") and newest["media_uuid"] == mem.get("last_ppv_media_uuid"):
        label = mem.get("last_ppv_label") or label

    return {
        "active": True,
        "count": len(unpaid_locks),
        "label": label,
        "price": newest.get("price")
        if newest.get("price") is not None
        else mem.get("last_ppv_price"),
        "minutes_left": mins,
        "expires_at": expires.isoformat() if expires else None,
        "ago": ago,
        "sent_at": newest.get("sent_at"),
        "message_uuid": newest.get("message_uuid"),
        "media_uuid": newest.get("media_uuid"),
        "purchased": False,
    }


def lock_status_prompt_block(status: Dict[str, Any]) -> str:
    """Loud prompt block — Emma must know active lock OR none."""
    if not status or not status.get("active"):
        return (
            "LOCK STATUS — VERIFIED THIS TURN:\n"
            "- NO unpaid timed lock is waiting in this chat right now.\n"
            "- HARD BAN: do NOT invent a candado, unlock-above, price ($XX), "
            "or countdown (20 min / 15 minutitos / 'vence en…').\n"
            "- Text-only urgency is a lie. Only mention a timed lock if THIS turn "
            f"actually attaches a NEW paid lock (~{expire_minutes()} min). "
            "If no photo attaches this turn → flirt/comfort only, zero invent."
        )

    label = status.get("label") or "your locked photo"
    price = status.get("price")
    price_txt = f" (${price:.0f})" if isinstance(price, (int, float)) else ""
    mins = status.get("minutes_left")
    if mins is None:
        time_txt = "timed — it will disappear if he waits"
    elif mins <= 0:
        time_txt = "about to disappear / already expired — urgency NOW"
    elif mins <= 5:
        time_txt = f"~{mins} min left — almost gone"
    else:
        time_txt = f"~{mins} min left before it disappears"
    ago = status.get("ago") or "recently"
    extra = ""
    if int(status.get("count") or 1) > 1:
        extra = (
            f"\n- NOTE: chat had {status['count']} unpaid locks; extras are being cleared. "
            "Only talk about THIS one."
        )
    return (
        "LOCK STATUS — VERIFIED THIS TURN (ACTIVE UNPAID CANDADO):\n"
        f"- ONE timed lock is waiting — \"{label}\"{price_txt} (sent {ago}).\n"
        f"- Clock: {time_txt}.\n"
        "- PERSIST on THIS unlock. Do NOT send a second lock. Do NOT claim he already saw it.\n"
        "- Light FOMO OK — never beg, never invent fake glitches."
        f"{extra}"
    )


def unsend_lock(
    fv: "FanvueConnector",
    fan_uuid: str,
    msg_uuid: str,
    *,
    handle: str = "",
    label: str = "",
) -> bool:
    """Public: delete one chat message (unsend unpaid PPV)."""
    return _delete_one(
        fv, fan_uuid, msg_uuid, handle=handle, label=label
    )


def _delete_one(
    fv: "FanvueConnector",
    fan_uuid: str,
    msg_uuid: str,
    *,
    handle: str = "",
    label: str = "",
) -> bool:
    try:
        fv.delete_message(fan_uuid, msg_uuid)
        print(
            f"   ⏳ PPV unsent @{handle or fan_uuid[:8]}: "
            f"{(label or '')[:40]} (msg {msg_uuid[:8]}…)"
        )
        return True
    except Exception as e:
        err = str(e)
        if "400" in err or "purchased" in err.lower() or "403" in err:
            print(f"   ⏳ PPV cannot delete @{handle}: {e}")
            return False
        print(f"   ❌ PPV delete @{handle}: {type(e).__name__}: {e}")
        return False


def sync_pending_from_lock(
    fan_uuid: str,
    lock: dict,
    *,
    fan_handle: str = "",
    label: str = "",
) -> None:
    """Keep memory clock aligned with the newest unpaid lock in chat."""
    fan_memory.set_pending_ppv_from_chat(
        fan_uuid,
        media_uuid=lock.get("media_uuid") or "",
        message_uuid=lock.get("message_uuid") or "",
        price=lock.get("price"),
        label=label,
        sent_at=lock.get("sent_at"),
        fan_handle=fan_handle,
    )


def purge_unpaid_in_chat(
    fv: "FanvueConnector",
    fan_uuid: str,
    creator_uuid: str,
    *,
    handle: str = "",
    keep_newest: bool = False,
    deep: bool = True,
) -> int:
    """
    Delete unpaid locks in one chat (including ancient ones when deep=True).
    keep_newest=False → delete ALL unpaid (clean slate).
    keep_newest=True → delete stacked extras only (keep newest).
    Note: Fanvue refuses delete on already-purchased locks.
    """
    try:
        # Deep: walk far enough back to catch old candados still sitting in chat
        size = 800 if deep else 40
        msgs = fv.get_messages(fan_uuid, size=size)
    except Exception as e:
        print(f"   ⚠️ PPV purge fetch @{handle}: {e}")
        return 0
    unpaid = list_unpaid_locks(
        msgs, creator_uuid, lookback_hours=None if deep else 72
    )
    if not unpaid:
        fan_memory.clear_pending_ppv(
            fan_uuid, fan_handle=handle, reason="purge_none_found"
        )
        return 0
    targets = unpaid[1:] if keep_newest else unpaid
    deleted = 0
    for lock in targets:
        age = ""
        if lock.get("sent_at"):
            age = f" sent={lock['sent_at'][:16]}"
        if _delete_one(
            fv,
            fan_uuid,
            lock["message_uuid"],
            handle=handle,
            label=f"purge{age}",
        ):
            deleted += 1
    if keep_newest and unpaid:
        sync_pending_from_lock(
            fan_uuid, unpaid[0], fan_handle=handle
        )
    else:
        fan_memory.clear_pending_ppv(
            fan_uuid, fan_handle=handle, reason="purged_all"
        )
    return deleted


def _chat_fan(chat: dict) -> tuple:
    """Fanvue list_chats uses `user` (not `fan`). Returns (uuid, handle)."""
    user = chat.get("user") or chat.get("fan") or {}
    fan_uuid = (
        user.get("uuid")
        or chat.get("fanUuid")
        or chat.get("userUuid")
        or chat.get("uuid")
    )
    handle = user.get("handle") or chat.get("handle") or ""
    return fan_uuid, handle


def purge_all_unpaid(
    fv: "FanvueConnector",
    creator_uuid: str,
    *,
    chat_size: int = 50,
) -> int:
    """Wipe every unpaid lock across recent chats + known memory fans."""
    deleted = 0
    scanned = 0
    found = 0
    seen: set = set()

    try:
        chats = fv.list_chats(size=chat_size)
    except Exception as e:
        print(f"   ⚠️ PPV purge list_chats: {e}")
        chats = []

    targets: list = []
    for chat in chats:
        fan_uuid, handle = _chat_fan(chat)
        if not fan_uuid or fan_uuid in seen:
            continue
        seen.add(fan_uuid)
        targets.append((fan_uuid, handle))

    # Memory fans (covers chats missing from the recent list page)
    try:
        all_mem = fan_memory_store_load()
    except Exception:
        all_mem = {}
    for fan_uuid, mem in (all_mem or {}).items():
        if not fan_uuid or fan_uuid in seen:
            continue
        if not isinstance(mem, dict):
            continue
        # Any known fan — ancient locks may still sit in their thread
        if int(mem.get("messages") or 0) > 0 or mem.get("last_ppv_media_uuid"):
            seen.add(fan_uuid)
            targets.append((fan_uuid, mem.get("handle") or ""))

    for fan_uuid, handle in targets:
        if fan_uuid == creator_uuid:
            continue
        scanned += 1
        try:
            msgs = fv.get_messages(fan_uuid, size=800)
        except Exception as e:
            print(f"   ⚠️ PPV purge fetch @{handle or fan_uuid[:8]}: {e}")
            continue
        unpaid = list_unpaid_locks(msgs, creator_uuid, lookback_hours=None)
        if unpaid:
            found += len(unpaid)
            oldest = unpaid[-1].get("sent_at") or "?"
            print(
                f"   ⏳ PPV purge @{handle or fan_uuid[:8]}: "
                f"{len(unpaid)} unpaid (oldest {str(oldest)[:16]})"
            )
        deleted += purge_unpaid_in_chat(
            fv,
            fan_uuid,
            creator_uuid,
            handle=handle,
            keep_newest=False,
            deep=True,
        )

    for fan_uuid, mem in fan_memory.pending_ppv_candidates():
        fan_memory.clear_pending_ppv(
            fan_uuid,
            fan_handle=mem.get("handle") or "",
            reason="purged_all_memory",
        )
    print(
        f"   ⏳ PPV purge-all: scanned {scanned} chat(s), "
        f"found {found} unpaid, deleted {deleted}"
    )
    return deleted


def fan_memory_store_load() -> dict:
    from db import fan_memory_store

    return fan_memory_store.load_all()


def run_pass(fv: "FanvueConnector", creator_uuid: str) -> int:
    """
    Hygiene pass:
    1) Memory-tracked expired locks → unsend
    2) Recent chats: unsend expired unpaid; drop stacked extras (keep newest)
    Returns how many were deleted.
    """
    if not getattr(config, "PPV_EXPIRE_ENABLED", True):
        return 0

    now = datetime.now(timezone.utc)
    deleted = 0
    seen: set = set()

    # --- 1) Memory candidates ---
    for fan_uuid, mem in fan_memory.pending_ppv_candidates():
        seen.add(fan_uuid)
        handle = mem.get("handle") or ""
        expires = _effective_expires(mem)
        msg_uuid = (mem.get("last_ppv_message_uuid") or "").strip()
        media_uuid = (mem.get("last_ppv_media_uuid") or "").strip()

        try:
            msgs = fv.get_messages(fan_uuid, size=40)
        except Exception as e:
            print(f"   ⚠️ PPV expire fetch @{handle}: {e}")
            continue

        unpaid = list_unpaid_locks(msgs, creator_uuid)
        # Drop stacked extras immediately
        for extra in unpaid[1:]:
            if _delete_one(
                fv,
                fan_uuid,
                extra["message_uuid"],
                handle=handle,
                label="extra stacked",
            ):
                deleted += 1
        unpaid = list_unpaid_locks(
            fv.get_messages(fan_uuid, size=40), creator_uuid
        ) if unpaid[1:] else unpaid

        if not unpaid:
            fan_memory.clear_pending_ppv(
                fan_uuid, fan_handle=handle, reason="already_gone"
            )
            continue

        newest = unpaid[0]
        msg_uuid = newest["message_uuid"] or msg_uuid
        sent = _parse_iso(newest.get("sent_at"))
        expires = _effective_expires(mem, sent) or (
            sent + timedelta(minutes=expire_minutes()) if sent else None
        )

        # Sync clock onto newest
        sync_pending_from_lock(
            fan_uuid,
            newest,
            fan_handle=handle,
            label=mem.get("last_ppv_label") or "",
        )

        if expires and expires > now:
            continue  # still live — Emma should persist

        # Expired → unsend
        if _delete_one(
            fv,
            fan_uuid,
            msg_uuid,
            handle=handle,
            label=mem.get("last_ppv_label") or "",
        ):
            deleted += 1
            fan_memory.clear_pending_ppv(
                fan_uuid, fan_handle=handle, reason="expired_unsent"
            )
        else:
            # purchased race
            fan_memory.clear_pending_ppv(
                fan_uuid, fan_handle=handle, reason="purchased_or_forbidden"
            )

    # --- 2) Chat scan for orphans not in memory ---
    try:
        chats = fv.list_chats(size=25)
    except Exception:
        chats = []
    for chat in chats:
        fan_uuid, handle = _chat_fan(chat)
        if not fan_uuid or fan_uuid in seen:
            continue
        try:
            msgs = fv.get_messages(fan_uuid, size=30)
        except Exception:
            continue
        unpaid = list_unpaid_locks(msgs, creator_uuid)
        if not unpaid:
            continue
        # extras
        for extra in unpaid[1:]:
            if _delete_one(
                fv,
                fan_uuid,
                extra["message_uuid"],
                handle=handle,
                label="orphan extra",
            ):
                deleted += 1
        unpaid = list_unpaid_locks(msgs, creator_uuid)
        if not unpaid:
            continue
        newest = unpaid[0]
        sent = _parse_iso(newest.get("sent_at"))
        expires = (
            sent + timedelta(minutes=expire_minutes()) if sent else now
        )
        if expires > now:
            sync_pending_from_lock(fan_uuid, newest, fan_handle=handle)
            continue
        if _delete_one(
            fv,
            fan_uuid,
            newest["message_uuid"],
            handle=handle,
            label="orphan expired",
        ):
            deleted += 1
            fan_memory.clear_pending_ppv(
                fan_uuid, fan_handle=handle, reason="orphan_expired"
            )

    return deleted
