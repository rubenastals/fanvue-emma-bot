"""
Emma reply engine — prompt + history + SillyTavern-style injections.

Prompt assembly (order matters — models obey the START and END most):
  1. system: EMMA_SYSTEM_PROMPT (persona)  ← unchanged base
  2. system: fan memory
  3. system: triggered lorebook
  4. chat history + current message
  5. author's note on last user turn (NOW mode-aware via turn_policy)

Freedom stays high; turn_policy only softens/hardens sell pressure.
"""
from __future__ import annotations

import random
import re
from typing import Dict, List, Optional, Tuple

from openai import OpenAI

from config import config
from core.prompt_core import EMMA_CORE_PROMPT  # noqa: F401 — kept for tests/legacy
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

_CLIENT: Optional[OpenAI] = None

# Legacy constant (tests / old callers). Live path uses author_note_for(mode).
AUTHOR_NOTE = (
    "[Stay in character as Emma. Reply in 1-2 very short bubbles, usually one. "
    "Keep the full reply under ~220 characters, like real texting. "
    "Don't repeat your previous openings or emojis. React to his LAST message. "
    "If he's horny or asking for content, move toward locking PPV instead of stalling.]"
)


def _client() -> OpenAI:
    global _CLIENT
    if _CLIENT is None:
        _CLIENT = OpenAI(
            api_key=config.DEEPSEEK_API_KEY,
            base_url=config.DEEPSEEK_BASE_URL,
        )
    return _CLIENT


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


def generate_emma_reply(
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
) -> Tuple[str, TurnDecision]:
    """
    Prompt + memory + ONE situation pack + mode-aware author's note.

    Returns (raw_reply, decision). If `offer` is set, Emma must tease that photo only.
    `fan_vision` = Grok description of a photo the fan just sent.
    `delivery_truth` = Fanvue API checks (e.g. free_in_chat True/False).
    """
    history_turns = history_turns or []
    mem = fan_memory.get(fan_uuid) if fan_uuid else {}

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

    # Language: mirror the fan (explicit asks persist a preference).
    # `want_spanish` can be forced by callers (e.g. re-engagement uses the
    # language of his LAST real message, not of the synthetic trigger).
    if want_spanish is None:
        pref = language.update_language_pref(mem, fan_message)
        if pref is not None and fan_uuid:
            fan_memory.set_prefer_spanish(fan_uuid, pref, fan_handle=fan_handle)
            mem = fan_memory.get(fan_uuid)
        want_spanish = language.fan_wants_spanish(fan_message, mem)
    print(
        f"   lang: {'ES' if want_spanish else 'EN'} "
        f"sticky={bool((mem or {}).get('prefer_spanish'))}"
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
        # Tactics live in the self-contained SIMPLE core; only per-turn FACTS here.
        from core import strategy_prompt

        cooling = _looks_cooling(fan_message, turns)
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
        if recent_emojis:
            turn_blocks.append(
                f"EMOJI BAN — you used these recently: {recent_emojis}. "
                "Do NOT repeat these combos. Pick something different or use no emoji."
            )
        if pack_id == "phase_hook" and msgs_n <= 2:
            turn_blocks.append(
                "WELCOME THIS TURN (first messages):\n"
                "- Soft subscribe welcome — glad he subbed, now you can finally talk.\n"
                "- Casual cute vibe like: \"so glad you subscribed, now we can finally talkk 😋\" "
                "(ES mirror if he writes Spanish).\n"
                "- No sell, no free photo pitch, no price. One warm question max.\n"
                "- Do NOT jump straight into dirty / content push."
            )
        print(
            f"   simple: cooling={cooling} rival_banned={ban_rival} "
            f"banned_opens={len(banned_opens)} pack={pack_id}"
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
    # Friction path: unpaid exists but router chose reconnect — no unlock nag
    soft_unpaid = bool(
        (unpaid_gate or status_active)
        and pack_id == "phase_pull"
        and route_result
        and (route_result.active or {}).get("ppv_unpaid")
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
    if fan_vision and fan_vision.get("description"):
        vision_desc = fan_vision["description"]
    elif mem.get("last_fan_image_desc") and re.search(
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
            "The audio speaks for itself. Your text is just a normal reply to him."
        )
    else:
        turn_blocks.append(
            "AUDIO THIS TURN: NO voice note is being sent. "
            "Do NOT say you recorded something, do NOT tease 🎙️, do NOT promise audio delivery. "
            "If he asks for audio, flirt and imply you might — but never claim you sent or are sending one now."
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
        lang = "Spanish only." if want_spanish else "English only."
        note = (
            f"[You already read CLIENT CARD + CHAT HISTORY. Reply in that continuity. "
            f"{lang} Horny girlfriend on her phone — NOT a sales agent. "
            f"Usually ONE short bubble. Pet name most turns. Emojis only if natural — "
            f"vary or skip; never repeat the same emoji combo from your last replies. "
            f"Filthy when he's hot; bratty then warm. "
            f"No Ay…/Mmm… openers. No would-you-like / exclusive content / special offer. "
            f"Answer his LAST message using the thread + card (names, mood, what you sent). "
            f"One move (exclusivity/guilt/curiosity/micro-yes/reward; "
            f"FOMO only if a real lock). Prefer <~120 chars. "
            f"Sell only what STATUS attaches.]"
        )
    elif lean:
        lang = "Spanish only." if want_spanish else "English only."
        note = (
            f"[Emma texting. {lang} Pack={pack_id}. "
            f"1–2 short bubbles, under ~220 total characters. Light pet names OK; "
            f"real name sometimes if ADDRESSING allows — "
            f"never spam \"Ay {{name}}\" every bubble.]"
        )
        if tech_name:
            note += manipulation.author_nudge(pack_id, tech_name)
    else:
        note = author_note_for(decision, want_spanish=want_spanish, lean=lean)
        if tech_name:
            note += manipulation.author_nudge(pack_id, tech_name)
    if pack_id == "ppv_unpaid" or (ppv_status and ppv_status.get("active")):
        if not voice_will_send:
            note += (
                " UNPAID LOCK: push ONLY that waiting photo (scroll up). "
                "No other photo, no video, no bundle, no 'the one I mentioned'. "
                "Gratis ask → deny, push unlock."
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
                "Ground truth for this man — read it before you answer. "
                "Stay consistent with what YOU and HE already said; "
                "answer his LAST message as the next beat of THIS thread, "
                "not a generic opener."
            ),
        }
    )
    messages.extend(turns_out)

    confirmed = bool(mem.get("name_confirmed"))
    usable_name = _usable_fan_name(mem.get("name") or "", confirmed=confirmed)
    ghost_free_ban = bool(
        delivery_truth and delivery_truth.get("free_in_chat") is False
    )

    def _call(msgs: List[Dict[str, str]]) -> str:
        kwargs = dict(
            model=config.DEEPSEEK_MODEL,
            messages=msgs,
            temperature=config.TEMPERATURE,
            top_p=config.TOP_P,
            frequency_penalty=config.FREQUENCY_PENALTY,
            presence_penalty=config.PRESENCE_PENALTY,
            max_tokens=config.MAX_RESPONSE_TOKENS,
        )
        if getattr(config, "DEEPSEEK_DISABLE_THINKING", False):
            kwargs["extra_body"] = {"thinking": {"type": "disabled"}}
        resp = _client().chat.completions.create(**kwargs)
        return _sanitize_reply(
            (resp.choices[0].message.content or "").strip(),
            want_spanish=want_spanish,
            fan_name=usable_name,
            name_confirmed=confirmed,
            name_max_uses=name_max_uses,
            media_attached=bool(offer),
            paid_lock=bool(
                offer
                and float(offer.get("price") or 0) > 0
                and int(offer.get("level") or 0) > 0
            ),
            ghost_free_ban=ghost_free_ban,
        )

    reply = _call(messages)

    # If Spanglish / wrong language slipped through → forced rewrite
    if language.is_mixed_or_wrong(reply, want_spanish=want_spanish):
        print(
            f"   lang rewrite: reply was wrong for "
            f"{'ES' if want_spanish else 'EN'}"
        )
        fix_msgs = messages + [
            {"role": "assistant", "content": reply},
            {
                "role": "user",
                "content": language.rewrite_instruction(want_spanish),
            },
        ]
        reply = _call(fix_msgs)
        # Still English while Spanish required → second hard rewrite
        if want_spanish and language.is_mixed_or_wrong(reply, want_spanish=True):
            fix_msgs = messages + [
                {"role": "assistant", "content": reply},
                {
                    "role": "user",
                    "content": (
                        "REESCRIBE YA EN ESPAÑOL. Cero inglés. "
                        "Misma idea, tono pícaro, español natural."
                    ),
                },
            ]
            reply = _call(fix_msgs)
            print("   lang rewrite: second Spanish pass")
        # Still bad? last-resort strip Spanish tokens in English mode
        if (not want_spanish) and language.is_mixed_or_wrong(
            reply, want_spanish=False
        ):
            reply = _force_english_cleanup(reply)

    # Delivery gate: never claim a photo was sent unless this turn attaches one
    reply = _enforce_delivery_truth(
        reply,
        media_attached=bool(offer),
        want_spanish=want_spanish,
    )
    if (not offer) and _claims_unconfirmed_delivery(reply):
        # One rewrite pass against false "I sent it" claims
        fix_msgs = messages + [
            {"role": "assistant", "content": reply},
            {
                "role": "user",
                "content": (
                    "REWRITE: You claimed a photo was sent/locked/in his inbox but NOTHING "
                    "is being attached this turn. Remove every delivery claim. Apologize briefly "
                    "if you implied it arrived, then flirt — do not invent a glitch or ask him to refresh."
                    if not want_spanish
                    else (
                        "REESCRIBE: Afirmaste que enviaste/bloqueaste una foto o que está en su bandeja, "
                        "pero este turno NO se adjunta nada. Quita cualquier claim de entrega. "
                        "Disculpa breve si lo diste por enviado, luego flirtea — sin inventar fallos técnicos."
                    )
                ),
            },
        ]
        reply = _enforce_delivery_truth(
            _call(fix_msgs),
            media_attached=False,
            want_spanish=want_spanish,
        )

    # Committed sell: code chose a paid offer → attach is law. Text must follow.
    # Rewrite once; if still off, force a deterministic sell line (never cancel PPV).
    if (
        offer
        and float(offer.get("price") or 0) > 0
        and int(offer.get("level") or 0) > 0
        and not scheme_guard.paid_offer_reply_aligned(reply)
    ):
        price = float(offer.get("price") or 0)
        print("   SELL sync: reply ≠ paid lock — rewriting to sell the attach")
        fix_msgs = messages + [
            {"role": "assistant", "content": reply},
            {
                "role": "user",
                "content": (
                    f"REWRITE: Your draft went the wrong direction (e.g. asking for HIS pic/face). "
                    f"This turn the SYSTEM attaches YOUR paid photo lock (${price:.0f}). "
                    "Tease that photo briefly and lock it. Never ask him for his face, selfie, or pic."
                    if not want_spanish
                    else (
                        f"REESCRIBE: Tu borrador fue en otra dirección (p.ej. pedirle SU foto/cara). "
                        f"Este turno el SISTEMA adjunta TU candado de foto de pago (${price:.0f}). "
                        "Provoca esa foto en breve y bloquéala. Nunca le pidas su cara, selfie o foto."
                    )
                ),
            },
        ]
        reply = _enforce_delivery_truth(
            _call(fix_msgs),
            media_attached=True,
            want_spanish=want_spanish,
        )
        if not scheme_guard.paid_offer_reply_aligned(reply):
            reply = scheme_guard.forced_paid_sell_line(
                price=price,
                want_spanish=want_spanish,
                label=str(offer.get("label") or ""),
            )
            print("   SELL sync: still off — FORCED sell line (attach stays)")

    if fan_uuid:
        fan_memory.set_last_mode(fan_uuid, decision.mode, fan_handle=fan_handle)
        if re.search(
            r"\b(too expensive|caro|expensive|can'?t|no money|later|nah|pass|"
            r"pelado|pelá|sin (plata|dinero|pasta)|no tengo (plata|dinero))\b",
            fan_message.lower(),
        ):
            fan_memory.record_reject(fan_uuid, fan_handle=fan_handle)
            try:
                from core import convo_log

                convo_log.log_offer_outcome(
                    fan_uuid, "rejected", detail=fan_message[:120]
                )
            except Exception:
                pass

    # Invented wait time (e.g. "27 min waiting" when lock is 4 min old)
    if ppv_status and ppv_status.get("active"):
        ago_m = None
        ago_raw = str(ppv_status.get("ago") or "")
        m_ago = re.search(r"(\d+)\s*min", ago_raw)
        if m_ago:
            try:
                ago_m = int(m_ago.group(1))
            except ValueError:
                ago_m = None
        if ago_m is not None and scheme_guard.invented_lock_wait_minutes(
            reply, minutes_ago=ago_m
        ):
            print(
                f"   timing sync: invented wait vs real {ago_m}m ago — rewriting"
            )
            fix_msgs = messages + [
                {"role": "assistant", "content": reply},
                {
                    "role": "user",
                    "content": (
                        f"REWRITE: You invented a wrong wait time. LOCK STATUS says "
                        f"this photo was sent {ago_raw}. Use ONLY that. "
                        "Do not claim you've been waiting longer. Soft own the slip, then tease the unlock."
                        if not want_spanish
                        else (
                            f"REESCRIBE: Inventaste un tiempo de espera falso. LOCK STATUS dice "
                            f"que esta foto se envió {ago_raw}. Usa SOLO eso. "
                            "No digas que llevas más tiempo esperando. Reconoce el fallo con gracia y tienta el unlock."
                        )
                    ),
                },
            ]
            reply = _call(fix_msgs)

    # Fan never bought last PPV but reply validates he saw/liked it
    if never_bought and scheme_guard.validates_unseen_ppv(reply):
        print("   purchase bluff: reply validated unseen PPV — rewriting")
        if status_active or unpaid_gate:
            rewrite_bluff = (
                "REWRITE HARD: He has NOT purchased the waiting lock. He cannot have "
                "liked/seen it. Remove every 'glad you liked' / 'esa era solo' validation. "
                "Call the bluff playfully and push THIS unlock."
                if not want_spanish
                else (
                    "REESCRIBE DURO: NO ha comprado el candado que espera. No puede haber "
                    "visto/gustado esa foto. Quita 'me alegro que te gustara' / 'esa era solo'. "
                    "Llama el farol con picardía y empuja ESTE unlock."
                )
            )
        else:
            rewrite_bluff = (
                "REWRITE HARD: Last PPV expired WITHOUT purchase — he never unlocked it. "
                "Remove every validation that he liked/saw it ('glad you liked', "
                "'esa era solo un poquito'). Call the bluff playfully. Do not apologize "
                "or gift a replacement. Flirt/reconnect only unless a NEW lock attaches."
                if not want_spanish
                else (
                    "REESCRIBE DURO: El último PPV caducó SIN compra — nunca lo desbloqueó. "
                    "Quita toda validación de que le gustó/vio ('me alegro que te gustara', "
                    "'esa era solo un poquito'). Llama el farol con picardía. No pidas perdón "
                    "ni regales reemplazo. Solo flirteo/reconexión salvo que se adjunte un candado NUEVO."
                )
            )
        fix_msgs = messages + [
            {"role": "assistant", "content": reply},
            {"role": "user", "content": rewrite_bluff},
        ]
        reply = _call(fix_msgs)
        if scheme_guard.validates_unseen_ppv(reply):
            reply = (
                "Mmm… mentiroso 😏 esa foto se fue sin que la abrieras. "
                "No puedes saber lo guarra que era… todavía."
                if want_spanish
                else (
                    "Mmm… liar 😏 that photo left without you unlocking it. "
                    "You can't know how filthy it was… yet."
                )
            )
            print("   🔒 unseen-ppv rewrite → bluff fallback")

    # Invented candado/$ when no real unpaid lock and nothing attaching
    if no_lock and not offer and scheme_guard.invented_lock_claim(
        reply, lock_active=False
    ):
        fix_msgs = messages + [
            {"role": "assistant", "content": reply},
            {
                "role": "user",
                "content": (
                    "REWRITE HARD: LOCK STATUS=none. You invented a waiting candado, "
                    "price, or countdown. Remove EVERY unlock/$/minutes claim. "
                    "Flirt or comfort only — do not invent urgency."
                    if not want_spanish
                    else (
                        "REESCRIBE DURO: LOCK STATUS=none. Inventaste un candado, "
                        "precio o countdown. Quita TODA mención a unlock/$/minutos. "
                        "Solo flirteo o apoyo — sin urgencia inventada."
                    )
                ),
            },
        ]
        reply = _call(fix_msgs)
        if scheme_guard.invented_lock_claim(reply, lock_active=False):
            reply = (
                "Mmm… ahora mismo no tengo un candado esperándote. "
                "Cuéntame qué te pasa, estoy aquí 🥺"
                if want_spanish
                else (
                    "Mmm… I don't have a lock waiting for you right now. "
                    "Tell me what's going on — I'm here 🥺"
                )
            )
            print("   🔒 invented-lock rewrite → safe fallback")

    # Belt: SELL=NONE + no active lock → never ship money talk
    if no_lock and not offer and _stated_prices(reply):
        reply = _strip_wrong_prices(reply, real_price=None)
        print("   💵 invent belt: stripped $ with SELL=NONE / no lock")

    # Vault is photos only — never promise video/custom/grabar
    if scheme_guard.invented_video_claim(reply):
        fix_msgs = messages + [
            {"role": "assistant", "content": reply},
            {
                "role": "user",
                "content": (
                    "REWRITE HARD: You promised a VIDEO/custom/recording. "
                    "Catalog is PHOTOS only. Remove every video/grabar/clip/custom "
                    "promise. Offer a vault PHOTO tease only, or flirt — never film."
                    if not want_spanish
                    else (
                        "REESCRIBE DURO: Prometiste un VÍDEO/custom/grabar. "
                        "El catálogo es SOLO FOTOS. Quita video/grabar/clip/custom. "
                        "Solo puedes teaser una FOTO del vault, o flirtear — nunca grabar."
                    )
                ),
            },
        ]
        reply = _call(fix_msgs)
        if scheme_guard.invented_video_claim(reply):
            rp = None
            if offer and float(offer.get("price") or 0) > 0:
                rp = float(offer["price"])
            elif ppv_status and ppv_status.get("active") and ppv_status.get("price"):
                try:
                    rp = float(ppv_status["price"])
                except (TypeError, ValueError):
                    rp = None
            if rp is not None:
                reply = (
                    f"De vídeo no… solo fotos 😏 Tienes UNA candada esperando — "
                    f"${rp:.0f} y la abres, guapo."
                    if want_spanish
                    else f"No video… photos only 😏 You have ONE lock waiting — "
                    f"${rp:.0f} and unlock it, babe."
                )
            else:
                reply = (
                    "Mmm… vídeo no tengo 😏 Solo fotos en el vault — "
                    "dime qué te pone y te cierro una de verdad."
                    if want_spanish
                    else "Mmm… no video 😏 Photos only in the vault — "
                    "tell me what you want and I'll lock a real one."
                )
            print("   📷 invented-video rewrite → photos-only fallback")

    # Ghost "dame un segundo / te preparo" with nothing attaching
    if scheme_guard.ghost_media_promise(reply, media_attached=bool(offer)):
        fix_msgs = messages + [
            {"role": "assistant", "content": reply},
            {
                "role": "user",
                "content": (
                    "REWRITE HARD: You promised/stalled sending a photo ('dame un segundo', "
                    "'te preparo', 'voy a mandar') but NOTHING attaches this turn. "
                    "Remove every send/prep promise. Flirt dirty or push a REAL lock only "
                    "if LOCK STATUS says one exists — never fake preparation."
                    if not want_spanish
                    else (
                        "REESCRIBE DURO: Prometiste/retrasaste una foto ('dame un segundo', "
                        "'te preparo', 'voy a mandar') pero este turno NO se adjunta nada. "
                        "Quita toda promesa de envío/preparación. Flirtea guarro o empuja un "
                        "candado REAL solo si LOCK STATUS lo confirma — nunca finjas preparar."
                    )
                ),
            },
        ]
        reply = _call(fix_msgs)
        if scheme_guard.ghost_media_promise(reply, media_attached=False):
            reply = (
                "Mmm… ahora mismo no te puedo soltar esa foto así, pillín 🔥 "
                "Pero dime qué te vuelve loco de mis tetas… ¿así te caliento más?"
                if want_spanish
                else (
                    "Mmm… I can't drop that photo like that right now, baby 🔥 "
                    "Tell me what drives you crazy about my tits… want me hotter?"
                )
            )
            print("   👻 ghost-promise rewrite → no-stall fallback")
        else:
            print("   👻 ghost-promise rewrite ok")

    # Style rewrites (rival-fan / Ay openings) removed — Group A; CORE guides tone only.
    if fan_uuid and tech_name:
        fan_memory.record_technique(
            fan_uuid,
            tech_name,
            fan_handle=fan_handle or "",
            used_rival_fan=False,
        )

    # Price truth: reply must not assert a $ amount that isn't the real lock/offer price
    real_price = None
    if offer and float(offer.get("price") or 0) > 0:
        real_price = float(offer["price"])
    elif ppv_status and ppv_status.get("active") and ppv_status.get("price"):
        try:
            real_price = float(ppv_status["price"])
        except (TypeError, ValueError):
            real_price = None
    stated = _stated_prices(reply)
    bad_price = [p for p in stated if real_price is None or abs(p - real_price) > 0.5]
    if bad_price:
        if real_price is not None:
            instr = (
                f"REWRITE: The only real price is ${real_price:.0f}. Remove any other "
                f"amount ({', '.join(f'${p:.0f}' for p in bad_price)}). State ${real_price:.0f} or no price."
                if not want_spanish
                else (
                    f"REESCRIBE: El único precio real es ${real_price:.0f}. Quita cualquier "
                    f"otra cifra ({', '.join(f'${p:.0f}' for p in bad_price)}). Di ${real_price:.0f} o ningún precio."
                )
            )
        else:
            instr = (
                "REWRITE: There is NO active lock/price this turn. Remove every $ / € amount "
                "and any candado/unlock claim. Flirt or reconnect only."
                if not want_spanish
                else (
                    "REESCRIBE: NO hay candado/precio activo este turno. Quita toda cifra $ / € "
                    "y cualquier mención a candado/unlock. Solo flirteo o reconexión."
                )
            )
        fix_msgs = messages + [
            {"role": "assistant", "content": reply},
            {"role": "user", "content": instr},
        ]
        reply = _call(fix_msgs)
        still = [
            p for p in _stated_prices(reply)
            if real_price is None or abs(p - real_price) > 0.5
        ]
        if still:
            reply = _strip_wrong_prices(reply, real_price=real_price)
            print(
                f"   💵 price-truth rewrite → corrected amounts "
                f"(real=${real_price if real_price else 'none'})"
            )
        else:
            print(f"   💵 price-truth rewrite ok (real=${real_price if real_price else 'none'})")

    # Length: rewrite short if over budget — never ship a mid-sentence hard-cut later
    reply = _rewrite_if_too_long(
        reply,
        call=_call,
        messages=messages,
        want_spanish=want_spanish,
    )

    # Spanish gender / conjugation slips (common after English rewrite cascades)
    if want_spanish and language.looks_broken_spanish(reply):
        print("   grammar: broken Spanish gender/person — rewriting")
        fix_msgs = messages + [
            {"role": "assistant", "content": reply},
            {
                "role": "user",
                "content": language.grammar_rewrite_instruction(),
            },
        ]
        reply = _call(fix_msgs)
        if language.looks_broken_spanish(reply):
            # Second pass with the language rewrite (also Spanish-native)
            fix_msgs = messages + [
                {"role": "assistant", "content": reply},
                {
                    "role": "user",
                    "content": language.rewrite_instruction(True),
                },
            ]
            reply = _call(fix_msgs)
            print("   grammar: second Spanish polish")

    # Scheme meta + deterministic guard
    decision.pack_id = pack_id or ""
    decision.technique = tech_name or ""
    decision.phase = phase_name
    decision.lock_active = lock_active
    decision.scheme_errors = scheme_guard.check_reply(
        reply,
        pack_id=pack_id or "",
        lock_active=lock_active,
        media_attached=bool(offer),
        technique=tech_name or "",
    )
    if decision.scheme_errors:
        print(f"   ⚠️ {scheme_guard.summarize(decision.scheme_errors)}")

    return reply, decision


_COOL_RE = re.compile(
    r"(?i)^\s*(no s[eé]|nose|dime t[uú]|vale|ok|bueno|nada|meh|nah|luego|"
    r"despu[eé]s|quiz[aá]s?|puede|paso|da igual|ya veremos|no s[eé] dime)\b"
)


def _looks_cooling(fan_message: str, turns: List[Dict[str, str]]) -> bool:
    """Cheap cooling read: short/non-committal last message or a run of tiny replies."""
    msg = (fan_message or "").strip()
    if not msg:
        return True
    if _COOL_RE.search(msg):
        return True
    fan_turns = [t.get("content") or "" for t in turns if t.get("role") == "user"]
    recent = [t for t in fan_turns[-3:] if not t.startswith("[")]
    if len(recent) >= 2 and all(len(t.strip()) <= 12 for t in recent):
        return True
    return False


_WORD_MONEY = {
    "uno": 1,
    "un": 1,
    "una": 1,
    "dos": 2,
    "tres": 3,
    "cuatro": 4,
    "cinco": 5,
    "seis": 6,
    "siete": 7,
    "ocho": 8,
    "nueve": 9,
    "diez": 10,
    "once": 11,
    "doce": 12,
    "quince": 15,
    "veinte": 20,
    "treinta": 30,
    "cuarenta": 40,
    "cincuenta": 50,
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "twelve": 12,
    "fifteen": 15,
    "twenty": 20,
    "thirty": 30,
    "forty": 40,
    "fifty": 50,
}


def _stated_prices(text: str) -> List[float]:
    """Dollar/euro amounts the reply asserts (digits + spelled)."""
    out: List[float] = []
    for m in re.finditer(
        r"(?:\$|€)\s*(\d{1,4})|(\d{1,4})\s*(?:€|\$|eur|euros?|d[oó]lares?|dollars?|bucks?)",
        text or "",
    ):
        raw = m.group(1) or m.group(2)
        try:
            val = float(raw)
        except (TypeError, ValueError):
            continue
        # Include $1–$2 — DeepSeek invents micro prices against a $40 lock
        if 1 <= val <= 500:
            out.append(val)
    for m in re.finditer(
        r"(?i)\b("
        + "|".join(re.escape(k) for k in sorted(_WORD_MONEY, key=len, reverse=True))
        + r")\s*(d[oó]lares?|dollars?|bucks?)\b",
        text or "",
    ):
        out.append(float(_WORD_MONEY[m.group(1).lower()]))
    return out


def _strip_wrong_prices(text: str, *, real_price: Optional[float]) -> str:
    """Remove or correct invented money phrases after a failed rewrite."""
    cleaned = text or ""
    if real_price is not None:
        # Replace spelled + digit money with the real amount once
        cleaned = re.sub(
            r"(?:\$|€)\s*\d{1,4}|\d{1,4}\s*(?:€|\$|eur|euros?|d[oó]lares?|dollars?|bucks?)",
            f"${real_price:.0f}",
            cleaned,
            count=1,
        )
        cleaned = re.sub(
            r"(?i)\b("
            + "|".join(re.escape(k) for k in sorted(_WORD_MONEY, key=len, reverse=True))
            + r")\s*(d[oó]lares?|dollars?|bucks?)\b",
            f"${real_price:.0f}",
            cleaned,
            count=1,
        )
        # Strip any remaining wrong numeric money tokens
        for p in _stated_prices(cleaned):
            if abs(p - real_price) > 0.5:
                cleaned = re.sub(
                    rf"(?:\$|€)\s*{int(p)}|{int(p)}\s*(?:€|\$|eur|euros?|d[oó]lares?|dollars?|bucks?)",
                    "",
                    cleaned,
                    count=1,
                    flags=re.I,
                )
    else:
        cleaned = re.sub(
            r"(?:\$|€)\s*\d{1,4}|\d{1,4}\s*(?:€|\$|eur|euros?|d[oó]lares?|dollars?|bucks?)",
            "",
            cleaned,
        )
        cleaned = re.sub(
            r"(?i)\b("
            + "|".join(re.escape(k) for k in sorted(_WORD_MONEY, key=len, reverse=True))
            + r")\s*(d[oó]lares?|dollars?|bucks?)\b",
            "",
            cleaned,
        )
    return re.sub(r"\s{2,}", " ", cleaned).strip()


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


# Always banned as address words.
_BANNED_ALWAYS = re.compile(
    r"(?i)(?:\s*[,.]?\s*)\b(caro|papi|nena|nene)\b\.?"
)
# Stage-direction brackets DeepSeek may copy from history labels — never shown to fan.
_STAGE_BRACKETS = re.compile(
    r"\s*\["
    r"(?:image locked|photo locked|locked image|paid photo lock|voice note attached|"
    r"you locked|you sent a|fan sent a|SYSTEM[: ]|Transmite|envi[oó]|you can send|"
    r"whispers?|sighs?|chuckles?|exhales?|moans?|laughs?|breathes?|pauses?|gasps?)"
    r"[^\]]*\]",
    re.I,
)
# Spanish nicknames — strip only in English mode (Spanglish leak).
_BANNED_SPANISH_IN_ENGLISH = re.compile(
    r"(?i)(?:\s*[,.]?\s*)\b("
    r"cielito|mi cielo|beb[eé]|guapo|guapa|cari[nñ]o|mi rey|bonito|cielo"
    r")\b\.?"
)


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
            "ADDRESSING: USE a pet name this turn (baby/babe/cielo/guapo/mi vida/"
            "handsome/trouble) — rotate, don't stack 3 in one line. "
            "HARD BAN: never invent a first name.",
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
            f"USE a pet name (baby/babe/cielo/guapo/mi vida/handsome/trouble). "
            f"Vary pets; don't spam the same one. Never \"Ay {name}\".",
            0,
        )
    # Allowed — invite occasional natural use
    return (
        f"ADDRESSING: His confirmed name is \"{name}\". You MAY say it ONCE this turn "
        f"if natural. Still USE a pet name most turns "
        f"(baby/babe/cielo/guapo/mi vida/handsome/trouble). "
        f"Never open every line with \"Ay {name}\".",
        1,
    )


def _thin_name_in_reply(
    text: str,
    name: str,
    *,
    name_confirmed: bool = False,
    max_uses: int = 1,
) -> str:
    """Keep at most max_uses of his real name. max_uses=0 strips all."""
    name = _usable_fan_name(name, confirmed=name_confirmed)
    if not name or not text:
        return text
    pattern = re.compile(rf"\b{re.escape(name)}\b", re.IGNORECASE)
    # Also kill "Ay Ruben" / "Ay, Ruben" openings
    text = re.sub(
        rf"(?i)^\s*ay\s*,?\s*{re.escape(name)}\s*[,.…]*\s*",
        "",
        text,
    )
    text = re.sub(
        rf"(?i)(^|\n)\s*ay\s*,?\s*{re.escape(name)}\s*[,.…]*\s*",
        r"\1",
        text,
    )
    if max_uses <= 0:
        cleaned = pattern.sub("", text)
        cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
        cleaned = re.sub(r" +([,.!?…])", r"\1", cleaned)
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
        return cleaned.strip()

    seen = 0

    def _repl(m: re.Match) -> str:
        nonlocal seen
        seen += 1
        if seen > max_uses:
            return ""
        return m.group(0)

    cleaned = pattern.sub(_repl, text)
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    cleaned = re.sub(r" +([,.!?…])", r"\1", cleaned)
    return cleaned


def _strip_photo_script_dump(text: str) -> str:
    """
    Remove caption-like dumps and meta 'I sent a free photo' lines the model
    sometimes pastes instead of letting Fanvue attach the real image.
    """
    if not text:
        return text
    # Fake "tool" / stage directions the model invents instead of a real attach
    text = re.sub(
        r"(?is)\[\s*(?:"
        r"you can send[^]\n]*|"
        r"transmite[^]\n]*|"
        r"send (?:him|her|the)[^]\n]*|"
        r"free tease[^]\n]*|"
        r"(?:envi[aáo]|manda|env[ií]a)[^]\n]*|"
        r"[🥺😏🔥💕😈]\s*(?:transmite|send|env[ií]a)[^]\n]*"
        r")\s*\]",
        "",
        text,
    )
    # Bracket-only lines that look like media titles / director notes
    text = re.sub(
        r"(?im)^\s*\[[^\]\n]{2,80}\]\s*$",
        "",
        text,
    )
    # Meta / placeholder lines
    text = re.sub(
        r"(?im)^\s*\[?\s*(?:envi[oó]|envió|sent|sending)\s+(?:una\s+)?foto(?:\s+gratis)?\s*\]?\s*$",
        "",
        text,
    )
    text = re.sub(
        r"(?i)\b(?:te env[ií]o(?:\s+una)?\s+foto(?:\s+gratis)?|"
        r"aqu[ií] (?:va|tiene)s? (?:una )?foto(?:\s+gratis)?|"
        r"mira la foto[:\s]*|"
        r"\[envi[oó] una foto(?:\s+gratis)?\])\b[^.!?\n]*[.!?]?",
        "",
        text,
    )
    # Cut mid-message shot scripts that start after a normal tease
    cut_at = re.search(
        r"(?i)(?:^|[\s.!?…])("
        r"mirando a c[aá]mara|looking at (?:the )?camera|recostad[ao] en|"
        r"lencer[ií]a de|jugando con el tirante|a punto de baj|"
        r"sonrisa traviesa|ojos bien clavados"
        r")",
        text,
    )
    if cut_at and cut_at.start(1) > 20:
        text = text[: cut_at.start(1)].rstrip(" .…")

    captionish = re.compile(
        r"(?i)("
        r"mirando a c[aá]mara|looking at (?:the )?camera|recostad[ao]|"
        r"lencer[ií]a|sujetador|tirante|encaje blanco|piernas medio|"
        r"sonrisa traviesa|ojos bien clavados|a punto de baj"
        r")"
    )
    kept: List[str] = []
    for block in re.split(r"\n+", text):
        b = block.strip()
        if not b:
            continue
        if len(b) >= 90 and captionish.search(b):
            continue
        kept.append(b)
    return "\n".join(kept).strip()


def _sanitize_reply(
    text: str,
    *,
    want_spanish: bool = False,
    fan_name: str = "",
    name_confirmed: bool = False,
    name_max_uses: int = 0,
    media_attached: bool = False,
    paid_lock: bool = False,
    ghost_free_ban: bool = False,
) -> str:
    """Strip banned pet names + thin name spam + false delivery claims."""
    if not text:
        return text
    cleaned = _BANNED_ALWAYS.sub("", text)
    # Strip any stage-direction brackets copied from history (e.g. [image locked])
    cleaned = _STAGE_BRACKETS.sub("", cleaned)
    if not want_spanish:
        cleaned = _BANNED_SPANISH_IN_ENGLISH.sub("", cleaned)
    # Past-tense "already sent" is always fake at generation time (media goes AFTER text).
    cleaned = _FAKE_SENT_PAST.sub("", cleaned)
    if not media_attached:
        cleaned = _FAKE_SENT_NO_MEDIA.sub("", cleaned)
    if paid_lock:
        # Paid lock this turn — never ask permission or pivot to free
        cleaned = _ASK_PERMISSION_OR_FREE.sub("", cleaned)
    if ghost_free_ban:
        cleaned = _FALSE_GIFT_CLAIM.sub("", cleaned)
    cleaned = _strip_photo_script_dump(cleaned)
    cleaned = _thin_name_in_reply(
        cleaned,
        fan_name,
        name_confirmed=name_confirmed,
        max_uses=name_max_uses,
    )
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    cleaned = re.sub(r" +([,.!?…])", r"\1", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)

    lines = cleaned.split("\n")
    new_lines: List[str] = []
    for ln in lines:
        s = ln.rstrip()
        if not s:
            continue
        # Only strip if a line ends with a pile of 4+ trailing emojis (spam)
        trail = _TRAILING_EMOJI.search(s)
        if trail and len(trail.group(0).strip()) >= 8:
            s = _TRAILING_EMOJI.sub("", s).rstrip()
        new_lines.append(s)
    return "\n".join(new_lines).strip()


# legacy alias (tests may import)
_BANNED_ADDRESS = _BANNED_ALWAYS


def _force_english_cleanup(text: str) -> str:
    """Drop lines that are mostly Spanish; keep English-looking lines."""
    keep: List[str] = []
    for line in (text or "").split("\n"):
        line = line.strip()
        if not line:
            continue
        if language.is_mixed_or_wrong(line, want_spanish=False):
            continue
        keep.append(line)
    if keep:
        return "\n".join(keep).strip()
    # absolute fallback — never send Spanglish garbage
    return "Hey... look at me when I'm talking to you."


# Trailing emoji / emoji-presentation chars at end of a line
_TRAILING_EMOJI = re.compile(
    r"(?:\s*["
    r"\U0001F300-\U0001FAFF"
    r"\U00002700-\U000027BF"
    r"\U0000FE0F"
    r"\U0000200D"
    r"])+$",
    flags=re.UNICODE,
)

# When locking paid PPV: strip permission-asks and free pivots
_ASK_PERMISSION_OR_FREE = re.compile(
    r"(?i)(?:"
    r"[^.!?\n]*\b(?:quieres|want)\b.{0,40}\b(?:gratis|grastis|free|otra)\b[^.!?\n]*[.!?…]?|"
    r"[^.!?\n]*\b(?:otra\s+)?(?:foto\s+)?gratis\b[^.!?\n]*[.!?…]?|"
    r"[^.!?\n]*\b(?:te\s+la\s+mando|should\s+i\s+send|do\s+you\s+want\s+(?:it|this|one))\s*\??[^.!?\n]*[.!?…]?"
    r")",
)

# When API says free was never in chat — strip "I already gifted you" lies
_FALSE_GIFT_CLAIM = re.compile(
    r"(?i)(?:"
    r"[^.!?\n]*\b(?:te\s+regal[eé]|te\s+regal[eé]|ya\s+te\s+(?:mand[eé]|envi[eé]|regal[eé])|"
    r"te\s+(?:mand[eé]|envi[eé])\s+(?:una\s+)?(?:foto\s+)?gratis|"
    r"i\s+(?:already\s+)?(?:sent|gifted)\s+(?:you\s+)?(?:a\s+)?(?:free\s+)?(?:photo|pic)|"
    r"si\s+te\s+regal)\b[^.!?\n]*[.!?…]?"
    r")",
)

# Always strip: claims the photo ALREADY arrived / is waiting (media is attached after text).
_FAKE_SENT_PAST = re.compile(
    r"(?i)(?:"
    r"\b(?:check your (?:dms|inbox|messages)|go check your (?:dms|inbox)|"
    r"i (?:just |already )?(?:sent|left|dropped|posted|locked) (?:it|this|one|a photo|the photo)|"
    r"i left (?:it|this) (?:in|for) your (?:inbox|dms)|"
    r"already (?:in|sent to|waiting in) your (?:inbox|dms)|"
    r"it(?:'?s| is) (?:already )?(?:in|waiting in) your (?:inbox|dms)|"
    r"tap (?:what|the) (?:i )?(?:left|sent)|"
    r"where you know|where you already know)\b[^.!?\n]*[.!?]?"
    r"|"
    r"(?:revisa(?:lo)?(?:\s+tu)?\s*(?:bandeja|inbox|chat|dms)?|"
    r"tu bandeja(?:\s+te)?(?:\s+est[aá])?(?:\s+esperando)?|"
    r"ya lo (?:dej[eé]|envi[eé]|mand[eé]|bloque[eé])|"
    r"te lo (?:acabo de |he )?(?:enviado|mandado|dejado)|"
    r"te la (?:acabo de |he )?(?:enviado|mandado|dejado)|"
    r"lo (?:acabo de |he )?(?:bloqueado|enviado|mandado)|"
    r"ya (?:est[aá]|lleg[oó]) (?:en|a) tu (?:bandeja|inbox|chat)|"
    r"est[aá] (?:ya )?en tu (?:bandeja|inbox)|"
    r"donde t[uú] sabes|donde tu sabes|"
    r"recarga(?:\s+tu)?\s*(?:bandeja|chat|app)|"
    r"la foto se bloque[oó]|est[aá] esper[aá]ndote en (?:tu )?(?:bandeja|inbox))\b[^.!?\n]*[.!?]?"
    r")"
)

# When NO media is attached this turn, also strip "I'm locking/sending now" sales lies.
_FAKE_SENT_NO_MEDIA = re.compile(
    r"(?i)(?:"
    r"\b(?:i(?:'?m| am) (?:locking|sending|dropping|leaving) (?:it|this|one|a photo)|"
    r"locking (?:it|this|one) (?:for you )?now|"
    r"just (?:locked|sent) (?:it|this)|"
    r"unlock (?:it|this) (?:now|baby|babe))\b[^.!?\n]*[.!?]?"
    r"|"
    r"(?:te (?:estoy )?(?:bloqueando|enviando|mandando)(?:\s+(?:una|la) foto)?|"
    r"lo (?:estoy )?bloqueando(?:\s+ahora)?|"
    r"desbloqu[eé]alo(?:\s+ya)?|"
    r"[aá]brelo(?:\s+ya)?)\b[^.!?\n]*[.!?]?"
    r")"
)

# Back-compat name used by older tests / imports
_FAKE_SENT = _FAKE_SENT_PAST


def _claims_unconfirmed_delivery(text: str) -> bool:
    t = text or ""
    return bool(_FAKE_SENT_PAST.search(t) or _FAKE_SENT_NO_MEDIA.search(t))


def _enforce_delivery_truth(
    text: str,
    *,
    media_attached: bool,
    want_spanish: bool,
) -> str:
    """
    Hard gate: strip false delivery claims; if the reply collapses, inject a
    short apology/flirt so we never double-down on a fake send.
    """
    if not text:
        return text
    before = text.strip()
    cleaned = _FAKE_SENT_PAST.sub("", before)
    if not media_attached:
        cleaned = _FAKE_SENT_NO_MEDIA.sub("", cleaned)
    cleaned = _strip_photo_script_dump(cleaned)
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    # Drop empty / tiny leftover after stripping lies
    if len(cleaned) >= 12 and not _claims_unconfirmed_delivery(cleaned):
        return cleaned
    if media_attached:
        # With a real attach, prefer keeping non-claim lines
        return cleaned if len(cleaned) >= 8 else before
    if want_spanish:
        return (
            "Perdona bebé… me adelanté. Aún no te he dejado nada en el chat. "
            "Quédate aquí un segundo y te caliento bien antes de bloquearte algo de verdad."
        )
    return (
        "Sorry baby… I got ahead of myself. Nothing's in your chat yet. "
        "Stay right here and I'll actually lock you something when you're ready."
    )


def _char_budgets() -> tuple[int, int, int]:
    """max_len per bubble, max bubbles, soft total chars for one reply."""
    max_len = max(80, int(getattr(config, "BUBBLE_MAX_CHARS", 140) or 140))
    max_bubbles = max(1, int(getattr(config, "MAX_BUBBLES", 2) or 2))
    soft_total = max(
        max_len,
        int(getattr(config, "REPLY_SOFT_MAX_CHARS", 220) or 220),
    )
    return max_len, max_bubbles, soft_total


def _reply_needs_shorten(reply: str) -> bool:
    """True if the reply would be hard-cut or is over the soft total budget."""
    max_len, max_bubbles, soft_total = _char_budgets()
    text = (reply or "").strip()
    if not text:
        return False
    if len(text) > soft_total:
        return True
    lines = [b.strip() for b in re.split(r"\n{1,}", text) if b.strip()]
    if len(lines) > max_bubbles:
        return True
    return any(len(b) > max_len for b in lines)


def _rewrite_if_too_long(
    reply: str,
    *,
    call,
    messages: List[Dict[str, str]],
    want_spanish: bool,
) -> str:
    """
    If the model wrote past the bubble budget, rewrite shorter — do NOT
    ship a reply that split_into_messages would mutilate with mid-word cuts.
    """
    if not _reply_needs_shorten(reply):
        return reply
    max_len, max_bubbles, soft_total = _char_budgets()
    instr = (
        f"REWRITE SHORTER — same meaning, same dirty/sweet tone, same price if any. "
        f"Max {max_bubbles} short bubbles (newline between). Each bubble under "
        f"{max_len} characters. Whole reply under ~{soft_total} characters. "
        f"Finish every sentence — never trail off mid-thought."
        if not want_spanish
        else (
            f"REESCRIBE MÁS CORTO — mismo significado, mismo tono guarro/dulce, "
            f"mismo precio si hay. Máx {max_bubbles} burbujas cortas (salto de línea). "
            f"Cada burbuja bajo {max_len} caracteres. Todo el reply bajo ~{soft_total} "
            f"caracteres. Termina cada frase — nunca cortes a mitad."
        )
    )
    try:
        shorter = call(
            messages
            + [
                {"role": "assistant", "content": reply},
                {"role": "user", "content": instr},
            ]
        )
    except Exception as exc:
        print(f"   ⚠️ length-rewrite failed: {exc}")
        return reply
    if (shorter or "").strip() and len(shorter.strip()) < len(reply.strip()):
        print(
            f"   ✂️ length-rewrite {len(reply)}→{len(shorter.strip())}c "
            f"(budget ~{soft_total})"
        )
        return shorter.strip()
    return reply


def split_into_messages(
    reply: str,
    *,
    max_len: Optional[int] = None,
    max_bubbles: Optional[int] = None,
    vary: bool = True,  # kept for backward compatibility
) -> List[str]:
    """
    Turn one AI reply into several short Fanvue bubbles.

    Newlines become bubbles. Overlong blocks split on sentence boundaries.
    Never mid-sentence truncate with "…" — drop overflow bubbles instead.
    Slight overshoot (~15%) allowed so a finished thought stays intact.
    """
    if max_len is None:
        max_len = int(getattr(config, "BUBBLE_MAX_CHARS", 200) or 200)
    max_len = max(80, int(max_len))
    # Prefer complete sentences over ugly chops
    soft_len = int(max_len * 1.15)

    reply = (reply or "").strip()
    if not reply:
        return []

    def _soft_slice(text: str) -> List[str]:
        """Split long text on punctuation/spaces; keep pieces readable (no …)."""
        out: List[str] = []
        while len(text) > soft_len:
            window = text[:soft_len]
            cut = -1
            for sep in (". ", "! ", "? ", "… ", "; ", ", ", " "):
                cut = window.rfind(sep)
                if cut >= max_len // 3:
                    cut = cut + len(sep) - 1 if sep != " " else cut
                    break
            if cut < max_len // 3:
                # Last resort: space near limit — still no ellipsis mutilation
                cut = text.rfind(" ", 0, max_len)
                if cut < max_len // 3:
                    # Keep whole remaining as one bubble (better than "foo…")
                    out.append(text.strip())
                    return out
            out.append(text[:cut].strip())
            text = text[cut:].strip()
        if text:
            out.append(text)
        return out

    raw_parts: List[str] = []
    for block in re.split(r"\n{1,}", reply):
        block = block.strip()
        if block:
            raw_parts.append(block)

    parts: List[str] = []
    for block in raw_parts:
        if len(block) <= soft_len:
            parts.append(block)
            continue
        sentences = re.split(r"(?<=[.!?…])\s+", block)
        buf = ""
        for s in sentences:
            s = s.strip()
            if not s:
                continue
            if buf and len(buf) + 1 + len(s) > soft_len:
                parts.extend(_soft_slice(buf) if len(buf) > soft_len else [buf])
                buf = s
            else:
                buf = f"{buf} {s}".strip()
        if buf:
            parts.extend(_soft_slice(buf) if len(buf) > soft_len else [buf])

    if not parts:
        parts = _soft_slice(reply)

    default_cap = int(getattr(config, "MAX_BUBBLES", 3) or 3)
    hard_cap = max(1, max_bubbles if max_bubbles is not None else default_cap)
    if len(parts) > hard_cap:
        # Keep first N complete bubbles; drop the rest (no glue + "…" chop)
        parts = parts[:hard_cap]

    return parts
