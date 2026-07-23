"""
Reply ASSEMBLE seam (audit R4).

Builds CORE + CARD + HISTORY + TURN + AUTHOR messages.
No LLM calls. Live creative path only patches personas/emma.md + TURN facts here
(or code gates) — not quarantined brains.
"""
from __future__ import annotations

import random
import re
from typing import Any, Dict, List, Optional, Tuple

from config import config
from core import (
    fan_memory,
    language,
    lessons,
    lorebook,
    manipulation,
    packs,
    persona_time,
    phase_analyst,
    prompt_audit,
    prompt_layers,
    scheme_guard,
    vault_catalog,
)
from core.intent_router import RouteResult, decision_for_pack, route as route_intent
from core.turn_policy import TurnDecision, author_note_for, decide_turn
from core.system_prompt import EMMA_SYSTEM_PROMPT  # legacy fat prompt (non-lean only)

from core.reply_types import AssembledTurn

def _sender_uuid(msg: dict) -> Optional[str]:
    sender = msg.get("sender")
    if isinstance(sender, dict):
        return sender.get("uuid")
    if isinstance(sender, str):
        return sender
    return None


def _parse_msg_time(msg: dict):
    raw = msg.get("sentAt") or msg.get("createdAt") or msg.get("created_at")
    if not raw:
        return None
    try:
        from datetime import datetime, timezone

        if isinstance(raw, (int, float)):
            return datetime.fromtimestamp(float(raw) / (1000 if raw > 1e12 else 1), tz=timezone.utc)
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except (ValueError, TypeError, OSError):
        return None


def filter_messages_for_context(
    messages: List[dict],
    *,
    hours: int = 72,
    max_messages: int = 100,
    min_messages: int = 8,
) -> List[dict]:
    """
    Newest-first Fanvue list → keep last `hours`, capped at max_messages.
    If the window is too thin, fall back to the newest min_messages.
    """
    from datetime import datetime, timedelta, timezone

    if not messages:
        return []
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=hours)
    in_window: List[dict] = []
    for m in messages:
        ts = _parse_msg_time(m)
        if ts is None or ts >= cutoff:
            in_window.append(m)
        if len(in_window) >= max_messages:
            break
    if len(in_window) >= min_messages:
        return in_window[:max_messages]
    return list(messages[: max(min_messages, max_messages)])


def tip_amount_usd(msg: dict) -> Optional[float]:
    """USD tip amount from pricing.USD.price (cents), or None."""
    usd = (msg.get("pricing") or {}).get("USD") or {}
    raw = usd.get("price")
    if raw is None:
        return None
    try:
        cents = float(raw)
    except (TypeError, ValueError):
        return None
    return round(cents / 100.0, 2) if cents >= 0 else None


def fan_tip_or_gift_stub(msg: dict) -> str:
    """
    Fanvue tips: type TIP (+ pricing / tipSource).
    Chat gifts: empty SINGLE_RECIPIENT (no text, media, pricing, tipSource).
    Returns a stub the model can react to, or '' if not tip/gift.
    """
    mtype = (msg.get("type") or "").upper()
    if mtype.startswith("AUTOMATED") or mtype in (
        "VOICE_CALL",
        "BROADCAST",
        "GHOST_PROMOTION",
    ):
        return ""
    tip_source = msg.get("tipSource")
    amount = tip_amount_usd(msg)
    is_tip = mtype == "TIP" or tip_source in ("chat", "post", "media_link")
    if is_tip:
        if amount is not None and amount > 0:
            return (
                f"[fan tipped you ${amount:g} on Fanvue — reward him warmly; "
                "do NOT pitch a new unlock]"
            )
        return (
            "[fan tipped you on Fanvue — reward him warmly; "
            "do NOT pitch a new unlock]"
        )
    text = (msg.get("text") or "").strip()
    has_media = bool(msg.get("hasMedia") or msg.get("mediaUuids"))
    if text or has_media or msg.get("pricing"):
        return ""
    # Opaque chat gift bubble (confirmed via live Fanvue API inspect)
    if mtype in ("SINGLE_RECIPIENT", ""):
        return (
            "[fan sent you a Fanvue chat gift — react warmly like he spoiled you; "
            "do NOT pitch a new unlock]"
        )
    return ""


def fan_message_display_text(msg: dict) -> str:
    """Text body, media stub, or tip/gift stub for a fan message."""
    text = (msg.get("text") or "").strip()
    if text:
        return text
    has_media = bool(msg.get("hasMedia") or msg.get("mediaUuids"))
    if not has_media:
        return fan_tip_or_gift_stub(msg)
    mtype = (msg.get("mediaType") or "").lower()
    if "audio" in mtype:
        return "[fan sent a voice note / audio]"
    if "video" in mtype:
        return "[fan sent a video]"
    return "[fan sent a photo]"


def fanvue_messages_to_turns(
    messages: List[dict],
    fan_uuid: str,
    creator_uuid: str,
    *,
    max_messages: int = 100,
) -> List[Dict[str, str]]:
    """Newest-first Fanvue msgs → chronological OpenAI turns."""
    chronological = list(reversed(messages[:max_messages]))
    turns: List[Dict[str, str]] = []
    for msg in chronological:
        sid = _sender_uuid(msg)
        if sid == fan_uuid:
            role = "user"
        elif sid == creator_uuid:
            role = "assistant"
        else:
            continue
        text = (msg.get("text") or "").strip()
        if not text and role == "user":
            text = fan_message_display_text(msg)
        elif not text and (msg.get("hasMedia") or msg.get("mediaUuids")):
            mtype = (msg.get("mediaType") or "").lower()
            priced = bool(msg.get("pricing"))
            if priced:
                unlocked = bool(msg.get("purchasedAt"))
                price = tip_amount_usd(msg)
                price_bit = f" ${price:.0f}" if price is not None else ""
                if unlocked:
                    text = f"[you locked a paid photo{price_bit} — HE UNLOCKED IT]"
                else:
                    text = f"[you locked a paid photo{price_bit} — still locked / unpaid]"
            elif "audio" in mtype:
                text = "[you sent a VOICE NOTE — free audio, not a photo]"
            else:
                text = "[you sent a FREE photo — unlocked gift]"
        elif text and role == "assistant" and (msg.get("hasMedia") or msg.get("mediaUuids")):
            mtype = (msg.get("mediaType") or "").lower()
            if "audio" in mtype and "[voice note" not in text.lower():
                text = f"{text} [voice note attached]"
            elif msg.get("pricing") and "[locked" not in text.lower() and "[paid" not in text.lower():
                text = f"{text} [paid photo lock attached]"
        if not text:
            continue
        if turns and turns[-1]["role"] == role:
            turns[-1]["content"] = turns[-1]["content"] + "\n" + text
        else:
            turns.append({"role": role, "content": text})
    return turns


def _thread_mentions_voice(
    turns: List[Dict[str, str]], fan_message: str, *, lookback: int = 10
) -> bool:
    """Recent thread is about audio/voice (for turn blocks, not hard gates)."""
    blob = (fan_message or "").lower()
    for t in (turns or [])[-lookback:]:
        blob += " " + (t.get("content") or "").lower()
    return any(
        k in blob
        for k in (
            "audio", "audios", "voz", "voice note", "escúchame", "escuchame",
            "susurr", "🎙", "oírme", "oírte", "grabar", "waiting for",
            "esperando", "voice note",
        )
    )


_COOL_RE = re.compile(
    r"(?i)^\s*(no s[eé]|nose|dime t[uú]|vale|ok|bueno|nada|meh|nah|luego|"
    r"despu[eé]s|quiz[aá]s?|puede|paso|da igual|ya veremos|no s[eé] dime)\b"
)


def _looks_cooling(
    fan_message: str,
    turns: List[Dict[str, str]],
    *,
    msgs: int = 0,
) -> bool:
    """Cheap cooling read: cool words, or a run of tiny replies early on."""
    msg = (fan_message or "").strip()
    if not msg:
        return True
    if _COOL_RE.search(msg):
        return True
    # After rapport, short polite texts ≠ cooling (shy fans stay short).
    if int(msgs or 0) >= 8:
        return False
    fan_turns = [t.get("content") or "" for t in turns if t.get("role") == "user"]
    recent = [t for t in fan_turns[-3:] if not t.startswith("[")]
    if len(recent) >= 2 and all(len(t.strip()) <= 12 for t in recent):
        return True
    return False


def _ppv_truth_block(status: dict) -> str:
    """Fact block: purchased / active timed lock / none — Emma must persist correctly."""
    from core import ppv_expiry

    if status.get("purchased"):
        label = status.get("label") or "your locked photo"
        price = status.get("price")
        ago = status.get("ago") or "recently"
        price_txt = f" (${price:.0f})" if isinstance(price, (int, float)) else ""
        return (
            "LOCK STATUS — VERIFIED THIS TURN:\n"
            f"- He **DID** purchase the lock \"{label}\"{price_txt} (sent {ago}).\n"
            "- Thank him warmly. Do not ask him to unlock it again."
        )
    # Active unpaid or explicit none
    if status.get("active") is False and not status.get("purchased"):
        return ppv_expiry.lock_status_prompt_block(status)
    if status.get("active") or (
        not status.get("purchased") and status.get("message_uuid")
    ):
        # Normalize legacy unpaid dicts into lock status shape
        if "active" not in status:
            status = {
                "active": True,
                "count": int(status.get("count") or 1),
                "label": status.get("label") or "",
                "price": status.get("price"),
                "minutes_left": status.get("minutes_left"),
                "ago": status.get("ago"),
            }
        return ppv_expiry.lock_status_prompt_block(status)
    return ppv_expiry.lock_status_prompt_block({"active": False})


def _usable_fan_name(name: str, *, confirmed: bool = False) -> str:
    """Real first names only — never articles like Un/De that destroy Spanish."""
    from core.fan_memory import _normalize_name

    n = _normalize_name(name or "")
    if not n or len(n) < 3:
        return ""
    if not confirmed:
        return ""
    return n


def _name_budget_note(
    name: str,
    turns: List[Dict[str, str]],
    *,
    name_confirmed: bool = False,
) -> Tuple[str, int]:
    """
    Returns (note, max_name_uses_this_turn).

    Goal: real name OCCASIONALLY (feels intimate), not every bubble.
    Ban only when recent spam risk — never strip the name forever.
    Pet names stay welcome when not stacked.
    """
    name = _usable_fan_name(name, confirmed=name_confirmed)
    if not name:
        return (
            "ADDRESSING: USE a pet name this turn "
            "(EN: baby/babe/handsome/trouble; ES: bebé/cielo/guapo/mi vida) — "
            "rotate, don't stack 3 in one line. HARD BAN: caro/papi/nena/nene. "
            "Never invent a first name.",
            0,
        )
    recent_emma = [
        t.get("content") or ""
        for t in turns[-12:]
        if t.get("role") == "assistant"
    ][-6:]
    used_recent = [
        c for c in recent_emma if name.lower() in (c or "").lower()
    ]
    # Back-to-back or 2+ of last 6 → cool off this turn
    last_had = bool(
        recent_emma and name.lower() in (recent_emma[-1] or "").lower()
    )
    if last_had or len(used_recent) >= 2:
        return (
            f"ADDRESSING THIS TURN: skip \"{name}\" — you used it recently. "
            f"USE a pet name (EN: baby/babe/handsome/trouble; "
            f"ES: bebé/cielo/guapo/mi vida). "
            f"Vary pets; don't spam the same one. Never \"Ay {name}\". "
            f"HARD BAN: caro/papi/nena/nene.",
            0,
        )
    # Allowed — invite occasional natural use
    return (
        f"ADDRESSING: His confirmed name is \"{name}\". You MAY say it ONCE this turn "
        f"if natural. Still USE a pet name most turns "
        f"(EN: baby/babe/handsome/trouble; ES: bebé/cielo/guapo/mi vida). "
        f"Never open every line with \"Ay {name}\". HARD BAN: caro/papi/nena/nene.",
        1,
    )


def assemble_emma_turn(
    fan_message: str,
    *,
    history_turns: Optional[List[Dict[str, str]]] = None,
    fan_handle: str = "baby",
    fan_uuid: Optional[str] = None,
    decision: Optional[TurnDecision] = None,
    offer: Optional[dict] = None,
    want_spanish: Optional[bool] = None,
    ppv_status: Optional[dict] = None,
    fan_vision: Optional[dict] = None,
    delivery_truth: Optional[dict] = None,
    pack_id: Optional[str] = None,
    route_result: Optional[RouteResult] = None,
    voice_will_send: bool = False,
    turn_action: Optional[Any] = None,
) -> AssembledTurn:
    """
    Prompt + memory + ONE situation pack + mode-aware author's note.

    Build prompt messages + turn truth. Returns AssembledTurn (no LLM call).
    `fan_vision` = Grok description of a photo the fan just sent.
    `delivery_truth` = Fanvue API checks (e.g. free_in_chat True/False).
    `turn_action` = code-owned ACTION from plan_turn_action (R5); optional.
    """
    history_turns = history_turns or []
    mem = fan_memory.get(fan_uuid) if fan_uuid else {}
    # Prefer ACTION from the poller resolver when provided
    if turn_action is not None:
        voice_will_send = bool(
            getattr(turn_action, "voice_will_send", voice_will_send)
        )
        if getattr(turn_action, "offer", None) is not None and offer is None:
            offer = turn_action.offer

    # Router: hard gates + soft intents → one pack (unless caller pre-routed)
    if route_result is None and (decision is None or not pack_id):
        snippets = [
            t.get("content") or ""
            for t in (history_turns or [])[-6:]
        ]
        route_result = route_intent(
            mem,
            fan_message,
            delivery_truth=delivery_truth,
            history_snippets=snippets,
        )
    if route_result is not None:
        decision = route_result.decision
        pack_id = pack_id or route_result.pack_id
        print(
            f"   pack: {pack_id} | mode={decision.mode} | "
            f"price={decision.allow_price} | via={route_result.facts.soft_source}"
            f"{' | hard=' + route_result.facts.hard_pack if route_result.facts.hard_pack else ''}"
        )
    if decision is None:
        decision = decide_turn(mem, fan_message, delivery_truth=delivery_truth)
    if not pack_id:
        pack_id = packs.fallback_pack()

    # Language: ENGLISH_ONLY (default) — always EN, ignore Spanish fans / sticky.
    if getattr(config, "ENGLISH_ONLY", True):
        want_spanish = False
        if fan_uuid and (mem or {}).get("prefer_spanish"):
            fan_memory.set_prefer_spanish(fan_uuid, False, fan_handle=fan_handle)
            mem = fan_memory.get(fan_uuid) or mem
    elif want_spanish is None:
        pref = language.update_language_pref(mem, fan_message)
        if pref is not None and fan_uuid:
            fan_memory.set_prefer_spanish(fan_uuid, pref, fan_handle=fan_handle)
            mem = fan_memory.get(fan_uuid)
        want_spanish = language.fan_wants_spanish(fan_message, mem)
    print(
        f"   lang: {'ES' if want_spanish else 'EN'} "
        f"sticky={bool((mem or {}).get('prefer_spanish'))}"
        f"{' ENGLISH_ONLY' if getattr(config, 'ENGLISH_ONLY', True) else ''}"
    )

    # Ensure the last turn is the current fan message exactly once
    turns = list(history_turns)
    if not (
        turns
        and turns[-1]["role"] == "user"
        and turns[-1]["content"].strip() == fan_message.strip()
    ):
        turns.append({"role": "user", "content": fan_message})

    lean = bool(getattr(config, "LEAN_CREATIVE", True))
    simple = bool(getattr(config, "SIMPLE_PROMPT", True))

    # --- PHASE ANALYST: read full chat + client card BEFORE creative ---
    card_block = ""
    if fan_uuid:
        card_block = fan_memory.render_block(fan_uuid) or ""
    hard_pack = None
    if route_result and route_result.facts.hard_pack:
        hard_pack = route_result.facts.hard_pack

    # Lock truth early — analyst + manip + rewrite all need it
    lock_active = None
    if ppv_status is not None:
        if ppv_status.get("purchased"):
            lock_active = False
        else:
            lock_active = bool(ppv_status.get("active"))
    elif delivery_truth is not None:
        lock_active = bool(delivery_truth.get("ppv_unpaid"))
    # Invent rails: treat unknown as "no waiting lock" (only True = real unpaid)
    no_lock = lock_active is not True
    soft_support = bool(
        route_result
        and (
            getattr(route_result.facts, "broke_soft", False)
            or getattr(route_result.facts, "heavy_vent", False)
        )
    )
    facts_line = ""
    if route_result is not None:
        facts_line = route_result.facts.facts_line()

    analysis = None
    force_tech = None
    phase_name = ""
    if not simple:
        try:
            analysis = phase_analyst.analyze(
                fan_message=fan_message,
                history_turns=turns,
                card_text=card_block,
                hard_pack=hard_pack,
                code_pack=pack_id,
                facts_line=facts_line,
                lock_active=lock_active,
                allow_price=bool(decision and decision.allow_price),
            )
        except Exception as e:
            print(f"   phase-analyst error: {type(e).__name__}: {e}")

    if analysis:
        phase_name = analysis.phase or ""
        print(
            f"   analyst: phase={analysis.phase} pack={analysis.pack_id} "
            f"name={analysis.name_to_use or '-'} "
            f"likes={','.join(analysis.likes[:3]) or '-'}"
        )
        # Soft packs only — never downgrade convert / hard packs
        if (
            not hard_pack
            and analysis.pack_id
            and analysis.pack_id != pack_id
            and pack_id not in phase_analyst._CONVERT_PACKS
            and not (decision and decision.allow_price)
        ):
            pack_id = analysis.pack_id
            if route_result is not None:
                decision = decision_for_pack(
                    pack_id,
                    route_result.facts,
                    mem,
                    f"analyst:{analysis.phase}",
                )
            print(f"   pack←analyst: {pack_id}")
        elif (
            analysis.pack_id
            and analysis.pack_id != pack_id
            and (
                pack_id in phase_analyst._CONVERT_PACKS
                or (decision and decision.allow_price)
            )
        ):
            print(
                f"   analyst pack {analysis.pack_id} ignored — keep convert {pack_id}"
            )
        if analysis.technique_hint:
            force_tech = phase_analyst.apply_technique_hint(
                pack_id, analysis.technique_hint
            )

    turn_blocks: List[str] = []

    # Soft lessons NEVER in live path unless operator forces INJECT_LESSONS=1
    if getattr(config, "INJECT_LESSONS", False):
        lessons_block = lessons.render_block(fan_uuid)
        if lessons_block:
            turn_blocks.append(lessons_block)
            prompt_audit.log_change(
                source="live_prompt",
                action="inject_lessons",
                detail=f"Injected Soft lessons ({len(lessons_block)} chars)",
                enters_live_prompt=True,
            )

    # CLIENT RECALL from analyst (name / likes / where we are)
    if analysis:
        turn_blocks.append(analysis.recall_block())

    # Rival-fan / cooling flags shared by both paths
    msgs_n = int(mem.get("messages") or 0)
    objection_step = int(mem.get("price_objection_step") or 0)
    ban_rival = bool(mem.get("rival_fan_used")) or scheme_guard.history_has_rival_fan(
        turns
    )
    ban_withdrawal = ban_rival
    tech_name = ""

    if simple:
        # FACTS + one code-picked psychology move (not a Soft essay).
        from core import strategy_prompt, technique_policy
        from core.turn_action import action_prompt_line, commitment_prompt_line

        cooling = _looks_cooling(fan_message, turns, msgs=msgs_n)
        banned_opens = scheme_guard.recent_openings(turns, n=5)
        recent_emojis = scheme_guard.recent_emojis(turns, n=4)
        ts = strategy_prompt.truth_state(
            lock_active=lock_active,
            offer_price=float(offer.get("price") or 0) if offer else None,
            cooling=cooling,
            rival_used=ban_rival,
            banned_openings=banned_opens,
        )
        if ts:
            turn_blocks.append(ts)
        # Code-owned protocol (not Soft memory) — ACTION line before other TURN noise
        action_line = action_prompt_line(turn_action, mem=mem)
        if not action_line:
            action_line = commitment_prompt_line(
                mem, voice_will_send=voice_will_send
            )
        if action_line:
            turn_blocks.append(action_line)
        # Soft unpaid reconnect (friction) — no FOMO / guilt stack
        soft_unpaid = bool(
            (bool(delivery_truth and delivery_truth.get("ppv_unpaid"))
             or bool(ppv_status and ppv_status.get("active")))
            and pack_id == "phase_pull"
            and route_result
            and (route_result.active or {}).get("ppv_unpaid")
        )
        exclude_techs = (
            fan_memory.recent_techniques(fan_uuid, n=4) if fan_uuid else []
        )
        move = technique_policy.choose_move(
            pack_id or "",
            fan_uuid=fan_uuid or "",
            msgs=msgs_n,
            reject_count=objection_step,
            no_lock=no_lock,
            soft_support=soft_support,
            ban_withdrawal=ban_withdrawal,
            ban_rival_fan=ban_rival,
            exclude_names=exclude_techs,
            turn_action=turn_action,
            unpaid=bool(
                delivery_truth and delivery_truth.get("ppv_unpaid")
            ) or bool(ppv_status and ppv_status.get("active")),
            cooling=cooling,
            soft_unpaid=soft_unpaid,
            mem=mem,
            fan_message=fan_message or "",
        )
        if move:
            tech_name = move.name
            turn_blocks.append(technique_policy.turn_block(move))
            print(
                f"   move: {move.name} fam={move.family_id or '-'} "
                f"why={move.why} (pack={pack_id})"
            )
        if recent_emojis:
            turn_blocks.append(
                f"EMOJI BAN — you used these recently: {recent_emojis}. "
                "Do NOT repeat these combos. Pick something different or use no emoji."
            )
        # Compact continuity — keep her in the long thread without a fat CONTEXT wall
        beat = scheme_guard.thread_beat_block(turns, mem)
        if beat:
            turn_blocks.append(beat)
        _early_unpaid = bool(
            (delivery_truth and delivery_truth.get("ppv_unpaid"))
            or (ppv_status and ppv_status.get("active"))
        )
        if msgs_n < 8 and not _early_unpaid:
            turn_blocks.append(
                "EARLY ROMANCE THIS TURN (first ~8 messages — strategy law):\n"
                "- Goal: make him fall for you — warm, hot, chosen, almost-boyfriend.\n"
                "- DO: compliments, dirty-sweet flirt, ask about him, ASK for HIS selfie/pic, "
                "mirror his energy, build heat.\n"
                "- DON'T: guilt, abandonment ('guys leave / poof they're gone'), rival jealousy, "
                "fake emergency, ego challenges, pressure-sell.\n"
                "- Those darker cards come LATER when he's hooked. Right now you seduce.\n"
                "- English only. One short WhatsApp bubble."
            )
        if pack_id == "phase_hook" and msgs_n <= 2:
            turn_blocks.append(
                "WELCOME THIS TURN (first messages):\n"
                "- Soft subscribe welcome — glad he subbed, now you can finally talk.\n"
                "- Casual cute vibe like: \"so glad you subscribed, now we can finally talkk 😋\" "
                "(English only).\n"
                "- No sell, no free photo pitch, no price. One warm question max.\n"
                "- Do NOT jump straight into dirty / content push."
            )
        print(
            f"   simple: cooling={cooling} rival_banned={ban_rival} "
            f"banned_opens={len(banned_opens)} pack={pack_id} "
            f"move={tech_name or '-'}"
        )
    else:
        # MANIPULATION ENGINE first (loudest), then situation pack
        exclude_techs = (
            fan_memory.recent_techniques(fan_uuid, n=4) if fan_uuid else []
        )
        manip_banner = manipulation.render_banner(
            pack_id,
            fan_uuid=fan_uuid or "",
            msgs=msgs_n,
            reject_count=objection_step,
            force_name=force_tech,
            no_lock=no_lock,
            soft_support=soft_support,
            exclude_names=exclude_techs,
            ban_withdrawal=ban_withdrawal,
            ban_rival_fan=ban_rival,
        )
        tech = manipulation.pick_technique(
            pack_id,
            fan_uuid=fan_uuid or "",
            msgs=msgs_n,
            reject_count=objection_step,
            force_name=force_tech,
            no_lock=no_lock,
            soft_support=soft_support,
            exclude_names=exclude_techs,
            ban_withdrawal=ban_withdrawal,
        )
        tech_name = tech[0] if tech else ""
        if manip_banner:
            turn_blocks.append(manip_banner)
            print(f"   manip: {tech_name} (pack={pack_id})")

        turn_blocks.append(packs.render(pack_id, facts_line=facts_line))

    # Code-first sell: SELL STATUS is law. Never dump full catalog when not attaching
    # (that menu taught the model to invent prices).
    turn_blocks.append(vault_catalog.sell_status_prompt_block(offer))
    if offer:
        turn_blocks.append(vault_catalog.offer_prompt_block(offer))

    unpaid_gate = bool(delivery_truth and delivery_truth.get("ppv_unpaid"))
    status_active = bool(ppv_status and ppv_status.get("active"))
    sell_paused = fan_memory.sell_pressure_paused(mem)
    # Fan asking what's IN the unpaid lock — filthy describe, not price frame
    if (
        not sell_paused
        and (unpaid_gate or status_active)
        and re.search(
        r"(?i)\b("
        r"how\s+do\s+you\s+look|what\s+do\s+you\s+look\s+like|"
        r"what.?s\s+in\s+(the|that)\s+(photo|pic)|"
        r"what\s+are\s+you\s+wearing|describe\s+(the|that|your)\s+(photo|pic)|"
        r"c[oó]mo\s+(est[aá]s|sales|te\s+ves)|qu[eé]\s+se\s+ve"
        r")\b",
        fan_message or "",
    )
    ):
        label = str((ppv_status or {}).get("label") or "").strip()
        label_bit = f' ("{label}")' if label else ""
        turn_blocks.append(
            "LOCK TEASE ASK — CRITICAL:\n"
            f"- He asked how you look / what's in the unpaid lock{label_bit}.\n"
            "- ANSWER with a short filthy WhatsApp describe of THAT photo "
            "(pose, body, vibe) + light unlock nudge.\n"
            "- HARD BAN this turn: discounts, 'i hear you', soft-exit, "
            "'when you're ready', price lectures."
        )
    # Friction path: unpaid exists but router chose reconnect — no unlock nag
    soft_unpaid = bool(
        sell_paused
        or (
            (unpaid_gate or status_active)
            and pack_id == "phase_pull"
            and route_result
            and (route_result.active or {}).get("ppv_unpaid")
        )
    )
    # One LOCK STATUS block only — skip when voice note attaches (fan wants audio, not lock push)
    if soft_unpaid and not voice_will_send:
        turn_blocks.append(
            "LOCK STATUS — UNPAID EXISTS BUT DO NOT PITCH THIS TURN:\n"
            "- There is still one unpaid lock in chat — do NOT stack another.\n"
            "- He is upset / cooling / calling out pressure. Reconnect as a human.\n"
            "- HARD BAN: unlock FOMO, 'ábrelo ya', scarcity spam, guilt.\n"
            "- At most one soft line that something is still there — no close question."
        )
    elif (unpaid_gate or status_active) and not voice_will_send:
        if status_active and ppv_status:
            turn_blocks.append(_ppv_truth_block(ppv_status))
        elif ppv_status and (
            ppv_status.get("price") is not None
            or ppv_status.get("minutes_left") is not None
            or ppv_status.get("label")
        ):
            forced = dict(ppv_status)
            forced["active"] = True
            forced["purchased"] = False
            turn_blocks.append(_ppv_truth_block(forced))
        else:
            turn_blocks.append(
                "LOCK STATUS — VERIFIED THIS TURN (ACTIVE UNPAID CANDADO):\n"
                "- ONE timed lock is STILL waiting (not unlocked yet).\n"
                "- Soft nudge only if he is warm — never nag every turn.\n"
                "- Do NOT tease another photo, video, or bundle.\n"
                "- Gratis ask → no more free; that lock is the only product."
            )
    elif ppv_status and not voice_will_send:
        turn_blocks.append(_ppv_truth_block(ppv_status))

    if re.search(r"(?i)\b(v[ií]deo|video|clip|grabaci[oó]n|film|filmar)\b", fan_message or ""):
        if status_active or unpaid_gate:
            turn_blocks.append(
                "FAN ASKED ABOUT VIDEO — CRITICAL:\n"
                "- You have NO videos. Catalog = PHOTOS only.\n"
                "- ONE unpaid PHOTO lock is already waiting (see LOCK STATUS above).\n"
                "- Say clearly: no video — only THAT photo at the REAL price in LOCK STATUS.\n"
                "- Never promise video, clip, bundle, or 'both for $X'. Push the waiting photo lock."
            )
        else:
            turn_blocks.append(
                "FAN ASKED ABOUT VIDEO: You have NO videos — photos only. "
                "Never promise to record or send a clip. Tease a vault PHOTO only if STATUS attaches."
            )

    # Fan calling out fake wait-time — obey LOCK STATUS "sent X min ago"
    if (
        (status_active or unpaid_gate)
        and ppv_status
        and re.search(
            r"(?i)\b("
            r"\d+\s*minut|"
            r"lleva\w*\s+\d+|"
            r"llevas\s+\d+|"
            r"como\s+que\s+llev|"
            r"que\s+dices|"
            r"no\s+me\s+he\s+ido|"
            r"just\s+(sent|dropped)|only\s+\d+\s*min"
            r")\b",
            fan_message or "",
        )
    ):
        ago = ppv_status.get("ago") or "recently"
        left = ppv_status.get("minutes_left")
        left_bit = f" ~{left} min left on the clock." if left is not None else ""
        turn_blocks.append(
            "TIMING CORRECTION — CRITICAL:\n"
            f"- LOCK STATUS says this photo was sent {ago}.{left_bit}\n"
            "- You previously invented a wrong wait time. Own it briefly / soft laugh, "
            "then use ONLY that real 'sent … ago' number — never 'da igual' with both numbers.\n"
            "- Do NOT claim you've been waiting longer than LOCK STATUS."
        )

    # Fan bluffs that he saw/liked a lock he never paid for (common after expiry)
    never_bought = scheme_guard.last_ppv_never_bought(mem, ppv_status)
    fan_saw_bluff = never_bought and scheme_guard.fan_claims_saw_ppv(
        fan_message or ""
    )
    if never_bought and not voice_will_send:
        if status_active or unpaid_gate:
            if fan_saw_bluff:
                turn_blocks.append(
                    "FAN BLUFF — CRITICAL:\n"
                    "- He claims he liked/saw the locked photo, but LOCK STATUS says "
                    "he has NOT purchased it. He cannot have seen it.\n"
                    "- Do NOT say 'me alegro que te gustara' / 'glad you liked it' / "
                    "'esa era solo un poquito'.\n"
                    "- Call the bluff playfully and push THIS unlock — scroll up."
                )
        else:
            # Expired / none — only shout when he claims he saw it, or soft-note
            # when we are NOT attaching a new lock (don't block a fresh close).
            if fan_saw_bluff:
                turn_blocks.append(
                    "FAN BLUFF — CRITICAL:\n"
                    "- Last timed PPV expired or was unsent WITHOUT purchase. "
                    "He NEVER unlocked that photo. He is lying or teasing.\n"
                    "- HARD BAN: 'me alegro que te gustara', 'glad you liked it', "
                    "'esa era solo un poquito', 'qué te pareció'.\n"
                    "- Call the bluff with a smirk: he never opened it / it vanished unpaid / "
                    "he can't know how hot it was.\n"
                    "- Do NOT apologize or gift a replacement for content he never bought.\n"
                    + (
                        "- SELL STATUS is ATTACHING a NEW lock this turn — sell THAT "
                        "(different from the expired one). Do not validate the old photo."
                        if offer
                        else "- Flirt / reconnect; only sell if SELL STATUS says ATTACHING."
                    )
                )
            elif not offer:
                turn_blocks.append(
                    "LAST PPV TRUTH:\n"
                    "- The previous timed lock left WITHOUT purchase (expired/unsent). "
                    "He never saw that photo.\n"
                    "- Do not talk about it as if he already enjoyed it."
                )

    if delivery_truth and delivery_truth.get("free_in_chat") is True:
        turn_blocks.append(
            "DELIVERY TRUTH: your FREE photo IS already in this chat. "
            "Tell him to scroll up. Do not re-gift. Do not invent a glitch."
        )
    elif delivery_truth and delivery_truth.get("free_in_chat") is False:
        turn_blocks.append(
            "DELIVERY TRUTH: Fanvue chat does NOT show any free gift from you. "
            "Do NOT claim you already sent/regalaste a photo. That would be a lie. "
            "If a photo attaches this turn, gift THAT. Otherwise apologize briefly and flirt."
        )

    vision_desc = None
    if fan_vision:
        vision_desc = (
            fan_vision.get("description")
            or fan_vision.get("summary")
            or ""
        ).strip() or None
    if not vision_desc and mem.get("last_fan_image_desc") and re.search(
        r"(?i)\b(qu[eé] (es|ves|hay)|what (is|do you see|do u see)|dime que|describe)\b",
        fan_message or "",
    ):
        vision_desc = mem["last_fan_image_desc"]
    if vision_desc:
        from core.fan_vision import vision_system_block

        turn_blocks.append(vision_system_block(vision_desc))

    if voice_will_send:
        turn_blocks.append(
            "VOICE NOTE THIS TURN: An audio file attaches after your text — naturally, no intro. "
            "Just continue the conversation normally. Do NOT announce it, promote it, or say "
            "'I recorded something' / 'listen to this' / 'I have something for you'. "
            "HARD BAN this turn: 'pídemelo', 'ask me nicely', asking him again to beg — "
            "he already asked / complied. The audio is coming. Your text is a short normal reply. "
            "NEVER write '[Voice Note:…]', 'Voice Note:', '(breathy, soft)', or any TTS/stage "
            "direction in chat — and do NOT paste the spoken audio script into the bubble."
        )
    else:
        turn_blocks.append(
            "AUDIO THIS TURN: NO voice note is being sent. "
            "Do NOT say you recorded something, do NOT tease 🎙️, do NOT promise audio delivery. "
            "If he asks for audio, flirt and imply you might — but never claim you sent or are sending one now. "
            "Do NOT loop 'pídemelo / ask me for it' if you already asked that in the recent thread."
        )

    if not lean:
        recent_text = " ".join(
            t["content"] for t in turns[-4:] if t["role"] == "user"
        )
        lore_block = lorebook.render_block(recent_text)
        if lore_block:
            turn_blocks.append(lore_block)

    name_note, name_max_uses = _name_budget_note(
        mem.get("name") or "",
        turns,
        name_confirmed=bool(mem.get("name_confirmed")),
    )

    if lean:
        core_prompt = None
        if simple:
            from core.prompt_core import get_active_persona, PROMPT_VERSION

            core_prompt = get_active_persona()
        else:
            PROMPT_VERSION = "legacy"
        messages, sizes = prompt_layers.build_system_layers(
            card_block=card_block,
            language_block=language.language_system_block(want_spanish),
            time_block=persona_time.time_system_block(),
            name_block=name_note,
            turn_blocks=turn_blocks,
            core_prompt=core_prompt,
        )
        print(
            f"   prompt: v={PROMPT_VERSION} CORE={sizes['core']} CARD={sizes['card']} "
            f"TURN={sizes['turn']} total_sys={sizes['system_total']} "
            f"pack={pack_id}{' SIMPLE' if simple else ''}"
        )
    else:
        # Legacy fat path (discouraged)
        messages = [
            {"role": "system", "content": EMMA_SYSTEM_PROMPT},
            {"role": "system", "content": language.language_system_block(want_spanish)},
            {"role": "system", "content": persona_time.time_system_block()},
        ]
        if card_block:
            messages.append({"role": "system", "content": card_block})
        for b in turn_blocks:
            messages.append({"role": "system", "content": b})
        if name_note:
            messages.append({"role": "system", "content": name_note})
        messages.append(
            {
                "role": "system",
                "content": (
                    "PRIORITY: CLIENT CARD + recent chat history are the only truth about him."
                ),
            }
        )

    # Lean author: pack + MANDATORY technique nudge
    if lean and simple:
        from core import technique_policy as _tp
        from core.account_context import creator_display_name

        _creator = creator_display_name()
        move_bit = (
            _tp.author_steer(tech_name)
            if tech_name
            else " Skip dark-psych moves this turn (comfort/cooling)."
        )
        note = (
            f"[{_creator} on WhatsApp. ENGLISH ONLY — even if he writes Spanish. "
            "Horny girlfriend texting — NOT a sales agent, NOT an essay. "
            "Informal chat slang OK (u/rn/idk/lol/haha/babe). "
            "Light punctuation, lowercase fine, react first. "
            "Usually ONE short bubble (~80-140 chars). Pet name most turns. "
            "Emojis only if natural — vary or skip; never same combo twice. "
            "Filthy when he's hot; bratty then warm. "
            "ZERO Spanish words (no mira/bebé/joder/guapo). "
            "No quotation marks around his words. "
            "No Ay…/Mmm… openers. No would-you-like / exclusive content / special offer. "
            "Answer his LAST message in context of the recent thread — "
            "do not ignore what he said minutes ago in THIS chat. "
            "ANTI-LOOP: never repeat the same question/beat from your last 2 replies. "
            "Never loop abandonment lines (most guys leave / poof they're gone / you're quiet). "
            "Early chat: seduce / ask his pics — save guilt-rival-emergency for later. "
            f"{move_bit.strip()} Readable but messy like real DMs. "
            "Sell only what STATUS attaches.]"
        )
    elif lean:
        from core.account_context import creator_display_name

        _creator = creator_display_name()
        note = (
            f"[{_creator} texting. ENGLISH ONLY. Pack={pack_id}. "
            f"1–2 short bubbles, under ~220 total characters. Light pet names OK; "
            f"real name sometimes if ADDRESSING allows — "
            f"never spam \"Ay {{name}}\" every bubble. Zero Spanish.]"
        )
        if tech_name:
            note += manipulation.author_nudge(pack_id, tech_name)
    else:
        note = author_note_for(decision, want_spanish=want_spanish, lean=lean)
        if tech_name:
            note += manipulation.author_nudge(pack_id, tech_name)
    if pack_id == "ppv_unpaid" or (ppv_status and ppv_status.get("active")):
        if not voice_will_send and not sell_paused:
            note += (
                " UNPAID LOCK: push ONLY that waiting photo (scroll up). "
                "No other photo, no video, no bundle, no 'the one I mentioned'. "
                "Gratis ask → deny, push unlock."
            )
        elif sell_paused:
            note += (
                " SELL COOLDOWN: he declined / can't pay — NO unlock nag, NO price. "
                "React to his roleplay or vibe only. Bond or heat, zero $."
            )
    paid_offer_now = bool(
        offer
        and float(offer.get("price") or 0) > 0
        and int(offer.get("level") or 0) > 0
    )
    if offer:
        is_free = not paid_offer_now
        if is_free:
            note += " FREE photo attached — one short flirty line."
        else:
            note += (
                f" PAID lock ${offer.get('price'):.0f} attaches WITH your first bubble. "
                "Tease THAT photo and lock it. "
                "Do NOT ask if he wants it. Do NOT offer free/gratis. "
                "Do NOT ask him for his face/pic/selfie — wrong direction."
            )
    if (
        fan_vision
        and (fan_vision.get("description") or "").strip()
        and not paid_offer_now
    ):
        note += (
            " FAN PHOTO attached — obey vision block: react to what's IN the pic. "
            "If it's not HIS body / it's your own content / wrong pic: call it out, "
            "don't fake arousal. Demand HIS pic if he dodged."
        )
    note = prompt_layers.clip_author(note)

    turns_out = [dict(t) for t in turns]
    hist_n = len(turns_out)
    for i in range(len(turns_out) - 1, -1, -1):
        if turns_out[i]["role"] == "user":
            turns_out[i]["content"] = f"{turns_out[i]['content']}\n\n{note}"
            break
    messages.append(
        {
            "role": "system",
            "content": (
                f"CHAT HISTORY ({hist_n} turns, chronological, newest last). "
                "This thread is ground truth — stay consistent with what was said; "
                "react to his LAST message in context. "
                "Do not re-ask something you already asked in the last turns."
            ),
        }
    )
    messages.extend(turns_out)

    confirmed = bool(mem.get("name_confirmed"))
    usable_name = _usable_fan_name(mem.get("name") or "", confirmed=confirmed)
    ghost_free_ban = bool(
        delivery_truth and delivery_truth.get("free_in_chat") is False
    )


    return AssembledTurn(
        messages=messages,
        decision=decision,
        pack_id=pack_id or "",
        tech_name=tech_name or "",
        phase_name=phase_name,
        want_spanish=want_spanish,
        fan_uuid=fan_uuid,
        fan_handle=fan_handle or "",
        fan_message=fan_message,
        usable_name=usable_name,
        name_confirmed=confirmed,
        name_max_uses=name_max_uses,
        turns=turns,
        offer=offer,
        ppv_status=ppv_status,
        delivery_truth=delivery_truth,
        voice_will_send=voice_will_send,
        lock_active=lock_active,
        no_lock=no_lock,
        status_active=status_active,
        unpaid_gate=unpaid_gate,
        never_bought=never_bought,
        fan_saw_bluff=fan_saw_bluff,
        ghost_free_ban=ghost_free_ban,
        turn_action=turn_action,
    )


