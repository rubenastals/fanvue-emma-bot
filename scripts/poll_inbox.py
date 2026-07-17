"""
Poll Fanvue inbox and auto-reply as Emma.

Design:
- DeepSeek gets prompt + real chat history (coherence + full freedom).
- Long replies are split into several short chat bubbles (never a wall of text).
- SIGTERM/SIGINT drains: finish the current fan turn, release Redis lock, exit.
"""
import argparse
import json
import os
import random
import re
import signal
import sys
import time
from datetime import datetime, timedelta, timezone

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from api.fanvue_connector import FanvueConnector
from api.fanvue_oauth import load_tokens
from core import convo_log, critic, fan_memory, fan_vision, lorebook, memory_extractor, reengagement, vault_catalog
from core.reply_engine import (
    fanvue_messages_to_turns,
    filter_messages_for_context,
    generate_emma_reply,
    split_into_messages,
)
from core.turn_policy import decide_turn
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


def _check_last_ppv(messages: list, creator_uuid: str, mem: dict):
    """
    Truth-check the LAST locked PPV using the chat itself: the PPV message
    object carries `purchasedAt` (null until the fan unlocks it).
    Scoped to THIS conversation's newest priced message; older than the
    window → None (never reclaim forgotten PPVs).
    """
    for msg in messages:  # newest-first
        if _sender_uuid(msg) != creator_uuid:
            continue
        pricing = msg.get("pricing") or {}
        if not pricing or not msg.get("mediaUuids"):
            continue
        # newest PPV from us found
        sent_raw = msg.get("sentAt") or msg.get("createdAt")
        try:
            sent_at = datetime.fromisoformat(str(sent_raw).replace("Z", "+00:00"))
        except (ValueError, TypeError):
            return None
        age = datetime.now(timezone.utc) - sent_at
        if age > timedelta(hours=PPV_CHECK_WINDOW_HOURS):
            return None
        price = None
        usd = pricing.get("USD") or {}
        if usd.get("price") is not None:
            price = float(usd["price"]) / 100.0
        minutes = int(age.total_seconds() // 60)
        ago = f"{minutes} min ago" if minutes < 120 else f"{minutes // 60}h ago"
        label = ""
        if (msg.get("mediaUuids") or [None])[0] == mem.get("last_ppv_media_uuid"):
            label = mem.get("last_ppv_label") or ""
        return {
            "purchased": bool(msg.get("purchasedAt")),
            "label": label,
            "price": price if price is not None else mem.get("last_ppv_price"),
            "ago": ago,
        }
    return None


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
    return pending


def _sleep_interruptible(
    fv: FanvueConnector,
    fan_uuid: str,
    processed: set,
    seconds: float,
    *,
    known_ids: set,
) -> bool:
    """
    Sleep in chunks; return True if a NEW fan message appeared (barge-in).
    """
    end = time.time() + max(0.0, seconds)
    while time.time() < end:
        chunk = min(1.5, end - time.time())
        if chunk <= 0:
            break
        time.sleep(chunk)
        try:
            msgs = fv.get_messages(fan_uuid, size=8)
        except Exception:
            continue
        for msg in _pending_fan_messages(msgs, fan_uuid, processed):
            if msg.get("uuid") not in known_ids:
                return True
    return False


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
        if shutting_down() and handled > 0:
            break
        messages = fv.get_messages(fan_uuid, size=50)
        if not messages:
            break

        pending = _pending_fan_messages(messages, fan_uuid, processed)
        if not pending:
            break

        # Oldest → newest so we absorb everything he typed while we were away
        pending_chrono = list(reversed(pending))
        texts = [_fan_message_text(m) for m in pending_chrono]
        text = "\n".join(t for t in texts if t)
        pending_ids = {m["uuid"] for m in pending_chrono if m.get("uuid")}

        ctx_messages = filter_messages_for_context(
            messages, hours=48, max_messages=50, min_messages=8
        )
        turns = fanvue_messages_to_turns(
            ctx_messages, fan_uuid, creator_uuid, max_messages=50
        )

        mem = fan_memory.observe_message(fan_uuid, fan_handle, text)
        decision = decide_turn(mem, text)

        preview = text.replace("\n", " | ")[:80]
        print(f"\n📩 @{fan_handle}: {preview}")
        if len(pending_chrono) > 1:
            print(f"   (absorbed {len(pending_chrono)} pending fan msgs)")
        print(
            f"   memory: status={mem.get('status')} spent=${mem.get('total_spent')} "
            f"likes={','.join(mem.get('interests', [])) or '-'}"
        )
        print(f"   mode: {decision.mode} ({decision.reason})")

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

        ppv_status = _check_last_ppv(messages, creator_uuid, mem)
        if ppv_status is not None:
            state = "PURCHASED" if ppv_status["purchased"] else "NOT purchased"
            print(f"   ppv-check: {state} — {ppv_status['label'][:40]} ({ppv_status['ago']})")

        offer = None
        if decision.mode in ("soft_sell", "hard_sell") and decision.allow_price:
            # Belt-and-suspenders: never lock twice inside cooloff even if mode slipped
            last_ppv = mem.get("last_ppv_at") or mem.get("last_offer_at")
            too_soon = False
            if last_ppv:
                try:
                    ago = datetime.now(timezone.utc) - datetime.fromisoformat(
                        str(last_ppv).replace("Z", "+00:00")
                    )
                    too_soon = ago < timedelta(minutes=12)
                except (ValueError, TypeError):
                    pass
            if too_soon:
                print("   ppv: skipped (cooloff — avoid double lock)")
            else:
                offer = vault_catalog.select_offer(mem, text)
                if offer:
                    print(
                        f"   ppv: L{offer['level']} ${offer['price']:.0f} "
                        f"{offer['label'][:50]} ({offer['media_uuid'][:8]}…)"
                    )
                else:
                    print("   ppv: no catalog item available")
        elif getattr(decision, "allow_free_tease", False):
            offer = vault_catalog.select_free_tease(mem)
            if offer:
                print(
                    f"   free L0: {offer['label'][:50]} ({offer['media_uuid'][:8]}…)"
                )
            else:
                print("   free L0: none left for this chat")

        reply, decision = generate_emma_reply(
            text,
            history_turns=turns,
            fan_handle=fan_handle,
            fan_uuid=fan_uuid,
            decision=decision,
            offer=offer,
            ppv_status=ppv_status,
            fan_vision=vision,
        )
        bubbles = split_into_messages(reply, max_bubbles=3, vary=True)
        print(f"💬 Emma ({len(bubbles)} msg) [{decision.mode}]: {reply[:120]}")

        # Mark ALL absorbed fan msgs before sending (crash-safe, no double-reply)
        for uid in pending_ids:
            _mark_processed(processed, uid)

        barged = False
        bubbles_sent = 0
        for i, bubble in enumerate(bubbles):
            if i == 0:
                delay = random.uniform(5.0, 11.0)
                if random.random() < 0.25:
                    delay += random.uniform(2.0, 5.0)
            else:
                delay = 2.8 + len(bubble) / 28.0 + random.uniform(0.8, 3.5)
                delay = min(14.0, max(3.0, delay))
            try:
                fv.send_typing_indicator(fan_uuid, True)
            except Exception:
                pass
            interrupted = _sleep_interruptible(
                fv, fan_uuid, processed, delay, known_ids=pending_ids
            )
            # Always deliver at least one bubble for this turn; abort the rest if he wrote
            fv.send_message(fan_uuid, bubble)
            bubbles_sent += 1
            try:
                fv.send_typing_indicator(fan_uuid, False)
            except Exception:
                pass
            print(f"   ✅ [{i+1}/{len(bubbles)}] (+{delay:.1f}s) {bubble[:60]}")
            if interrupted:
                print("   ⏭ barge-in: fan wrote mid-reply — stopping remaining bubbles")
                barged = True
                break

        # Skip PPV if he interrupted — next turn will re-decide with his new text
        if offer and not barged:
            if _sleep_interruptible(
                fv,
                fan_uuid,
                processed,
                random.uniform(2.0, 4.5),
                known_ids=pending_ids,
            ):
                print("   ⏭ barge-in before PPV — skipping lock this turn")
                barged = True
            else:
                try:
                    fv.send_typing_indicator(fan_uuid, True)
                except Exception:
                    pass
                if _sleep_interruptible(
                    fv,
                    fan_uuid,
                    processed,
                    random.uniform(1.5, 3.0),
                    known_ids=pending_ids,
                ):
                    print("   ⏭ barge-in before PPV — skipping lock this turn")
                    barged = True
                    try:
                        fv.send_typing_indicator(fan_uuid, False)
                    except Exception:
                        pass
                else:
                    is_free = (
                        float(offer.get("price") or 0) <= 0
                        or int(offer.get("level") or 0) == 0
                    )
                    try:
                        if is_free:
                            # Attach image on its own bubble with a tiny vibe text —
                            # media-only payloads have rendered as empty placeholders.
                            fv.send_media_message(
                                fan_uuid,
                                media_uuids=[offer["media_uuid"]],
                                text="😏",
                            )
                            fan_memory.record_free_tease(
                                fan_uuid,
                                offer["media_uuid"],
                                fan_handle=fan_handle,
                                label=offer.get("label") or "",
                                level=int(offer.get("level") or 0),
                            )
                            print(
                                f"   🎁 FREE L0 media attached — {offer['label']}"
                            )
                        else:
                            price = max(3.0, float(offer["price"]))
                            fv.send_ppv_message(
                                fan_uuid,
                                media_uuids=[offer["media_uuid"]],
                                price_dollars=price,
                                text=None,
                            )
                            fan_memory.set_last_offer(
                                fan_uuid,
                                price,
                                fan_handle=fan_handle,
                                level=int(offer["level"]),
                                media_uuid=offer["media_uuid"],
                                label=offer.get("label") or "",
                            )
                            print(
                                f"   🔒 PPV sent L{offer['level']} ${price:.0f} — {offer['label']}"
                            )
                    except Exception as e:
                        kind = "FREE" if is_free else "PPV"
                        print(f"   ❌ {kind} send failed: {type(e).__name__}: {e}")
                        if is_free:
                            # Don't leave him with a promise and no image
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
            )
            critic.review_fan_async(fan_uuid, fan_handle)
            memory_extractor.update_fan_card_async(fan_uuid, fan_handle)
        except Exception as e:
            print(f"   ⚠️ learning-loop log failed: {e}")

        handled += 1
        if not barged:
            # No interruption — done with this fan for this poll
            break
        # else: loop and answer the new pending message immediately

    return handled


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

    for chat in candidates:
        if shutting_down():
            break
        user = chat.get("user", {})
        fan_uuid = user.get("uuid")
        fan_handle = user.get("handle", "fan")
        if not fan_uuid:
            continue
        handled += _handle_fan_chat(
            fv, processed, creator_uuid, fan_uuid, fan_handle
        )

    return handled


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--interval", type=int, default=10)
    args = parser.parse_args()

    aid = account_id()
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
    else:
        print(f"   storage: local JSON files (account={aid})")

    if not load_tokens():
        print("❌ No Fanvue tokens. Run oauth login first (or migrate tokens to PG).")
        sys.exit(1)

    fv = FanvueConnector()
    me = fv.get_current_user()
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
    print("   Ctrl+C to stop\n")

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

                # Soft: pick up lorebook.json edits without process restart
                if time.time() - last_lore_reload >= 300:
                    last_lore_reload = time.time()
                    if lorebook.ensure_fresh(force=True):
                        print("\n📖 lorebook reloaded from disk\n", flush=True)

                count = poll_once(fv, processed, creator_uuid)
                if shutting_down():
                    break
                if count:
                    print(f"\n--- handled {count} ---\n")
                else:
                    print(".", end="", flush=True)

                # Re-engagement pass every 60s (5-min nudges + morning openers)
                if not shutting_down() and time.time() - last_reengage >= 60:
                    last_reengage = time.time()
                    try:
                        chats = fv.list_chats(size=20)
                        n = reengagement.run_pass(fv, chats, creator_uuid)
                        if n:
                            print(f"\n--- re-engaged {n} fan(s) ---\n")
                    except Exception as e:
                        print(f"\n⚠️ Re-engagement error: {e}")

                # Every 30 min: Soft autopilot (auto-approve global lessons) + board
                if not shutting_down() and time.time() - last_fix_scan >= 1800:
                    last_fix_scan = time.time()
                    try:
                        from core import auto_fix, improve_board

                        new = auto_fix.scan_and_queue()
                        if new:
                            rules = ", ".join(i["rule"] for i in new)
                            print(
                                f"\n🧠 self-repair queue: {len(new)} ({rules}) "
                                f"— Soft lessons auto-approve; code autofix still manual\n"
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
                        print(f"\n⚠️ fix-scan error: {e}")

                # Interruptible sleep so SIGTERM is noticed quickly
                deadline = time.time() + args.interval
                while time.time() < deadline and not shutting_down():
                    time.sleep(min(0.5, deadline - time.time()))
            except Exception as e:
                if shutting_down():
                    break
                print(f"\n⚠️ Poll error: {e}")
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
