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
from core.system_prompt import EMMA_SYSTEM_PROMPT
from core import fan_memory, language, lessons, lorebook, persona_time, vault_catalog
from core.turn_policy import TurnDecision, author_note_for, decide_turn

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
                text = "[you locked a paid photo]"
            else:
                text = "[you sent media]"
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
) -> Tuple[str, TurnDecision]:
    """
    Prompt + memory + lorebook + catalog offer + mode-aware author's note.

    Returns (raw_reply, decision). If `offer` is set, Emma must tease that photo only.
    `fan_vision` = Grok description of a photo the fan just sent.
    `delivery_truth` = Fanvue API checks (e.g. free_in_chat True/False).
    """
    history_turns = history_turns or []
    mem = fan_memory.get(fan_uuid) if fan_uuid else {}
    if decision is None:
        decision = decide_turn(mem, fan_message, delivery_truth=delivery_truth)

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

    messages: List[Dict[str, str]] = [
        {"role": "system", "content": EMMA_SYSTEM_PROMPT},
        {"role": "system", "content": language.language_system_block(want_spanish)},
        {"role": "system", "content": persona_time.time_system_block()},
    ]

    if fan_uuid:
        mem_block = fan_memory.render_block(fan_uuid)
        if mem_block:
            messages.append({"role": "system", "content": mem_block})

    # Learned lessons (global approved + this fan's)
    lessons_block = lessons.render_block(fan_uuid)
    if lessons_block:
        messages.append({"role": "system", "content": lessons_block})

    # Always remind what we actually own (stops inventing videos)
    messages.append({"role": "system", "content": vault_catalog.catalog_summary_block()})

    # Verified truth about the LAST locked PPV (API-checked this turn)
    if ppv_status:
        messages.append({"role": "system", "content": _ppv_truth_block(ppv_status)})

    # Fanvue API: is the free photo actually in this chat?
    if delivery_truth and delivery_truth.get("free_in_chat") is True:
        messages.append(
            {
                "role": "system",
                "content": (
                    "DELIVERY TRUTH (Fanvue API): Your FREE tease photo IS already in THIS chat. "
                    "Tell him to scroll up / look again. Do NOT send another free. "
                    "Do NOT invent a glitch or say it never left. Be playful but honest."
                ),
            }
        )
    elif delivery_truth and delivery_truth.get("free_in_chat") is False:
        messages.append(
            {
                "role": "system",
                "content": (
                    "DELIVERY TRUTH (Fanvue API): The free photo is NOT in chat history right now. "
                    "If the system attaches a new L0 this turn, gift it. "
                    "If nothing is attached, apologize briefly without inventing tech excuses."
                ),
            }
        )

    # Grok Vision: what HE just sent (or fall back to last remembered photo)
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

        messages.append({"role": "system", "content": vision_system_block(vision_desc)})

    if offer:
        messages.append({"role": "system", "content": vault_catalog.offer_prompt_block(offer)})
    else:
        messages.append(
            {
                "role": "system",
                "content": (
                    "No photo is being sent this turn. Flirt only. "
                    "FORBIDDEN: claiming you sent/left/locked a photo, "
                    "'check your inbox/DMs', 'revisa tu bandeja', "
                    "'ya lo dejé', 'recarga el chat', or inventing a technical glitch. "
                    "FORBIDDEN: writing bracket stage directions like "
                    "'[You can send him the free tease…]' or '[Transmite Mira Mis Piernas…]' — "
                    "that does NOT send anything. "
                    "If he asks where a free photo is, apologize briefly and tease — "
                    "do not pretend it already arrived and do not invent media titles."
                ),
            }
        )

    recent_text = " ".join(
        t["content"] for t in turns[-4:] if t["role"] == "user"
    )
    lore_block = lorebook.render_block(recent_text)
    if lore_block:
        messages.append({"role": "system", "content": lore_block})

    name_note = _name_budget_note(mem.get("name") or "", turns)
    if name_note:
        messages.append({"role": "system", "content": name_note})

    messages.append(
        {
            "role": "system",
            "content": (
                "GROUNDING: Recent chat history + CLIENT CARD are the ONLY sources of truth "
                "about him. Do not invent quotes, gifts, jobs, plans, names, divorces, hobbies, "
                "or details missing from both. If unclear, ask a short question — never assume."
            ),
        }
    )

    note = author_note_for(decision, want_spanish=want_spanish)
    if offer:
        is_free = float(offer.get("price") or 0) <= 0 or int(offer.get("level") or 0) == 0
        if is_free:
            note += (
                f" You are GIFTING one FREE soft tease photo now (internal vibe: {offer.get('label')}). "
                "Write ONE short flirty line only — NEVER paste a photo caption or describe the shot "
                "in detail. Do NOT write '[envió una foto]' or 'te envío una foto gratis'. "
                "The system attaches the real image after your text."
            )
        else:
            note += (
                f" You are locking ONE real photo now (internal vibe: {offer.get('label')}, "
                f"${offer.get('price'):.0f}). Short tease only — no caption dump. "
                "Do not say it was already sent."
            )
    turns_out = [dict(t) for t in turns]
    for i in range(len(turns_out) - 1, -1, -1):
        if turns_out[i]["role"] == "user":
            turns_out[i]["content"] = f"{turns_out[i]['content']}\n\n{note}"
            break
    messages.extend(turns_out)

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
            fan_name=(mem.get("name") or ""),
            media_attached=bool(offer),
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
    """Fact block so Emma never believes fake 'I paid it' claims."""
    label = status.get("label") or "your locked photo"
    price = status.get("price")
    ago = status.get("ago") or "recently"
    price_txt = f" (${price:.0f})" if isinstance(price, (int, float)) else ""
    if status.get("purchased"):
        return (
            "PPV TRUTH — VERIFIED VIA FANVUE API THIS TURN:\n"
            f"- The locked photo you sent {ago} — \"{label}\"{price_txt} — HE **DID** PURCHASE IT.\n"
            "- He really saw it. Thank him warmly, make him feel special about it.\n"
            "- Do not ask him to unlock it again."
        )
    return (
        "PPV TRUTH — VERIFIED VIA FANVUE API THIS TURN:\n"
        f"- The locked photo you sent {ago} — \"{label}\"{price_txt} — HE HAS **NOT** PURCHASED IT.\n"
        "- If he claims he paid it, saw it, or loved it: that is FALSE. He is bluffing.\n"
        "- Call it out playfully and confidently (\"nice try baby... I can see you never unlocked it\"),\n"
        "  turn it into a tease to actually unlock it. Never play along with the lie.\n"
        "- Never describe the photo's content as if he had seen it.\n"
        "- This applies ONLY to that exact photo — do not bring up older content."
    )


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


def _name_budget_note(name: str, turns: List[Dict[str, str]]) -> str:
    """Tell the model whether his real name is allowed this turn."""
    name = (name or "").strip()
    if len(name) < 2:
        return (
            "ADDRESSING: use a light pet name (babe/baby/handsome/trouble) or none. "
            "HARD BAN: do NOT invent a first name (no Carlos, Jamie, Alex, etc.). "
            "If you don't know his name from CLIENT CARD, ask once or use a pet name."
        )
    recent_emma = [
        t.get("content") or ""
        for t in turns[-8:]
        if t.get("role") == "assistant"
    ]
    used_recently = any(name.lower() in (c or "").lower() for c in recent_emma[-2:])
    if used_recently:
        return (
            f"NAME BUDGET: You already used \"{name}\" in a recent reply. "
            f"This turn do NOT say his name. Use a light pet name "
            f"(babe/baby/handsome/love/trouble) or no address at all. "
            f"Never swap in a different first name."
        )
    return (
        f"NAME BUDGET: His name is {name} (confirmed). Prefer a pet name or none this turn. "
        f"You may say \"{name}\" at most once, and only if it feels natural "
        f"(greeting / apology / big moment) — not every message. "
        f"Never call him any other first name."
    )


def _thin_name_in_reply(text: str, name: str) -> str:
    """Keep at most one use of his real name across the whole reply."""
    name = (name or "").strip()
    if len(name) < 2 or not text:
        return text
    pattern = re.compile(rf"\b{re.escape(name)}\b", re.IGNORECASE)
    seen = False

    def _repl(m: re.Match) -> str:
        nonlocal seen
        if seen:
            return ""
        seen = True
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
    media_attached: bool = False,
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
    cleaned = _strip_photo_script_dump(cleaned)
    cleaned = _thin_name_in_reply(cleaned, fan_name)
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
