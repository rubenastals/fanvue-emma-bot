"""
Poll Fanvue inbox and auto-reply as Emma.

Design:
- DeepSeek gets prompt + real chat history (coherence + full freedom).
- Long replies are split into several short chat bubbles (never a wall of text).
- SIGTERM/SIGINT drains: finish the current fan turn, release Redis lock, exit.
"""
import argparse
import contextlib
import json
import os
import random
import re
import signal
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from api.fanvue_connector import FanvueConnector
from api.fanvue_oauth import load_tokens
from config import config
from core import (
    convo_log,
    fan_memory,
    fan_vision,
    lorebook,
    memory_extractor,
    offer_selector,
    ppv_expiry,
    reengagement,
    vault_catalog,
)
from core.reply_engine import (
    _parse_msg_time,
    fanvue_messages_to_turns,
    filter_messages_for_context,
    generate_emma_reply,
    split_into_messages,
)
from core.reply_v2 import generate_reply_v2
from core.intent_router import route as route_intent
from core.turn_policy import decide_turn  # noqa: F401 — kept for scripts/tests
from db import account_id, processed_store, use_postgres, use_redis
from db import redis_client as redis_store

# Graceful shutdown: finish in-flight turn, then stop accepting new chats.
_shutting_down = False
_in_fan_turn = False


def _request_shutdown(signum=None, frame=None) -> None:
    global _shutting_down
    if _shutting_down:
        return
    _shutting_down = True
    where = "after current turn" if _in_fan_turn else "now"
    print(f"\n⏳ shutdown signal — draining {where}…", flush=True)


def shutting_down() -> bool:
    return _shutting_down


def _load_processed() -> set:
    return processed_store.load()


def _save_processed(processed: set) -> None:
    processed_store.save(processed)


def _mark_processed(processed: set, msg_uuid: str) -> None:
    processed_store.add(msg_uuid, processed)


def _sender_uuid(msg: dict):
    sender = msg.get("sender")
    if isinstance(sender, dict):
        return sender.get("uuid")
    if isinstance(sender, str):
        return sender
    return None


# Only fact-check the most recent PPV, and only while it's still "current".
PPV_CHECK_WINDOW_HOURS = int(os.getenv("PPV_CHECK_WINDOW_HOURS", "48"))


def _record_verified_ppv(
    fv: FanvueConnector,
    *,
    fan_uuid: str,
    fan_handle: str,
    creator_uuid: str,
    offer: dict,
    price: float,
    send_resp: Optional[dict] = None,
) -> Optional[str]:
    """Persist unpaid lock + message uuid for timed unsend. Returns message_uuid."""
    aliases = [
        u
        for u in (offer.get("media_uuid"), offer.get("media_uuid_previous"))
        if u
    ]
    msg_uuid = ppv_expiry.resolve_ppv_message_uuid(
        fv,
        fan_uuid,
        creator_uuid=creator_uuid,
        media_uuid=offer["media_uuid"],
        send_resp=send_resp,
        aliases=aliases,
    )
    fan_memory.set_last_offer(
        fan_uuid,
        price,
        fan_handle=fan_handle,
        level=int(offer["level"]),
        media_uuid=offer["media_uuid"],
        label=offer.get("label") or "",
        message_uuid=msg_uuid,
    )
    return msg_uuid


def _check_last_ppv(messages: list, creator_uuid: str, mem: dict):
    """
    Truth-check locks in THIS chat via Fanvue messages + memory fallback.
    Returns purchased status, or LOCK STATUS (active timed unpaid / none).
    """
    unpaid = ppv_expiry.list_unpaid_locks(
        messages,
        creator_uuid,
        lookback_hours=PPV_CHECK_WINDOW_HOURS,
    )
    # Newest priced message overall (paid or unpaid) for purchase detect
    newest_priced = None
    for msg in messages:  # newest-first
        if _sender_uuid(msg) != creator_uuid:
            continue
        if not ppv_expiry._msg_has_pricing(msg):
            continue
        media = msg.get("mediaUuids") or []
        if not media:
            for m in msg.get("media") or []:
                if isinstance(m, dict) and m.get("uuid"):
                    media.append(m["uuid"])
        if not media:
            continue
        sent_raw = msg.get("sentAt") or msg.get("createdAt")
        try:
            sent_at = datetime.fromisoformat(str(sent_raw).replace("Z", "+00:00"))
        except (ValueError, TypeError):
            continue
        age = datetime.now(timezone.utc) - sent_at
        if age > timedelta(hours=PPV_CHECK_WINDOW_HOURS):
            break
        newest_priced = msg
        break

    # Tracked message uuid purchased in chat → clear unpaid
    tracked_msg = (mem.get("last_ppv_message_uuid") or "").strip()
    if tracked_msg and mem.get("last_ppv_pending"):
        for msg in messages or []:
            if (msg.get("uuid") or "").strip() != tracked_msg:
                continue
            if ppv_expiry._msg_is_purchased(msg):
                price = ppv_expiry._msg_price_dollars(msg)
                sent_at = ppv_expiry._msg_sent_at(msg)
                minutes = 0
                if sent_at:
                    minutes = int(
                        (datetime.now(timezone.utc) - sent_at).total_seconds()
                        // 60
                    )
                ago = (
                    f"{minutes} min ago"
                    if minutes < 120
                    else f"{minutes // 60}h ago"
                )
                return {
                    "purchased": True,
                    "active": False,
                    "label": mem.get("last_ppv_label") or "",
                    "price": price
                    if price is not None
                    else mem.get("last_ppv_price"),
                    "ago": ago,
                    "message_uuid": tracked_msg,
                    "source": "tracked_purchase",
                }
            break

    if (
        newest_priced
        and ppv_expiry._msg_is_purchased(newest_priced)
        and not unpaid
    ):
        price = ppv_expiry._msg_price_dollars(newest_priced)
        sent_at = ppv_expiry._msg_sent_at(newest_priced)
        minutes = 0
        if sent_at:
            minutes = int(
                (datetime.now(timezone.utc) - sent_at).total_seconds() // 60
            )
        ago = f"{minutes} min ago" if minutes < 120 else f"{minutes // 60}h ago"
        label = ""
        if (newest_priced.get("mediaUuids") or [None])[0] == mem.get(
            "last_ppv_media_uuid"
        ):
            label = mem.get("last_ppv_label") or ""
        return {
            "purchased": True,
            "active": False,
            "label": label,
            "price": price if price is not None else mem.get("last_ppv_price"),
            "ago": ago,
            "source": "chat_purchase",
        }

    status = ppv_expiry.build_lock_status(unpaid_locks=unpaid, mem=mem)
    status["purchased"] = False
    if status.get("active"):
        status["source"] = "chat"
        return status

    # Chat scan empty/missed — trust our pending clock so we never stack sells
    mem_lock = ppv_expiry.memory_pending_lock_status(mem)
    if mem_lock:
        return mem_lock

    status["purchased"] = False
    return status


def _fan_message_text(msg: dict) -> str:
    """Text body, or a stub when the fan sent media with no caption."""
    text = (msg.get("text") or "").strip()
    if text:
        return text
    has_media = bool(msg.get("hasMedia") or msg.get("mediaUuids"))
    if not has_media:
        return ""
    # Priced media from fan is rare; treat as photo/video share
    mtype = (msg.get("mediaType") or "").lower()
    if "video" in mtype:
        return "[fan sent a video]"
    return "[fan sent a photo]"


def _pending_fan_messages(messages: list, fan_uuid: str, processed: set) -> list:
    """
    Fan messages not yet answered — newest first.

    Includes media-only (no caption). Critical: do NOT require messages[0]
    to be from the fan — if Emma already bubbled after he wrote, his msg
    sits in the middle and must still be answered.

    Unstick: if the fan spoke LAST but that uuid was marked processed without
    a later Emma reply (crash / empty send), retry it.
    """
    pending = []
    for msg in messages:
        if _sender_uuid(msg) != fan_uuid:
            continue
        uid = msg.get("uuid")
        text = _fan_message_text(msg)
        if not uid or not text or uid in processed:
            continue
        pending.append(msg)

    if not pending and messages:
        newest = messages[0]
        if _sender_uuid(newest) == fan_uuid:
            uid = newest.get("uuid")
            text = _fan_message_text(newest)
            if uid and text and uid in processed:
                print(
                    f"   ♻️ unstick: fan spoke last (msg {uid[:8]}…) "
                    "was marked processed with no Emma reply after — retrying"
                )
                processed_store.remove(uid, processed)
                pending = [newest]
    return pending


def _human_bubble_delay(text: str, *, first: bool) -> float:
    """Human typing pause scaled to the bubble length."""
    n = len(text or "")
    if first:
        lo = float(getattr(config, "BUBBLE_DELAY_FIRST_MIN", 4.0))
        hi = float(getattr(config, "BUBBLE_DELAY_FIRST_MAX", 6.5))
        delay = lo + min(1.8, n / 70.0) + random.uniform(0.0, 0.7)
        return min(hi, max(lo, delay))
    lo = float(getattr(config, "BUBBLE_DELAY_NEXT_MIN", 2.8))
    hi = float(getattr(config, "BUBBLE_DELAY_NEXT_MAX", 4.8))
    delay = lo + min(1.4, n / 85.0) + random.uniform(0.0, 0.6)
    return min(hi, max(lo, delay))


def _sleep_interruptible(
    fv: FanvueConnector,
    fan_uuid: str,
    processed: set,
    seconds: float,
    *,
    known_ids: set,
    keep_typing: bool = True,
) -> bool:
    """
    Sleep for ~`seconds` wall-clock. Typing pings are cheap; Fanvue message
    polls are rare (API latency was stacking and making delays feel eternal).
    Returns True if a NEW fan message appeared (barge-in).
    """
    end = time.time() + max(0.0, seconds)
    last_ping = 0.0
    last_barge = 0.0
    ping_every = max(1.5, float(getattr(config, "TYPING_PING_SEC", 2.5)))
    barge_every = max(2.0, float(getattr(config, "BUBBLE_BARGE_CHECK_SEC", 3.0)))
    if keep_typing:
        try:
            fv.send_typing_indicator(fan_uuid, True)
            last_ping = time.time()
        except Exception:
            pass
    while time.time() < end:
        now = time.time()
        if keep_typing and (now - last_ping) >= ping_every:
            try:
                fv.send_typing_indicator(fan_uuid, True)
            except Exception:
                pass
            last_ping = now
        # Pure sleep — do NOT call Fanvue every tick
        chunk = min(0.4, end - time.time())
        if chunk <= 0:
            break
        time.sleep(chunk)
        now = time.time()
        if now - last_barge < barge_every:
            continue
        last_barge = now
        try:
            msgs = fv.get_messages(fan_uuid, size=5)
        except Exception:
            continue
        for msg in _pending_fan_messages(msgs, fan_uuid, processed):
            if msg.get("uuid") not in known_ids:
                return True
    return False


def _newest_fan_ts(messages: list, fan_uuid: str):
    for msg in messages:  # newest-first
        if _sender_uuid(msg) == fan_uuid:
            return _parse_msg_time(msg)
    return None


def _wait_for_fan_to_finish(
    fv: FanvueConnector,
    fan_uuid: str,
    processed: set,
    pending: list,
) -> list:
    """
    Coalesce a burst: if he JUST wrote, wait a quiet window for more messages
    before replying, so we answer the whole batch as one turn.

    Returns the (possibly larger) pending list, newest-first.
    """
    if not getattr(config, "COALESCE_ENABLED", True) or not pending:
        return pending

    newest_ts = _newest_fan_ts(pending, fan_uuid)
    if newest_ts is not None:
        age = (datetime.now(timezone.utc) - newest_ts).total_seconds()
        # He's catching-up mail, not typing live → answer now.
        if age > getattr(config, "COALESCE_FRESH_SEC", 20):
            return pending

    settle = float(getattr(config, "COALESCE_SETTLE_SEC", 6))
    max_wait = float(getattr(config, "COALESCE_MAX_WAIT_SEC", 25))
    known = {m.get("uuid") for m in pending if m.get("uuid")}
    started = time.time()
    print(f"   ⏳ coalesce: waiting {settle:.0f}s quiet (max {max_wait:.0f}s)…")

    # Keep Emma "typing" while we wait so he feels her writing back.
    with _typing_keepalive(fv, fan_uuid):
        while time.time() - started < max_wait:
            if not _sleep_interruptible(
                fv, fan_uuid, processed, settle, known_ids=known
            ):
                break  # quiet window elapsed with no new message → he's done
            try:
                msgs = fv.get_messages(fan_uuid, size=100)
            except Exception:
                break
            fresh = _pending_fan_messages(msgs, fan_uuid, processed)
            new_ids = {m.get("uuid") for m in fresh}
            if new_ids - known:
                known = new_ids
                pending = fresh
                print(f"   ⏳ coalesce: absorbed more ({len(fresh)}) — waiting again")
    return pending


@contextlib.contextmanager
def _typing_keepalive(fv: FanvueConnector, fan_uuid: str):
    """
    Keep the 'Emma is typing…' indicator alive on Fanvue for the whole block
    (analysis + coalesce). Fanvue's indicator self-expires, so we re-ping it.
    """
    if not getattr(config, "TYPING_WHILE_THINKING", True):
        yield
        return
    stop = threading.Event()
    ping = max(1.5, float(getattr(config, "TYPING_PING_SEC", 4)))

    def _loop() -> None:
        while not stop.is_set():
            try:
                fv.send_typing_indicator(fan_uuid, True)
            except Exception:
                pass
            stop.wait(ping)

    t = threading.Thread(target=_loop, daemon=True)
    t.start()
    try:
        yield
    finally:
        stop.set()
        with contextlib.suppress(Exception):
            fv.send_typing_indicator(fan_uuid, False)


def _handle_fan_chat(
    fv: FanvueConnector,
    processed: set,
    creator_uuid: str,
    fan_uuid: str,
    fan_handle: str,
) -> int:
    """
    Drain all pending fan messages for one chat (including ones buried under
    Emma's own bubbles). Returns how many reply turns were sent.
    """
    # Drain: do not start a NEW fan turn after SIGTERM; finish only if already in body.
    if shutting_down():
        return 0
    global _in_fan_turn
    _in_fan_turn = True
    try:
        return _handle_fan_chat_body(fv, processed, creator_uuid, fan_uuid, fan_handle)
    finally:
        _in_fan_turn = False


def _handle_fan_chat_body(
    fv: FanvueConnector,
    processed: set,
    creator_uuid: str,
    fan_uuid: str,
    fan_handle: str,
) -> int:
    handled = 0
    # Cap turns per poll so one chat can't starve others
    for _ in range(4):
        # Finish the turn we already started; do not open another reply cycle while draining.
        if shutting_down() and handled > 0:
            break
        messages = fv.get_messages(fan_uuid, size=100)
        if not messages:
            break

        pending = _pending_fan_messages(messages, fan_uuid, processed)
        if not pending:
            break

        # Coalesce a live burst: wait for him to finish, keep "typing…" on.
        pending = _wait_for_fan_to_finish(fv, fan_uuid, processed, pending)
        if shutting_down() and handled > 0:
            break
        # Re-fetch so context/turns include everything absorbed during the wait.
        messages = fv.get_messages(fan_uuid, size=100) or messages
        pending = _pending_fan_messages(messages, fan_uuid, processed) or pending

        # Oldest → newest so we absorb everything he typed while we were away
        pending_chrono = list(reversed(pending))
        texts = [_fan_message_text(m) for m in pending_chrono]
        text = "\n".join(t for t in texts if t)
        pending_ids = {m["uuid"] for m in pending_chrono if m.get("uuid")}

        hist_hours = int(getattr(config, "HISTORY_HOURS", 36) or 36)
        hist_max = int(getattr(config, "HISTORY_MAX_MESSAGES", 36) or 36)
        hist_min = int(getattr(config, "HISTORY_MIN_MESSAGES", 12) or 12)
        ctx_messages = filter_messages_for_context(
            messages,
            hours=hist_hours,
            max_messages=hist_max,
            min_messages=hist_min,
        )
        turns = fanvue_messages_to_turns(
            ctx_messages, fan_uuid, creator_uuid, max_messages=hist_max
        )
        print(
            f"   history: {len(turns)} turns "
            f"(≤{hist_max} msgs / {hist_hours}h)"
        )

        mem = fan_memory.observe_message(fan_uuid, fan_handle, text)
        # Sync media Emma already sent in Fanvue history → client card (no repeats)
        synced = fan_memory.merge_sent_from_chat(
            fan_uuid, messages, creator_uuid, fan_handle=fan_handle
        )
        if synced:
            print(f"   sent-sync: +{synced} media uuid(s) from chat history")
            mem = fan_memory.get(fan_uuid) or mem

        # API delivery truth for last free (and aliases) — stops "I sent it" / re-gift lies
        delivery_truth: dict = {"free_in_chat": None, "ppv_unpaid": False}
        last_free_uid = (mem.get("last_free_media_uuid") or "").strip()
        if last_free_uid or (mem.get("sent_media_uuids") and re.search(
            r"(?i)\b(gratis|grastis|free|no ha llegado|nothing arrived|ninguna foto|"
            r"no me has|no me mand)\b",
            text or "",
        )):
            check_uid = last_free_uid
            if not check_uid:
                # Any L0 uuid already on the card
                from core import vault_catalog as _vc

                l0 = {i["media_uuid"] for i in _vc.load_items() if int(i.get("level") or -1) == 0}
                for u in mem.get("sent_media_uuids") or []:
                    if u in l0:
                        check_uid = u
                        break
            if check_uid:
                aliases = []
                for it in vault_catalog.load_items():
                    if it.get("media_uuid") == check_uid or it.get("media_uuid_previous") == check_uid:
                        if it.get("media_uuid"):
                            aliases.append(it["media_uuid"])
                        if it.get("media_uuid_previous"):
                            aliases.append(it["media_uuid_previous"])
                in_chat = fv.creator_media_in_chat(
                    fan_uuid, creator_uuid, check_uid, aliases=aliases
                )
                delivery_truth["free_in_chat"] = in_chat
                print(
                    f"   delivery-check free {check_uid[:8]}…: "
                    f"{'IN CHAT' if in_chat else 'NOT in chat'}"
                )
                if not in_chat:
                    cleared = fan_memory.clear_ghost_free(
                        fan_uuid, check_uid, fan_handle=fan_handle
                    )
                    if cleared:
                        print(
                            f"   ghost-free cleared {check_uid[:8]}… "
                            "(memory claimed gift Fanvue never showed)"
                        )
                        mem = fan_memory.get(fan_uuid) or mem

        # PPV unpaid gate BEFORE route — stop mass stacking
        ppv_status = _check_last_ppv(messages, creator_uuid, mem)
        if ppv_status is not None:
            if ppv_status.get("purchased"):
                print(
                    f"   ppv-check: PURCHASED — "
                    f"{(ppv_status.get('label') or '')[:40]} ({ppv_status.get('ago')})"
                )
                try:
                    fan_memory.clear_pending_ppv(
                        fan_uuid, fan_handle=fan_handle, reason="purchased"
                    )
                except Exception:
                    pass
            elif ppv_status.get("active"):
                mins = ppv_status.get("minutes_left")
                # Already past clock → unsend now so Emma doesn't nag a dead lock
                if mins is not None and mins <= 0 and ppv_status.get("message_uuid"):
                    try:
                        ok = ppv_expiry.unsend_lock(
                            fv,
                            fan_uuid,
                            ppv_status["message_uuid"],
                            handle=fan_handle,
                            label=ppv_status.get("label") or "expired_now",
                        )
                        if ok:
                            fan_memory.clear_pending_ppv(
                                fan_uuid,
                                fan_handle=fan_handle,
                                reason="expired_inline",
                            )
                            print(
                                f"   ppv-check: EXPIRED+UNSENT — "
                                f"{(ppv_status.get('label') or '')[:40]}"
                            )
                            ppv_status = {
                                "active": False,
                                "purchased": False,
                                "count": 0,
                            }
                        else:
                            print(
                                f"   ppv-check: ACTIVE unpaid (expire delete failed) — "
                                f"{(ppv_status.get('label') or '')[:40]}"
                            )
                            delivery_truth["ppv_unpaid"] = True
                    except Exception as e:
                        print(f"   ⚠️ ppv inline expire: {e}")
                        delivery_truth["ppv_unpaid"] = True
                else:
                    print(
                        f"   ppv-check: ACTIVE unpaid — "
                        f"{(ppv_status.get('label') or '')[:40]} "
                        f"({ppv_status.get('ago')}, ~{mins}m left, "
                        f"n={ppv_status.get('count', 1)})"
                    )
                    delivery_truth["ppv_unpaid"] = True
                    try:
                        if ppv_status.get("message_uuid"):
                            ppv_expiry.sync_pending_from_lock(
                                fan_uuid,
                                {
                                    "message_uuid": ppv_status.get("message_uuid"),
                                    "media_uuid": ppv_status.get("media_uuid"),
                                    "price": ppv_status.get("price"),
                                    "sent_at": ppv_status.get("sent_at"),
                                },
                                fan_handle=fan_handle,
                                label=ppv_status.get("label") or "",
                            )
                    except Exception:
                        pass
            else:
                # Do NOT wipe memory pending just because chat scan was empty —
                # that caused stacking a second PPV while the first was still locked.
                if mem.get("last_ppv_pending"):
                    print(
                        "   ppv-check: NO unpaid in chat scan, but memory still "
                        "pending — keeping lock (will not clear / will not stack)"
                    )
                else:
                    print("   ppv-check: NO active unpaid lock")

        snippets = [
            (m.get("text") or "")[:120]
            for m in list(reversed(messages[:12]))
            if (m.get("text") or "").strip()
        ]
        # Router still runs for Group-B truth (unpaid lock / delivery).
        # Soft pack labels are telemetry only when REPLY_V2 — words come from V2 prompt.
        route_result = route_intent(
            mem,
            text,
            delivery_truth=delivery_truth,
            history_snippets=snippets,
        )
        decision = route_result.decision
        # SIMPLE brain owns creative path — REPLY_V2 must not bypass it.
        use_v2 = bool(getattr(config, "REPLY_V2", False)) and not bool(
            getattr(config, "SIMPLE_PROMPT", True)
        )

        preview = text.replace("\n", " | ")[:80]
        print(f"\n📩 @{fan_handle}: {preview}")
        if len(pending_chrono) > 1:
            print(f"   (absorbed {len(pending_chrono)} pending fan msgs)")
        print(
            f"   memory: status={mem.get('status')} spent=${mem.get('total_spent')} "
            f"likes={','.join(mem.get('interests', [])) or '-'}"
        )
        if use_v2:
            print(
                f"   brain=v2 | truth_pack={route_result.pack_id} "
                f"({decision.reason})"
            )
        else:
            print(
                f"   mode: {decision.mode} ({decision.reason}) | pack={route_result.pack_id}"
            )
        if route_result.pack_id in ("reward_purchase",) or (
            ppv_status and ppv_status.get("purchased")
        ):
            try:
                fan_memory.reset_price_objection_step(
                    fan_uuid, fan_handle=fan_handle
                )
            except Exception:
                pass

        # Grok Vision: resolve Fanvue mediaUuids → describe what HE sent
        vision = None
        media_pending = [
            m
            for m in pending_chrono
            if m.get("hasMedia") or m.get("mediaUuids")
        ]
        # Also describe newest fan image in recent history if he's asking what it is
        ask_see = bool(
            re.search(
                r"(?i)\b(qu[eé] (es|ves|hay)|what (is|do you see)|dime que|te gusta)\b",
                text,
            )
        )
        if media_pending or ask_see:
            scan = media_pending or [
                m
                for m in messages
                if _sender_uuid(m) == fan_uuid
                and (m.get("hasMedia") or m.get("mediaUuids"))
            ][:2]
            vision = fan_vision.describe_fan_message_images(
                fv, fan_uuid, scan, max_images=1
            )
            if vision and vision.get("description"):
                fan_memory.set_last_fan_image(
                    fan_uuid,
                    vision["description"],
                    media_uuid=(vision.get("media_uuids") or [None])[0],
                    fan_handle=fan_handle,
                )
                # Enrich stub so DeepSeek's user turn is concrete too
                if "[fan sent a photo]" in text or not (text or "").strip():
                    text = (
                        f"[fan sent a photo]\n"
                        f"(You can see it: {vision['description']})"
                    )
                else:
                    text = (
                        f"{text}\n"
                        f"[attached photo — you see: {vision['description']}]"
                    )

        # CODE-FIRST SELL: pick real vault item BEFORE DeepSeek.
        # Never let allow_price=True reach creative without an offer (or demote).
        offer = None
        _CONVERT_PACKS = frozenset(
            {"phase_close", "lock_now", "escalate_paid", "delivery_missing"}
        )
        unpaid = bool(delivery_truth.get("ppv_unpaid")) or bool(
            ppv_status and ppv_status.get("active")
        )
        # Belt: memory pending with live clock blocks sell even if status glitched
        if not unpaid and mem.get("last_ppv_pending"):
            mem_lock = ppv_expiry.memory_pending_lock_status(mem)
            if mem_lock:
                unpaid = True
                delivery_truth["ppv_unpaid"] = True
                if not (ppv_status and ppv_status.get("active")):
                    ppv_status = mem_lock
                print(
                    f"   SELL: blocked by memory pending lock "
                    f"(~{mem_lock.get('minutes_left')}m left)"
                )

        want_sell = bool(decision.allow_price) or (
            route_result.pack_id in _CONVERT_PACKS
        )
        want_free = bool(getattr(decision, "allow_free_tease", False)) and not want_sell

        # Already got free teases — gratis ask = push paid, never another L0.
        frees_done = int(mem.get("free_teases_sent") or 0)
        from core.turn_policy import _ASK_FREE

        ask_free_now = bool(getattr(route_result.facts, "ask_free", False)) or bool(
            re.search(_ASK_FREE, text or "", re.I)
        )
        if not unpaid and ask_free_now and frees_done >= 2:
            want_free = False
            want_sell = True
            print(
                f"   SELL: gratis refused ({frees_done} free already) — force paid path"
            )

        if unpaid:
            offer = None  # never attach a second lock
            print("   SELL: skipped (unpaid lock already in chat)")
            # Force router pack so creative gets ppv_unpaid rails
            if route_result.pack_id != "ppv_unpaid":
                from core.turn_policy import MODE_TEASE, TurnDecision
                from core.intent_router import RouteResult as _RR

                decision = TurnDecision(
                    mode=MODE_TEASE,
                    reason="unpaid PPV still open — push unlock, don't stack",
                    max_bubbles=2,
                    allow_ppv_talk=True,
                    allow_price=False,
                    allow_free_tease=False,
                )
                route_result = _RR(
                    "ppv_unpaid",
                    decision,
                    route_result.facts,
                    {**(route_result.active or {}), "ppv_unpaid": True},
                )
                try:
                    route_result.facts.ppv_unpaid = True
                except Exception:
                    pass
        elif want_free:
            offer = vault_catalog.select_free_tease(mem)
            if offer:
                print(
                    f"   SELL FREE L0: {offer['label'][:50]} "
                    f"({offer['media_uuid'][:8]}…)"
                )
            else:
                print("   SELL FREE L0: none left — flirt only")
        elif want_sell:
            selection = offer_selector.choose_offer(
                mem,
                text,
                history_turns=turns,
                facts=route_result.facts,
            )
            offer = selection.offer if selection.sell_now else None
            if offer is not None:
                print(
                    f"   SELL: L{offer['level']} ${float(offer['price']):.0f} "
                    f"{offer['label'][:50]} ({offer['media_uuid'][:8]}…) "
                    f"[{selection.source} {selection.confidence:.2f}]"
                )
            else:
                # Demote — selector says timing is wrong OR inventory exhausted.
                from core.turn_policy import MODE_TEASE, TurnDecision
                from core.intent_router import RouteResult as _RR

                print(
                    f"   SELL demote: {selection.reason[:100]} "
                    "→ phase_pull (no price)"
                )
                decision = TurnDecision(
                    mode=MODE_TEASE,
                    reason=f"demote: {selection.reason[:120]}",
                    max_bubbles=2,
                    allow_ppv_talk=True,
                    allow_price=False,
                    allow_free_tease=False,
                )
                route_result = _RR(
                    "phase_pull",
                    decision,
                    route_result.facts,
                    {**(route_result.active or {}), "phase_pull": True},
                )

        try:
            # Keep "Emma is typing…" alive during the (multi-second) DeepSeek call.
            with _typing_keepalive(fv, fan_uuid):
                if use_v2:
                    reply, decision, offer = generate_reply_v2(
                        text,
                        history_turns=turns,
                        fan_handle=fan_handle,
                        fan_uuid=fan_uuid,
                        offer=offer,
                        ppv_status=ppv_status,
                        delivery_truth=delivery_truth,
                        route_result=route_result,
                        fan_vision=vision,
                        catalog_locked=True,  # poller already decided offer/demote
                    )
                    if offer:
                        print(
                            f"   attach: L{offer.get('level')} "
                            f"${float(offer.get('price') or 0):.0f} "
                            f"{(offer.get('label') or '')[:40]}"
                        )
                else:
                    reply, decision = generate_emma_reply(
                        text,
                        history_turns=turns,
                        fan_handle=fan_handle,
                        fan_uuid=fan_uuid,
                        decision=decision,
                        offer=offer,
                        ppv_status=ppv_status,
                        fan_vision=vision,
                        delivery_truth=delivery_truth,
                        pack_id=route_result.pack_id,
                        route_result=route_result,
                    )
        except Exception as e:
            import traceback

            print(f"   ❌ generate reply failed: {type(e).__name__}: {e}")
            traceback.print_exc()
            break

        max_bubbles = int(
            getattr(decision, "max_bubbles", None)
            or getattr(config, "MAX_BUBBLES", 3)
            or 3
        )
        bubbles = split_into_messages(
            reply,
            max_len=int(getattr(config, "BUBBLE_MAX_CHARS", 200) or 200),
            max_bubbles=max_bubbles,
            vary=True,
        )
        print(
            f"💬 Emma ({len(bubbles)} msg, ≤{getattr(config, 'BUBBLE_MAX_CHARS', 200)}c) "
            f"[{decision.mode}]: {reply[:120]}"
        )

        # Do NOT mark processed until we actually send — otherwise a crash/empty
        # reply permanently silences the fan.
        if not (reply or "").strip() or not bubbles:
            print("   ⚠️ empty reply — NOT marking processed; will retry next poll")
            break

        barged = False
        bubbles_sent = 0
        free_sent = False
        ppv_sent = False
        is_free_offer = bool(
            offer
            and (
                float(offer.get("price") or 0) <= 0
                or int(offer.get("level") or 0) == 0
            )
        )
        # Absolute hard stop: never attach a new paid lock while one is unpaid
        if unpaid and offer and not is_free_offer:
            print(
                "   🛑 HARD BLOCK: unpaid lock still open — refusing new PPV attach"
            )
            offer = None
        is_paid_offer = bool(offer and not is_free_offer)

        # FREE L0: attach image WITH the first bubble so barge-in can't skip the gift
        # after Emma already teased it in text.
        if is_free_offer and bubbles and not barged:
            media_text = (bubbles[0] or "").strip() or "😏"
            rest_bubbles = bubbles[1:]
            delay = _human_bubble_delay(media_text, first=True)
            interrupted = _sleep_interruptible(
                fv, fan_uuid, processed, delay, known_ids=pending_ids, keep_typing=True
            )
            try:
                fv.send_media_message(
                    fan_uuid,
                    media_uuids=[offer["media_uuid"]],
                    text=media_text[:500],
                    fallback_uuids=[offer.get("media_uuid_previous")]
                    if offer.get("media_uuid_previous")
                    else None,
                )
                # Verify Fanvue actually shows this media in chat before marking sent
                time.sleep(1.0)
                aliases = [
                    u
                    for u in (
                        offer.get("media_uuid"),
                        offer.get("media_uuid_previous"),
                    )
                    if u
                ]
                verified = fv.creator_media_in_chat(
                    fan_uuid,
                    creator_uuid,
                    offer["media_uuid"],
                    aliases=aliases,
                )
                if verified:
                    fan_memory.record_free_tease(
                        fan_uuid,
                        offer["media_uuid"],
                        fan_handle=fan_handle,
                        label=offer.get("label") or "",
                        level=int(offer.get("level") or 0),
                    )
                    free_sent = True
                    print(
                        f"   🎁 FREE L0 verified in chat — {offer['label']}"
                    )
                else:
                    # Do NOT claim delivery in memory — that creates ghost gifts
                    fan_memory.mark_media_attempt(
                        fan_uuid,
                        offer["media_uuid"],
                        fan_handle=fan_handle,
                    )
                    free_sent = False
                    print(
                        f"   ❌ FREE L0 API returned OK but media NOT in chat — "
                        f"{offer['label']} (not marked sent)"
                    )
                    try:
                        want_es = bool(mem.get("prefer_spanish"))
                        apology = (
                            "Uy… se me trabó al mandarla. Un segundo que lo arreglo 🥺"
                            if want_es
                            else "Ugh… glitched while sending. One sec, I'll drop it properly 🥺"
                        )
                        fv.send_message(fan_uuid, apology)
                    except Exception:
                        pass
                bubbles_sent += 1
                print(f"   ✅ [1/{len(bubbles)}] (+{delay:.1f}s) {media_text[:60]}")
            except Exception as e:
                print(f"   ❌ FREE send failed: {type(e).__name__}: {e}")
                try:
                    fan_memory.mark_media_attempt(
                        fan_uuid,
                        offer["media_uuid"],
                        fan_handle=fan_handle,
                    )
                except Exception:
                    pass
                try:
                    want_es = bool(mem.get("prefer_spanish"))
                    apology = (
                        "Uy… se me trabó el chat un segundo. Dame un momento y te la dejo bien 🥺"
                        if want_es
                        else "Ugh… chat glitched for a sec. Give me a moment and I'll drop it properly 🥺"
                    )
                    fv.send_message(fan_uuid, apology)
                except Exception:
                    pass
                # Don't send tease bubbles that promised a photo that never attached
                rest_bubbles = []
            try:
                fv.send_typing_indicator(fan_uuid, False)
            except Exception:
                pass
            if interrupted:
                print("   ⏭ barge-in after free gift — stopping remaining bubbles")
                barged = True
                rest_bubbles = []
            bubbles = rest_bubbles
            offer = None  # free path handled (success or fail)

        # PAID PPV: lock WITH first bubble — text-then-lock was skipped by barge-in
        # and media-only locks sometimes rendered empty.
        if is_paid_offer and bubbles and not barged and offer:
            media_text = (bubbles[0] or "").strip() or "🔒"
            rest_bubbles = bubbles[1:]
            delay = _human_bubble_delay(media_text, first=True)
            interrupted = _sleep_interruptible(
                fv, fan_uuid, processed, delay, known_ids=pending_ids, keep_typing=True
            )
            price = max(3.0, float(offer["price"]))
            try:
                send_resp = fv.send_ppv_message(
                    fan_uuid,
                    media_uuids=[offer["media_uuid"]],
                    price_dollars=price,
                    text=media_text[:500],
                    fallback_uuids=[offer.get("media_uuid_previous")]
                    if offer.get("media_uuid_previous")
                    else None,
                )
                time.sleep(1.2)
                aliases = [
                    u
                    for u in (
                        offer.get("media_uuid"),
                        offer.get("media_uuid_previous"),
                    )
                    if u
                ]
                verified = fv.creator_media_in_chat(
                    fan_uuid,
                    creator_uuid,
                    offer["media_uuid"],
                    aliases=aliases,
                )
                if verified:
                    msg_uuid = _record_verified_ppv(
                        fv,
                        fan_uuid=fan_uuid,
                        fan_handle=fan_handle,
                        creator_uuid=creator_uuid,
                        offer=offer,
                        price=price,
                        send_resp=send_resp if isinstance(send_resp, dict) else None,
                    )
                    ppv_sent = True
                    mins = int(getattr(config, "PPV_EXPIRE_MINUTES", 30))
                    print(
                        f"   🔒 PPV verified in chat L{offer['level']} "
                        f"${price:.0f} — {offer['label']}"
                        + (
                            f" (expires {mins}m, msg {msg_uuid[:8]}…)"
                            if msg_uuid
                            else f" (expires {mins}m)"
                        )
                    )
                else:
                    fan_memory.mark_media_attempt(
                        fan_uuid,
                        offer["media_uuid"],
                        fan_handle=fan_handle,
                    )
                    print(
                        f"   ❌ PPV API OK but lock NOT in chat — "
                        f"{offer['label']} (not marked sent)"
                    )
                    try:
                        want_es = bool(mem.get("prefer_spanish"))
                        apology = (
                            "Uy… se me trabó el candado. Dame un segundo y te lo dejo bien 🥺"
                            if want_es
                            else "Ugh… lock glitched. One sec and I'll drop it properly 🥺"
                        )
                        fv.send_message(fan_uuid, apology)
                    except Exception:
                        pass
                    rest_bubbles = []
                bubbles_sent += 1
                print(f"   ✅ [1/{len(bubbles)}] (+{delay:.1f}s) {media_text[:60]}")
            except Exception as e:
                print(f"   ❌ PPV send failed: {type(e).__name__}: {e}")
                try:
                    fan_memory.mark_media_attempt(
                        fan_uuid,
                        offer["media_uuid"],
                        fan_handle=fan_handle,
                    )
                except Exception:
                    pass
                try:
                    want_es = bool(mem.get("prefer_spanish"))
                    apology = (
                        "Uy… se me trabó al bloquearla. Un momento y te la dejo 🥺"
                        if want_es
                        else "Ugh… failed locking that one. Give me a moment 🥺"
                    )
                    fv.send_message(fan_uuid, apology)
                except Exception:
                    pass
                rest_bubbles = []
            try:
                fv.send_typing_indicator(fan_uuid, False)
            except Exception:
                pass
            if interrupted:
                print("   ⏭ barge-in after PPV — stopping remaining bubbles")
                barged = True
                rest_bubbles = []
            bubbles = rest_bubbles
            offer = None  # paid path handled

        for i, bubble in enumerate(bubbles):
            first = i == 0 and not free_sent and not ppv_sent
            delay = _human_bubble_delay(bubble, first=first)
            # Typing stays on for EVERY bubble (re-pinged inside sleep)
            interrupted = _sleep_interruptible(
                fv,
                fan_uuid,
                processed,
                delay,
                known_ids=pending_ids,
                keep_typing=True,
            )
            # Always deliver at least one bubble for this turn; abort the rest if he wrote
            fv.send_message(fan_uuid, bubble)
            bubbles_sent += 1
            # Brief pause then typing back on for the next bubble
            if i + 1 < len(bubbles) and not interrupted:
                try:
                    fv.send_typing_indicator(fan_uuid, True)
                except Exception:
                    pass
            else:
                try:
                    fv.send_typing_indicator(fan_uuid, False)
                except Exception:
                    pass
            print(f"   ✅ [{bubbles_sent}] (+{delay:.1f}s) {bubble[:60]}")
            if interrupted:
                print("   ⏭ barge-in: fan wrote mid-reply — stopping remaining bubbles")
                barged = True
                break

        # Mark processed only after at least one bubble / media actually went out
        if bubbles_sent > 0 or free_sent or ppv_sent:
            for uid in pending_ids:
                _mark_processed(processed, uid)
        else:
            print("   ⚠️ no bubble sent — leaving fan msgs unprocessed for retry")

        # Legacy fallback: paid offer still pending (e.g. no bubbles) — verify before memory
        if (
            offer
            and not barged
            and not ppv_sent
            and not is_free_offer
            and not unpaid
        ):
            try:
                fv.send_typing_indicator(fan_uuid, True)
            except Exception:
                pass
            price = max(3.0, float(offer["price"]))
            try:
                send_resp = fv.send_ppv_message(
                    fan_uuid,
                    media_uuids=[offer["media_uuid"]],
                    price_dollars=price,
                    text="🔒",
                    fallback_uuids=[offer.get("media_uuid_previous")]
                    if offer.get("media_uuid_previous")
                    else None,
                )
                time.sleep(1.2)
                verified = fv.creator_media_in_chat(
                    fan_uuid,
                    creator_uuid,
                    offer["media_uuid"],
                    aliases=[
                        u
                        for u in (
                            offer.get("media_uuid"),
                            offer.get("media_uuid_previous"),
                        )
                        if u
                    ],
                )
                if verified:
                    msg_uuid = _record_verified_ppv(
                        fv,
                        fan_uuid=fan_uuid,
                        fan_handle=fan_handle,
                        creator_uuid=creator_uuid,
                        offer=offer,
                        price=price,
                        send_resp=send_resp if isinstance(send_resp, dict) else None,
                    )
                    mins = int(getattr(config, "PPV_EXPIRE_MINUTES", 30))
                    print(
                        f"   🔒 PPV verified (fallback) L{offer['level']} "
                        f"${price:.0f} — {offer['label']}"
                        + (
                            f" (expires {mins}m, msg {msg_uuid[:8]}…)"
                            if msg_uuid
                            else f" (expires {mins}m)"
                        )
                    )
                else:
                    fan_memory.mark_media_attempt(
                        fan_uuid, offer["media_uuid"], fan_handle=fan_handle
                    )
                    print(
                        f"   ❌ PPV fallback API OK but NOT in chat — {offer['label']}"
                    )
            except Exception as e:
                print(f"   ❌ PPV fallback failed: {type(e).__name__}: {e}")
                try:
                    fan_memory.mark_media_attempt(
                        fan_uuid, offer["media_uuid"], fan_handle=fan_handle
                    )
                except Exception:
                    pass
            try:
                fv.send_typing_indicator(fan_uuid, False)
            except Exception:
                pass

        try:
            convo_log.log_turn(
                fan_uuid,
                fan_handle=fan_handle,
                fan_message=text,
                reply=reply,
                bubbles=len(bubbles),
                mode=decision.mode,
                mode_reason=decision.reason,
                offer=offer if not barged else None,
                pack_id=getattr(decision, "pack_id", "")
                or getattr(route_result, "pack_id", ""),
                technique=getattr(decision, "technique", "") or "",
                phase=getattr(decision, "phase", "") or "",
                lock_active=getattr(decision, "lock_active", None),
                scheme_errors=getattr(decision, "scheme_errors", None),
            )
            # Per-turn critic removed — hourly hour_review covers Soft/Hard proposals.
            memory_extractor.update_fan_card_async(fan_uuid, fan_handle)
        except Exception as e:
            print(f"   ⚠️ learning-loop log failed: {e}")

        if route_result.pack_id == "price_objection" and not barged:
            try:
                step = fan_memory.bump_price_objection_step(
                    fan_uuid, fan_handle=fan_handle
                )
                print(f"   objection-step → {step}")
            except Exception:
                pass

        handled += 1
        if not barged:
            # No interruption — done with this fan for this poll
            break
        # else: loop and answer the new pending message immediately

    return handled


def _looks_like_uuid(value: str) -> bool:
    v = (value or "").strip()
    return len(v) >= 32 and v.count("-") >= 4


def poll_once(fv: FanvueConnector, processed: set, creator_uuid: str) -> int:
    if shutting_down():
        return 0
    handled = 0
    chats = fv.list_chats(size=20)
    unread_only = [
        c
        for c in chats
        if not c.get("isRead") or (c.get("unreadMessagesCount") or 0) > 0
    ]
    # Always also scan a few recent chats: unread flags can clear while Emma
    # is mid-send, leaving a buried fan message with isRead=true.
    seen = set()
    candidates = []
    for c in unread_only + chats:
        uid = (c.get("user") or {}).get("uuid")
        if not uid or uid in seen:
            continue
        seen.add(uid)
        candidates.append(c)
        if len(candidates) >= 25:
            break

    # Memory fans (covers chats missing from list_chats page / stuck threads)
    try:
        from db import fan_memory_store

        for fid, mem in (fan_memory_store.load_all() or {}).items():
            if not _looks_like_uuid(fid) or fid in seen or fid == creator_uuid:
                continue
            if not isinstance(mem, dict):
                continue
            if int(mem.get("messages") or 0) < 1:
                continue
            seen.add(fid)
            candidates.append(
                {"user": {"uuid": fid, "handle": mem.get("handle") or "fan"}}
            )
            if len(candidates) >= 40:
                break
    except Exception:
        pass

    for chat in candidates:
        if shutting_down():
            break
        user = chat.get("user", {})
        fan_uuid = user.get("uuid")
        fan_handle = user.get("handle", "fan")
        if not fan_uuid:
            continue
        try:
            handled += _handle_fan_chat(
                fv, processed, creator_uuid, fan_uuid, fan_handle
            )
        except Exception as e:
            import traceback

            print(f"   ❌ handle @{fan_handle} failed: {type(e).__name__}: {e}")
            traceback.print_exc()

    return handled


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--interval", type=int, default=10)
    args = parser.parse_args()

    aid = account_id()

    from config import config as _cfg
    from core.prompt_core import EMMA_CORE_PROMPT_SIMPLE, PROMPT_VERSION

    print(
        f"   brain: REPLY_V2={int(bool(_cfg.REPLY_V2))} "
        f"SIMPLE_PROMPT={int(bool(_cfg.SIMPLE_PROMPT))} "
        f"LEAN_CREATIVE={int(bool(_cfg.LEAN_CREATIVE))} "
        f"PHASE_ANALYST={int(bool(_cfg.PHASE_ANALYST))} "
        f"| prompt={PROMPT_VERSION} core_chars={len(EMMA_CORE_PROMPT_SIMPLE)}"
    )
    if _cfg.SIMPLE_PROMPT and _cfg.REPLY_V2:
        print(
            "   ⚠️ REPLY_V2=1 ignored while SIMPLE_PROMPT=1 "
            "(SIMPLE core is the live brain)"
        )

    if use_postgres():
        from db.schema import ensure_account, init_schema

        init_schema(seed_account=True)
        print(f"   storage: Postgres + Redis (account={aid})")
        # Keep vault_media aligned with the shipped media map (L0/L1 ladder, etc.)
        try:
            from pathlib import Path
            from db import vault_store

            map_path = vault_store._default_map_path()
            if map_path and map_path.is_file():
                raw = json.loads(Path(map_path).read_text(encoding="utf-8"))
                n = vault_store.replace_items(
                    raw.get("items") or [],
                    aid=aid,
                    catalog_version=Path(map_path).parent.name,
                )
                print(f"   vault synced: {n} items from {Path(map_path).name}")
        except Exception as e:
            print(f"   ⚠️ vault sync skipped: {e}")

        # Lean creative: wipe Soft lesson flood + repair known corrupt names once at boot
        try:
            from config import config as _cfg

            if getattr(_cfg, "LEAN_CREATIVE", True):
                from core import lessons as _lessons
                from db import fan_memory_store as _fms

                cleared = _lessons.clear_all_active()
                if cleared:
                    print(f"   lean: cleared {cleared} Soft global lessons")
                # Ruben card was poisoned as name "Un" — restore confirmed name
                rid = "abe29501-7bef-4486-831d-a6ed0a3a56a8"
                mem = fan_memory.get(rid) or {}
                if (mem.get("name") or "").lower() != "ruben" or not mem.get("name_confirmed"):
                    fan_memory._set_confirmed_name(mem, "Ruben")  # noqa: SLF001
                    mem["handle"] = mem.get("handle") or "patient-guineafowl-495"
                    _fms.set_fan(rid, mem)
                    print("   lean: client card → Ruben (confirmed)")
                # Drop junk test fans that break purge/list (invalid UUIDs)
                for junk_id, junk_mem in list((_fms.load_all() or {}).items()):
                    if junk_id.count("-") < 4 or len(junk_id) < 32:
                        try:
                            _fms.set_fan(junk_id, {"_deleted": True, "handle": ""})
                        except Exception:
                            pass
                        print(f"   lean: drop junk fan entry {junk_id[:24]!r}")
        except Exception as e:
            print(f"   ⚠️ lean reset skipped: {e}")
    else:
        print(f"   storage: local JSON files (account={aid})")

    if not load_tokens():
        print("❌ No Fanvue tokens. Run oauth login first (or migrate tokens to PG).")
        sys.exit(1)

    # Auto-rescue: Discord alert + optional public /oauth/callback HTTP
    try:
        from core import oauth_rescue

        oauth_rescue.maybe_start_callback_http()
    except Exception as e:
        print(f"   ⚠️ oauth rescue init: {e}")

    fv = FanvueConnector()
    try:
        me = fv.get_current_user()
    except Exception as e:
        print(f"❌ Fanvue auth failed at boot: {e}")
        try:
            from core.oauth_rescue import mark_broken

            mark_broken(f"boot: {type(e).__name__}: {e}")
        except Exception:
            pass
        print("   Waiting for re-auth (webhook link / oauth_login)…")
        me = {"uuid": None, "handle": "?"}
    creator_uuid = me.get("uuid")
    if use_postgres() and creator_uuid:
        from db.schema import ensure_account

        ensure_account(
            aid,
            handle=me.get("handle") or "",
            creator_uuid=creator_uuid,
        )
    n_cat = len(vault_catalog.load_items())
    print(f"🔥 Emma polling @{me.get('handle')} every {args.interval}s")
    print(f"   Vault catalog: {n_cat} photos ready for real PPV")
    if getattr(config, "PPV_EXPIRE_ENABLED", True):
        print(
            f"   PPV scarcity: unpaid locks unsend after "
            f"{getattr(config, 'PPV_EXPIRE_MINUTES', 30)} min"
        )
    if getattr(config, "PPV_PURGE_ACTIVE_ON_START", True):
        print("   PPV purge-on-start: wiping ALL unpaid locks in recent chats…")
        try:
            n_purge = ppv_expiry.purge_all_unpaid(fv, creator_uuid)
            print(f"   PPV purge-on-start: done ({n_purge} deleted)")
        except Exception as e:
            print(f"   ⚠️ PPV purge-on-start failed: {e}")
    print("   Ctrl+C to stop")
    print(
        "   drain: SIGTERM finishes current fan turn, skips new chats, "
        "releases Redis lock (safe Railway redeploy)\n"
    )

    processed = _load_processed()
    last_reengage = 0.0
    last_fix_scan = 0.0
    last_lore_reload = 0.0
    use_lock = use_redis()
    hold_lock = False

    signal.signal(signal.SIGTERM, _request_shutdown)
    signal.signal(signal.SIGINT, _request_shutdown)

    if use_lock:
        # Acquire once; refresh each loop. SET NX every iteration would
        # block ourselves after the first successful poll.
        for _attempt in range(30):
            if shutting_down():
                break
            if redis_store.acquire_poller_lock(aid):
                hold_lock = True
                print("   redis lock: acquired")
                break
            print("z", end="", flush=True)
            time.sleep(2)
        if not hold_lock and not shutting_down():
            print("\n❌ could not acquire poller lock — another replica running?")
            sys.exit(1)

    try:
        while not shutting_down():
            try:
                if hold_lock:
                    redis_store.refresh_poller_lock(aid)

                # Soft: pick up lorebook.json edits ~every 5 min (no redeploy)
                if (
                    not shutting_down()
                    and time.time() - last_lore_reload >= 300
                ):
                    last_lore_reload = time.time()
                    if lorebook.ensure_fresh(force=True):
                        print("\n📖 lorebook reloaded from disk\n", flush=True)

                try:
                    from core.oauth_rescue import is_broken, notify_rescue

                    if is_broken():
                        print("o", end="", flush=True)  # oauth waiting
                        notify_rescue("still_broken")
                        time.sleep(max(args.interval, 30))
                        continue
                except Exception:
                    pass

                if not creator_uuid:
                    try:
                        me2 = fv.get_current_user()
                        creator_uuid = me2.get("uuid")
                        if creator_uuid:
                            print(f"\n🔐 Fanvue auth recovered as @{me2.get('handle')}\n")
                    except Exception:
                        time.sleep(max(args.interval, 30))
                        continue

                count = poll_once(fv, processed, creator_uuid)
                if shutting_down():
                    break
                if count:
                    print(f"\n--- handled {count} ---\n")
                else:
                    print(".", end="", flush=True)

                # Re-engagement pass every 60s (15/30m ladder + morning openers)
                if not shutting_down() and time.time() - last_reengage >= 60:
                    last_reengage = time.time()
                    try:
                        n_exp = ppv_expiry.run_pass(fv, creator_uuid)
                        if n_exp:
                            print(f"\n--- expired {n_exp} unpaid PPV(s) ---\n")
                    except Exception as e:
                        print(f"\n⚠️ PPV expiry error: {e}")
                    try:
                        chats = fv.list_chats(size=20)
                        n = reengagement.run_pass(fv, chats, creator_uuid)
                        if n:
                            print(f"\n--- re-engaged {n} fan(s) ---\n")
                    except Exception as e:
                        print(f"\n⚠️ Re-engagement error: {e}")

                # Every hour: DeepSeek reviews ONLY last-hour turns → Soft/Hard board
                # Soft stays PENDING (no live prompt inject unless AUTO_APPROVE_SOFT_LESSONS=1)
                if not shutting_down() and time.time() - last_fix_scan >= 3600:
                    last_fix_scan = time.time()
                    try:
                        from core import auto_fix, hour_review, improve_board

                        hr = hour_review.run_hourly_review()
                        if not hr.get("skipped"):
                            print(
                                f"\n⏱ hourly review done — "
                                f"fails={hr.get('failures', 0)} "
                                f"soft+={hr.get('soft_proposed', 0)} "
                                f"hard={hr.get('hard', 0)}\n"
                            )
                        new = auto_fix.scan_and_queue()
                        if new:
                            rules = ", ".join(i["rule"] for i in new)
                            print(
                                f"\n🧠 self-repair queue: {len(new)} ({rules}) "
                                f"— Soft pending unless AUTO_APPROVE; code autofix manual\n"
                            )
                        result = improve_board.run_soft_autopilot(ask_deepseek=True)
                        n_act = len(result.get("activated") or [])
                        if n_act:
                            print(
                                f"\n✅ Soft auto-approved {n_act} global lesson(s) "
                                f"(shared Emma behavior)\n"
                            )
                        soft_n = result.get("soft_n") or 0
                        hard_n = result.get("hard_n") or 0
                        if soft_n or hard_n or n_act:
                            print(
                                f"\n📋 improve board: Soft={soft_n} Hard={hard_n} "
                                f"activated={n_act} → docs/IMPROVE_BOARD.md\n"
                            )
                    except Exception as e:
                        print(f"\n⚠️ hour-review / fix-scan error: {e}")

                # Interruptible sleep so SIGTERM is noticed quickly
                deadline = time.time() + args.interval
                while time.time() < deadline and not shutting_down():
                    time.sleep(min(0.5, deadline - time.time()))
            except Exception as e:
                if shutting_down():
                    break
                err = str(e)
                print(f"\n⚠️ Poll error: {e}")
                # OAuth dead → alert once + long backoff (don't spam token URL)
                if (
                    "oauth" in err.lower()
                    or "refresh" in err.lower()
                    or "401" in err
                    or "token" in err.lower()
                ):
                    try:
                        from core.oauth_rescue import mark_broken

                        mark_broken(err[:180])
                    except Exception:
                        pass
                    time.sleep(max(args.interval, 60))
                else:
                    time.sleep(args.interval)
    finally:
        if hold_lock:
            try:
                redis_store.release_poller_lock(aid)
                print("   redis lock: released", flush=True)
            except Exception as e:
                print(f"   ⚠️ lock release failed: {e}", flush=True)
        print("Stopped gracefully.", flush=True)


if __name__ == "__main__":
    main()
