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
    vault_catalog,
)
from core.intent_router import RouteResult, decision_for_pack, route as route_intent
from core.turn_policy import TurnDecision, author_note_for, decide_turn
from core.system_prompt import EMMA_SYSTEM_PROMPT  # legacy fat prompt (non-lean only)

_CLIENT: Optional[OpenAI] = None

# Legacy constant (tests / old callers). Live path uses author_note_for(mode).
AUTHOR_NOTE = (
    "[Stay in character as Emma. Reply in 1-3 short lines, like real texting. "
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
        if not text and (msg.get("hasMedia") or msg.get("mediaUuids")):
            mtype = (msg.get("mediaType") or "").lower()
            priced = bool(msg.get("pricing"))
            if role == "user":
                text = "[fan sent a video]" if "video" in mtype else "[fan sent a photo]"
            elif priced:
                unlocked = bool(msg.get("purchasedAt"))
                price = None
                usd = (msg.get("pricing") or {}).get("USD") or {}
                if usd.get("price") is not None:
                    try:
                        price = float(usd["price"]) / 100.0
                    except (TypeError, ValueError):
                        price = None
                price_bit = f" ${price:.0f}" if price is not None else ""
                if unlocked:
                    text = f"[you locked a paid photo{price_bit} — HE UNLOCKED IT]"
                else:
                    text = f"[you locked a paid photo{price_bit} — still locked / unpaid]"
            else:
                text = "[you sent a FREE photo — unlocked gift]"
        if not text:
            continue
        if turns and turns[-1]["role"] == role:
            turns[-1]["content"] = turns[-1]["content"] + "\n" + text
        else:
            turns.append({"role": role, "content": text})
    return turns


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

    # Ensure the last turn is the current fan message exactly once
    turns = list(history_turns)
    if not (
        turns
        and turns[-1]["role"] == "user"
        and turns[-1]["content"].strip() == fan_message.strip()
    ):
        turns.append({"role": "user", "content": fan_message})

    lean = bool(getattr(config, "LEAN_CREATIVE", True))

    # --- PHASE ANALYST: read full chat + client card BEFORE creative ---
    card_block = ""
    if fan_uuid:
        card_block = fan_memory.render_block(fan_uuid) or ""
    hard_pack = None
    if route_result and route_result.facts.hard_pack:
        hard_pack = route_result.facts.hard_pack
    analysis = None
    force_tech = None
    try:
        analysis = phase_analyst.analyze(
            fan_message=fan_message,
            history_turns=turns,
            card_text=card_block,
            hard_pack=hard_pack,
            code_pack=pack_id,
        )
    except Exception as e:
        print(f"   phase-analyst error: {type(e).__name__}: {e}")

    if analysis:
        print(
            f"   analyst: phase={analysis.phase} pack={analysis.pack_id} "
            f"name={analysis.name_to_use or '-'} "
            f"likes={','.join(analysis.likes[:3]) or '-'}"
        )
        # Soft packs: analyst can refine phase from full conversation
        if not hard_pack and analysis.pack_id and analysis.pack_id != pack_id:
            pack_id = analysis.pack_id
            if route_result is not None:
                decision = decision_for_pack(
                    pack_id,
                    route_result.facts,
                    mem,
                    f"analyst:{analysis.phase}",
                )
            print(f"   pack←analyst: {pack_id}")
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

    # MANIPULATION ENGINE first (loudest), then situation pack
    facts_line = ""
    msgs_n = int(mem.get("messages") or 0)
    objection_step = int(mem.get("price_objection_step") or 0)
    manip_banner = manipulation.render_banner(
        pack_id,
        fan_uuid=fan_uuid or "",
        msgs=msgs_n,
        reject_count=objection_step,
        force_name=force_tech,
    )
    tech = manipulation.pick_technique(
        pack_id,
        fan_uuid=fan_uuid or "",
        msgs=msgs_n,
        reject_count=objection_step,
        force_name=force_tech,
    )
    tech_name = tech[0] if tech else ""
    if manip_banner:
        turn_blocks.append(manip_banner)
        print(f"   manip: {tech_name} (pack={pack_id})")

    if route_result is not None:
        facts_line = route_result.facts.facts_line()
    turn_blocks.append(packs.render(pack_id, facts_line=facts_line))

    if offer or (decision and decision.allow_price):
        turn_blocks.append(vault_catalog.catalog_summary_block())

    if ppv_status:
        turn_blocks.append(_ppv_truth_block(ppv_status))

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
    # LOCK STATUS already covers unpaid vs none via _ppv_truth_block(ppv_status).
    # If gate says unpaid but status missing, hard fallback:
    if (
        delivery_truth
        and delivery_truth.get("ppv_unpaid")
        and not ppv_status
    ):
        turn_blocks.append(
            "LOCK STATUS: UNPAID timed lock is waiting. Persist on THAT unlock. "
            "Do NOT stack another. Do NOT invent older gifts."
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

    if offer:
        turn_blocks.append(vault_catalog.offer_prompt_block(offer))
    else:
        turn_blocks.append(
            "No photo attached this turn. Flirt only. "
            "Never claim you sent/locked a photo. Never invent media titles in brackets."
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
        messages, sizes = prompt_layers.build_system_layers(
            card_block=card_block,
            language_block=language.language_system_block(want_spanish),
            time_block=persona_time.time_system_block(),
            name_block=name_note,
            turn_blocks=turn_blocks,
        )
        print(
            f"   prompt: CORE={sizes['core']} CARD={sizes['card']} "
            f"TURN={sizes['turn']} total_sys={sizes['system_total']} pack={pack_id}"
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
    if lean:
        lang = "Spanish only." if want_spanish else "English only."
        note = (
            f"[Emma texting. {lang} Pack={pack_id}. "
            f"1–3 short lines. Pet name or none — almost never his real name.]"
        )
        if tech_name:
            note += manipulation.author_nudge(pack_id, tech_name)
    else:
        note = author_note_for(decision, want_spanish=want_spanish, lean=lean)
        if tech_name:
            note += manipulation.author_nudge(pack_id, tech_name)
    if offer:
        is_free = float(offer.get("price") or 0) <= 0 or int(offer.get("level") or 0) == 0
        if is_free:
            note += " FREE photo attached — one short flirty line."
        else:
            note += (
                f" PAID lock ${offer.get('price'):.0f} attaches WITH your first bubble. "
                "Do NOT ask if he wants it. Do NOT offer free/gratis. Do NOT claim older gifts. "
                "Tease once then lock."
            )
    note = prompt_layers.clip_author(note)

    turns_out = [dict(t) for t in turns]
    for i in range(len(turns_out) - 1, -1, -1):
        if turns_out[i]["role"] == "user":
            turns_out[i]["content"] = f"{turns_out[i]['content']}\n\n{note}"
            break
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

    # If Spanglish / wrong language slipped through → one forced rewrite
    if language.is_mixed_or_wrong(reply, want_spanish=want_spanish):
        fix_msgs = messages + [
            {"role": "assistant", "content": reply},
            {
                "role": "user",
                "content": language.rewrite_instruction(want_spanish),
            },
        ]
        reply = _call(fix_msgs)
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

    if fan_uuid:
        fan_memory.set_last_mode(fan_uuid, decision.mode, fan_handle=fan_handle)
        if re.search(
            r"\b(too expensive|caro|expensive|can'?t|no money|later|nah|pass)\b",
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

    return reply, decision


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
    Default max_uses=0 — stop 'Ay Ruben' every bubble.
    """
    name = _usable_fan_name(name, confirmed=name_confirmed)
    if not name:
        return (
            "ADDRESSING: pet name or none. HARD BAN: never invent a first name.",
            0,
        )
    recent_emma = [
        t.get("content") or ""
        for t in turns[-10:]
        if t.get("role") == "assistant"
    ]
    used_count = sum(1 for c in recent_emma if name.lower() in (c or "").lower())
    # Used in any of last 3 Emma turns → zero this turn
    if used_count >= 1 or any(name.lower() in (c or "").lower() for c in recent_emma[-3:]):
        return (
            f"NAME BAN THIS TURN: Do NOT write \"{name}\" or \"Ay {name}\" at all. "
            f"Pet name (bebe/cielo/guapo) or no address. Name spam kills the vibe.",
            0,
        )
    # Rare allowance — still prefer none
    return (
        f"ADDRESSING: Prefer pet name or none. You may say \"{name}\" at most ONCE "
        f"only if it is a rare apology/greeting beat — never \"Ay {name}\" as a stamp.",
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
        # Light strip of trailing emoji stamp only when it looks spammy (keep most)
        if _TRAILING_EMOJI.search(s) and random.random() < 0.25:
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


def split_into_messages(
    reply: str,
    *,
    max_len: int = 600,
    max_bubbles: Optional[int] = None,
    vary: bool = True,  # kept for backward compatibility; no longer forces sizes
) -> List[str]:
    """
    Split a reply into chat bubbles following the MODEL's own structure.

    No min/max character shaping: each newline the model wrote becomes a
    bubble. Only two safety nets remain:
    - a block longer than `max_len` chars (a real wall of text) is split
      on sentence boundaries
    - at most `max_bubbles` bubbles (default 3) so she never spams
    """
    reply = (reply or "").strip()
    if not reply:
        return []

    raw_parts: List[str] = []
    for block in re.split(r"\n{1,}", reply):
        block = block.strip()
        if block:
            raw_parts.append(block)

    parts: List[str] = []
    for block in raw_parts:
        if len(block) <= max_len:
            parts.append(block)
            continue
        sentences = re.split(r"(?<=[.!?…])\s+", block)
        buf = ""
        for s in sentences:
            s = s.strip()
            if not s:
                continue
            if buf and len(buf) + 1 + len(s) > max_len:
                parts.append(buf)
                buf = s
            else:
                buf = f"{buf} {s}".strip()
        if buf:
            parts.append(buf)

    if not parts:
        parts = [reply]

    hard_cap = max(1, max_bubbles if max_bubbles is not None else 3)
    if len(parts) > hard_cap:
        # keep the model's first bubbles intact, fold the overflow into the last
        head = parts[: hard_cap - 1]
        tail = " ".join(parts[hard_cap - 1 :]).strip()
        parts = head + [tail]

    return parts
