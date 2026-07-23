"""
Timed unpaid PPV — scarcity unsend + chat hygiene.

- New locks get last_ppv_expires_at (PPV_EXPIRE_MINUTES, default 60).
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
        return max(1, int(getattr(config, "PPV_EXPIRE_MINUTES", 60) or 60))
    except (TypeError, ValueError):
        return 60


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
    if msg.get("ppv") or msg.get("isPpv") or msg.get("payToView"):
        return True
    return False


def _msg_is_purchased(msg: dict) -> bool:
    """True when Fanvue marks the lock as unlocked/paid by the fan."""
    if msg.get("purchasedAt") or msg.get("unlockedAt"):
        return True
    if msg.get("purchased") is True or msg.get("isPurchased") is True:
        return True
    if msg.get("unlocked") is True or msg.get("isUnlocked") is True:
        return True
    status = str(
        msg.get("purchaseStatus") or msg.get("lockStatus") or ""
    ).lower()
    if status in ("purchased", "unlocked", "paid", "opened"):
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
        if _msg_is_purchased(msg):
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


def memory_pending_lock_status(mem: Optional[dict]) -> Optional[Dict[str, Any]]:
    """
    Fallback when Fanvue chat scan misses the lock but our memory still tracks
    an unpaid timed PPV. Prevents stacking a second sell.
    """
    mem = mem or {}
    if not mem.get("last_ppv_pending"):
        return None
    media = (mem.get("last_ppv_media_uuid") or "").strip()
    msg_uuid = (mem.get("last_ppv_message_uuid") or "").strip()
    if not media and not msg_uuid:
        return None

    now = datetime.now(timezone.utc)
    expires = _effective_expires(mem)
    # Grace: keep treating as unpaid until expire + 2 min (scan lag / clock skew)
    if expires and now > expires + timedelta(minutes=2):
        return None

    mins = minutes_remaining(expires, now)
    sent = _parse_iso(mem.get("last_ppv_at"))
    ago = None
    if sent:
        age_m = int((now - sent).total_seconds() // 60)
        ago = f"{age_m} min ago" if age_m < 120 else f"{age_m // 60}h ago"

    price = mem.get("last_ppv_price")
    try:
        price = float(price) if price is not None else None
    except (TypeError, ValueError):
        price = None

    return {
        "active": True,
        "count": 1,
        "label": mem.get("last_ppv_label") or "",
        "price": price,
        "minutes_left": mins,
        "expires_at": expires.isoformat() if expires else None,
        "ago": ago or "recently",
        "sent_at": mem.get("last_ppv_at"),
        "message_uuid": msg_uuid or None,
        "media_uuid": media or None,
        "purchased": False,
        "source": "memory",
    }


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
            "- SYSTEM TRUTH: if fan CLAIMS he bought/opened/liked/disliked a previous PPV "
            "('me ha gustado la última foto', 'ya la vi', 'liked that photo') "
            "but he never purchased — that claim is FALSE. He never unlocked it; "
            "he cannot have seen it. Do NOT say 'me alegro que te gustara' / "
            "'glad you liked it' / 'esa era solo un poquito'. Call the bluff playfully.\n"
            "- Do NOT apologize for content he never bought. Do NOT offer refunds or replacements.\n"
            "- HARD BAN: do NOT invent a candado, unlock-above, price ($XX), "
            "or countdown (20 min / 15 minutitos / 'vence en…' / 'quedan X min').\n"
            "- If a NEW lock attaches this turn, urgency = 'limited time' / 'rápido' — "
            "never quote minutes or hours to him.\n"
            "- Text-only urgency is a lie. Only mention a timed lock if THIS turn "
            "actually attaches a NEW paid lock. "
            "If no photo attaches this turn → flirt/comfort only, zero invent."
        )

    label = status.get("label") or "your locked photo"
    price = status.get("price")
    mins = status.get("minutes_left")
    if mins is not None and mins <= 0:
        urgency_txt = "almost gone — push NOW (limited time; do NOT name minutes)"
    elif mins is not None and mins <= 15:
        urgency_txt = "running out — limited time / rápido (do NOT quote how many minutes)"
    else:
        urgency_txt = "limited time — he should open soon (do NOT quote a countdown)"
    ago = status.get("ago") or "recently"
    extra = ""
    if int(status.get("count") or 1) > 1:
        extra = (
            f"\n- NOTE: chat had {status['count']} unpaid locks; extras are being cleared. "
            "Only talk about THIS one."
        )
    return (
        "LOCK STATUS — VERIFIED THIS TURN (ACTIVE UNPAID CANDADO):\n"
        f"- ONE timed lock is waiting — \"{label}\".\n"
        f"- How long it's BEEN in chat: {ago}. That is the ONLY wait time you may use if he challenges timing.\n"
        f"- Urgency to fan: {urgency_txt}.\n"
        "- HARD BAN: never tell him minutes/hours left ('quedan 20 min', '30 minutes', etc.). "
        "Say limited time / por tiempo limitado / rápido / antes de que desaparezca — no numbers.\n"
        "- HARD BAN: do NOT invent wait times (e.g. '27 minutes waiting') that contradict "
        f"'sent {ago}'. Internal clock is NOT for him — limited-time vibe only.\n"
        "- If he corrects the timing, agree with LOCK STATUS (the 'sent … ago' line), don't shrug it off.\n"
        "- SYSTEM TRUTH: He has NOT paid yet. Fan saying 'sí', 'dale', 'lo abro', 'ya', "
        "'me ha gustado', 'liked the photo', or any affirmative word is NOT a purchase — "
        "only the system confirms that.\n"
        "- Do NOT act as if he bought it. Do NOT say 'gracias', 'ya la ves', "
        "'me alegro que te gustara', or 'qué te parece'.\n"
        "- If fan INSULTS or REJECTS the content ('is trash', 'not worth it', 'no me gusta', 'very bad'): "
        "he hasn't opened it — he literally cannot know. Stay confident: call him out playfully, "
        "dare him to actually open it before judging. Never apologize for unseen content.\n"
        "- If fan says 'I won't pay MORE' or 'I already paid enough': CLIENT CARD shows $0 spent — "
        "he has paid NOTHING. Do not validate fake spending history. Playfully correct him or ignore it.\n"
        "- The price is VISIBLE in the lock itself — do NOT repeat $ amounts in text.\n"
        "- Don't obsess over the lock every message — warm human chat first.\n"
        "- THIS is the ONLY product in play if you mention content — scroll up. Soft nudge max.\n"
        "- HARD BAN: do NOT tease/send/offer a DIFFERENT photo, 'another one', or a new lock.\n"
        "- HARD BAN: do NOT promise video, clip, bundle, or 'both for $X'. Photos only.\n"
        "- If he asks gratis/free: NO more free — that waiting lock is the only option.\n"
        "- Never beg, never invent glitches, never FOMO-spam every turn."
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

        if not fan_memory.is_real_fan_uuid(fan_uuid):
            fan_memory.clear_pending_ppv(
                fan_uuid, fan_handle=handle, reason="junk_fan_uuid"
            )
            print(f"   PPV expire: drop junk fan {fan_uuid[:24]!r}")
            continue
        try:
            msgs = fv.get_messages(fan_uuid, size=40)
        except Exception as e:
            err = str(e)
            print(f"   ⚠️ PPV expire fetch @{handle}: {e}")
            # Invalid test UUIDs / gone fans — stop retrying every poll
            if (
                "invalid_format" in err
                or "Invalid userUuid" in err
                or "404" in err
            ):
                fan_memory.clear_pending_ppv(
                    fan_uuid, fan_handle=handle, reason="expire_fetch_invalid"
                )
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
