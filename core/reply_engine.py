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


def fanvue_messages_to_turns(
    messages: List[dict],
    fan_uuid: str,
    creator_uuid: str,
    *,
    max_messages: int = 14,
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
) -> Tuple[str, TurnDecision]:
    """
    Prompt + memory + lorebook + catalog offer + mode-aware author's note.

    Returns (raw_reply, decision). If `offer` is set, Emma must tease that photo only.
    `fan_vision` = Grok description of a photo the fan just sent.
    """
    history_turns = history_turns or []
    mem = fan_memory.get(fan_uuid) if fan_uuid else {}
    if decision is None:
        decision = decide_turn(mem, fan_message)

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
                    "No locked photo is being sent this turn. Flirt only. "
                    "FORBIDDEN: claiming you sent/left/locked a photo, "
                    "'check your inbox/DMs', 'revisa tu bandeja', "
                    "'ya lo dejé', 'recarga el chat', or inventing a technical glitch. "
                    "If he asks where the photo is, tease that you will lock one when he's ready — "
                    "do not pretend it already arrived."
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

    note = author_note_for(decision, want_spanish=want_spanish)
    if offer:
        note += (
            f" You are locking ONE real photo now ({offer.get('label')}, "
            f"${offer.get('price'):.0f}). Tease it — do not say it was already sent."
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
            "Do not invent a first name."
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
            f"(babe/baby/handsome/love/trouble) or no address at all."
        )
    return (
        f"NAME BUDGET: His name is {name}. Prefer a pet name or none this turn. "
        f"You may say \"{name}\" at most once, and only if it feels natural "
        f"(greeting / apology / big moment) — not every message."
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


def _sanitize_reply(
    text: str,
    *,
    want_spanish: bool = False,
    fan_name: str = "",
) -> str:
    """Strip banned pet names + thin name spam + trailing emoji stamps."""
    if not text:
        return text
    cleaned = _BANNED_ALWAYS.sub("", text)
    if not want_spanish:
        cleaned = _BANNED_SPANISH_IN_ENGLISH.sub("", cleaned)
    cleaned = _FAKE_SENT.sub("", cleaned)
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
        # Often strip trailing emoji stamp; sometimes keep one vibe
        if _TRAILING_EMOJI.search(s) and random.random() < 0.6:
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


_FAKE_SENT = re.compile(
    r"(?i)(?:"
    r"\b(?:check your (?:dms|inbox|messages)|go check your (?:dms|inbox)|"
    r"i (?:just )?sent|i left (?:it|this) in your inbox|"
    r"already (?:in|sent to) your inbox|tap (?:what|the) (?:i )?(?:left|sent))\b[^.!?\n]*[.!?]?"
    r"|"
    r"(?:revisa(?:lo)?(?:\s+tu)?\s*(?:bandeja|inbox|chat|dms)?|"
    r"tu bandeja(?:\s+te)?(?:\s+est[aá])?(?:\s+esperando)?|"
    r"ya lo dej[eé]|te (?:estoy )?dejando(?:\s+algo)?|"
    r"lo (?:acabo de |he )?bloque[eé]|recarga(?:\s+tu)?\s*(?:bandeja|chat|app)|"
    r"la foto se bloque[oó]|est[aá] en tu (?:bandeja|inbox))\b[^.!?\n]*[.!?]?"
    r")"
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
