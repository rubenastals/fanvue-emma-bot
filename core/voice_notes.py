"""
Voice notes ? ElevenLabs TTS -> Fanvue vault audio -> free chat bubble.

Sent naturally at key heating moments, not promoted or packaged.
Dirty, spontaneous, real ? like a girl grabbing her phone because she had to say something.
"""
from __future__ import annotations

import os
import random
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from config import config
from core import fan_memory, language
from utils.elevenlabs_client import (
    is_configured,
    scrub_tts_stage_directions,
    synthesize_to_file,
)

_HORNY = re.compile(
    r"(?i)\b("
    r"hard|horny|wet|cock|dick|pussy|fuck|cum|stroke|jerk|"
    r"duro|caliente|mojada|polla|follar|correr|"
    r"tetas?|culo|ass|mojad|empapad|"
    r"te quiero|te deseo|thinking about you|pienso en ti"
    r")\b"
)
_EMOTIONAL = re.compile(
    r"(?i)\b("
    r"te quiero|te extra[n\u00f1]o|miss you|thinking about you|"
    r"me encantas|you turn me on|me pones|need you|"
    r"pienso en ti|solo t[u\u00fa]|only you"
    r")\b"
)

_HEAT_PACKS = frozenset(
    {
        "phase_spiral",
        "rapport",
        "reward_purchase",
        "phase_close",
    }
)
_BLOCK_PACKS = frozenset(
    {
        "ppv_unpaid",
        "price_objection",
        "delivery_missing",
        "phase_reengage",
        "ask_free_first",
    }
)

_ASK_VOICE = re.compile(
    r"(?i)("
    r"\b("
    r"audio|audios|voice\s*notes?|voice\s*memo|voz|nota\s+de\s+voz|"
    r"gr[aá]bame|m[aá]ndame\s+audio|mandame\s+audio|"
    r"env[ií]ame\s+audio|enviame\s+audio|escucharte|"
    r"whisper|susurra|al\s+o[ií]do|"
    r"el\s+audio|la\s+nota|lo\s+del\s+audio|ese\s+audio|"
    r"me\s+lo\s+mandas|me\s+lo\s+grabas|cuando\s+el\s+audio|"
    r"still\s+waiting|waiting\s+for\s+(the\s+)?(audio|voice)|"
    r"y\s+el\s+audio|and\s+the\s+audio"
    r")\b|"
    r"gr[aá]ba\s*melo|mandamelo|m[aá]ndamelo"
    r")"
)

# She already stalled with "ask me for it" / promised a voice note.
# Also catch standalone pídemelo / quieres audio (the 20-msg beg loop).
_EMMA_OWED_VOICE = re.compile(
    r"(?i)("
    r"p[ií]demel[oa]\b|"
    r"ask\s+me\s+nicely|"
    r"ask\s+me\s+(?:for\s+it|to\s+ask)|"
    r"quieres\s+(?:un\s+)?(?:audio|voice)|"
    r"want\s+(?:a\s+)?(?:voice\s*note|audio)\??|"
    r"(?:p[ií]demel[oa]|ask\s+me\s+nicely).{0,120}"
    r"(?:audio|voz|voice|grab|whisper|susurr)|"
    r"(?:audio|voz|voice|grab|whisper|susurr).{0,120}"
    r"(?:p[ií]demel[oa]|ask\s+me\s+nicely)|"
    r"d[eé]jame\s+grabarte|"
    r"give\s+me\s+a\s+sec.{0,40}(?:voice|audio|whisper)|"
    r"voy\s+a\s+grabar|"
    r"te\s+(?:grabo|mando|env[ií]o)\s+(?:un\s+)?(?:audio|voice)|"
    r"i(?:'?ll| will)\s+(?:send|record|drop)\s+(?:you\s+)?(?:a\s+)?(?:voice|audio)|"
    r"want\s+(?:me\s+to\s+)?(?:record|send)\s+(?:you\s+)?(?:a\s+)?(?:voice|audio)|"
    r"quieres\s+(?:que\s+)?(?:te\s+)?(?:grabe|mande\s+(?:un\s+)?audio)"
    r")"
)

# Emma asking AGAIN for him to beg / offer audio (ban when debt is open)
_EMMA_VOICE_BEG = re.compile(
    r"(?i)("
    r"p[ií]demel[oa]\b|"
    r"ask\s+me\s+nicely|"
    r"quieres\s+(?:un\s+)?(?:audio|voice)|"
    r"want\s+(?:a\s+)?(?:voice\s*note|audio)\??|"
    r"si\s+me\s+lo\s+pides|"
    r"if\s+you\s+ask\s+(?:me\s+)?nicely|"
    r"d[eé]jame\s+grabarte\??|"
    r"te\s+grabo\s+(?:algo|un\s+audio)\s*\?"
    r")"
)

_COMPLY_AFTER_VOICE_STALL = re.compile(
    r"(?i)\b("
    r"por\s*favor|please|vale|ok|okay|dale|venga|"
    r"s[ií]+|manda|env[ií]|pasa|quiero|hazlo|vamos|"
    r"audio|voz|voice|gr[aá]ba|"
    r"ganas|gatas|ya|now|esperando|waiting"
    r")\b"
)

_VOICE_DELIVERED = re.compile(
    r"(?i)(\[you sent a VOICE NOTE|voice note attached|/audio\]|🎙)"
)

_FAN_REJECT_VOICE = re.compile(
    r"(?i)\b("
    r"no\s+quiero\s+(audio|voz|voice)|"
    r"no\s+audio|forget\s+(the\s+)?audio|"
    r"nah|pass|luego|later|otro\s+d[ií]a"
    r")\b"
)


def _enabled() -> bool:
    return bool(getattr(config, "VOICE_NOTES_ENABLED", True)) and is_configured()


def _parse_iso(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except ValueError:
        return None


def _today_key() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _voice_count_today(mem: dict) -> int:
    if mem.get("voice_notes_day") != _today_key():
        return 0
    return int(mem.get("voice_notes_today") or 0)


def _horny_score(text: str) -> int:
    if not text:
        return 0
    return len(_HORNY.findall(text))


def fan_asked_voice(fan_message: str) -> bool:
    return bool(_ASK_VOICE.search(fan_message or ""))


def _recent_assistant_text(
    history_turns: Optional[List[Dict[str, Any]]], *, n: int = 4
) -> str:
    if not history_turns:
        return ""
    chunks: List[str] = []
    seen = 0
    for turn in reversed(history_turns):
        if (turn.get("role") or "") != "assistant":
            continue
        chunks.append(str(turn.get("content") or ""))
        seen += 1
        if seen >= n:
            break
    return "\n".join(reversed(chunks))


def _recent_user_text(
    history_turns: Optional[List[Dict[str, Any]]], *, n: int = 8
) -> str:
    if not history_turns:
        return ""
    chunks: List[str] = []
    seen = 0
    for turn in reversed(history_turns):
        if (turn.get("role") or "") != "user":
            continue
        chunks.append(str(turn.get("content") or ""))
        seen += 1
        if seen >= n:
            break
    return "\n".join(reversed(chunks))


def voice_delivered_recently(
    history_turns: Optional[List[Dict[str, Any]]] = None,
    *,
    n: int = 24,
    mem: Optional[dict] = None,
) -> bool:
    """True if a voice note was already delivered (history marker or mem clock)."""
    if _mem_voice_fresh(mem):
        return True
    if not history_turns:
        return False
    for turn in history_turns[-n:]:
        if _VOICE_DELIVERED.search(str(turn.get("content") or "")):
            return True
    return False


def _mem_voice_fresh(mem: Optional[dict]) -> bool:
    """True if we successfully sent audio within VOICE_NOTES_COOLDOWN_HOURS."""
    if not mem:
        return False
    ts = _parse_iso(mem.get("last_voice_at"))
    if not ts:
        return False
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    hours = float(getattr(config, "VOICE_NOTES_COOLDOWN_HOURS", 6) or 6)
    return datetime.now(timezone.utc) - ts < timedelta(hours=hours)


def _normalize_spoken(text: str) -> str:
    t = (text or "").lower()
    t = re.sub(r"[\U0001F300-\U0001FAFF]+", " ", t)
    t = re.sub(r"[^\w\s]", " ", t, flags=re.UNICODE)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def script_echoes_reply(script: str, reply: str) -> bool:
    """True if the voice script is basically reading the text bubble aloud."""
    a = _normalize_spoken(script)
    b = _normalize_spoken(reply)
    if not a or not b:
        return False
    # Shared long prefix / containment (the live bug: verbatim replay)
    prefix = min(48, len(a), len(b))
    if prefix >= 24 and (a[:prefix] in b or b[:prefix] in a):
        return True
    if len(a) >= 20 and (a in b or b in a):
        return True
    ta, tb = set(a.split()), set(b.split())
    if len(ta) < 4 or len(tb) < 4:
        return False
    overlap = len(ta & tb) / len(ta | tb)
    return overlap >= 0.55


def thread_voice_debt(
    history_turns: Optional[List[Dict[str, Any]]] = None,
    *,
    lookback: int = 20,
) -> tuple[bool, str]:
    """
    Open voice debt across the recent thread (not just last message).

    True when fan asked / Emma promised-or-begged for audio multiple times
    and no voice note was delivered yet — the 20-msg pídemelo loop.
    """
    if not history_turns:
        return False, ""
    window = history_turns[-lookback:]
    if voice_delivered_recently(window, n=lookback):
        return False, "already delivered"

    fan_hits = 0
    emma_hits = 0
    for turn in window:
        body = str(turn.get("content") or "")
        role = turn.get("role") or ""
        if role == "user" and _ASK_VOICE.search(body):
            fan_hits += 1
        if role == "assistant" and (
            _EMMA_OWED_VOICE.search(body) or _EMMA_VOICE_BEG.search(body)
        ):
            emma_hits += 1

    # Also count fan asks in current-looking short complies if Emma already begged
    if emma_hits >= 2 or (emma_hits >= 1 and fan_hits >= 1) or fan_hits >= 2:
        return True, f"thread debt fan={fan_hits} emma={emma_hits}"
    if emma_hits >= 1:
        # Single pídemelo / audio tease still counts as owed
        return True, f"emma voice stall x{emma_hits}"
    return False, ""


def emma_owed_voice(
    history_turns: Optional[List[Dict[str, Any]]] = None,
) -> bool:
    """True if Emma promised audio / asked him to beg (wider lookback)."""
    emma = _recent_assistant_text(history_turns, n=8)
    if not emma:
        return False
    return bool(_EMMA_OWED_VOICE.search(emma) or _EMMA_VOICE_BEG.search(emma))


def fan_complied_for_voice(fan_message: str) -> bool:
    return bool(_COMPLY_AFTER_VOICE_STALL.search(fan_message or ""))


def fan_asked_voice_in_thread(
    history_turns: Optional[List[Dict[str, Any]]] = None,
    *,
    n: int = 12,
) -> bool:
    return bool(_ASK_VOICE.search(_recent_user_text(history_turns, n=n)))


def reply_is_voice_beg(reply: str) -> bool:
    """True if this draft asks him again to beg for / want audio."""
    return bool(_EMMA_VOICE_BEG.search(reply or ""))


def forced_voice_close_line(*, want_spanish: bool = False) -> str:
    """Short text when audio attaches — never another pídemelo."""
    if getattr(config, "ENGLISH_ONLY", True):
        want_spanish = False
    if want_spanish:
        return "Ven aquí un segundo… esto es solo para ti"
    return "Come here a sec… this one's just for you"


def _open_voice_state(
    mem: dict,
    history_turns: Optional[List[Dict[str, Any]]],
    fan_message: str,
) -> tuple[bool, str]:
    """
    Dumb FSM input: is a voice note owed right now?

    True if DB commitment, thread debt, Emma stall, or fan asked (now/recent).
    No rolls, packs, or horny scores — those only apply to opportunistic sends.

    After a successful send (mem last_voice_at fresh), stale thread asks do NOT
    reopen debt — only a new ask this turn does. Fanvue history rarely has our
    local VOICE NOTE markers, so mem clock is the real delivery signal.
    """
    db_voice = isinstance(mem.get("open_commitment"), dict) and (
        (mem.get("open_commitment") or {}).get("type") == "voice"
    )
    if db_voice:
        hits = int((mem.get("open_commitment") or {}).get("hits") or 0)
        return True, f"DB commitment=voice hits={hits}"

    # Delivery already happened → ignore stale "asked in thread" / old stalls
    if _mem_voice_fresh(mem) or voice_delivered_recently(history_turns, n=24):
        if fan_asked_voice(fan_message):
            return True, "fan asked voice this turn (post-delivery)"
        return False, ""

    debt, debt_why = thread_voice_debt(history_turns, lookback=20)
    if debt:
        return True, f"thread debt ({debt_why})"
    if fan_asked_voice(fan_message):
        return True, "fan asked voice this turn"
    if fan_asked_voice_in_thread(history_turns, n=16):
        return True, "fan asked voice in recent thread"
    if emma_owed_voice(history_turns):
        return True, "emma voice stall"
    return False, ""


def should_send(
    *,
    fan_message: str,
    mem: dict,
    decision: Any,
    pack_id: str,
    unpaid: bool,
    media_sent_this_turn: bool,
    barged: bool,
    apply_roll: bool = True,
    history_turns: Optional[List[Dict[str, Any]]] = None,
) -> tuple[bool, str]:
    """
    WHEN to send a voice note — FSM, not prompt intelligence.

    Committed path (open voice):
      open_voice + fan msg not reject → SEND
      Ignores unpaid / pack / mode / roll / horny.

    Opportunistic path (no debt): rare reward/heat only, still uses roll.
    """
    if not _enabled():
        return False, "disabled or no API key"
    if barged:
        return False, "barge-in"
    if media_sent_this_turn:
        return False, "photo turn"
    if _FAN_REJECT_VOICE.search(fan_message or ""):
        return False, "fan rejected audio"

    open_voice, open_why = _open_voice_state(mem, history_turns, fan_message)

    # --- COMMITTED FSM: owed → send on this fan turn ---
    if open_voice:
        # Any non-reject fan message closes the debt (por favor / dale / ok / …)
        return True, f"FSM open_voice → send ({open_why})"

    # --- Opportunistic only (no debt): keep rare; never the pídemelo path ---
    if unpaid or pack_id in _BLOCK_PACKS:
        return False, "sell/objection/reengage block"
    if int(mem.get("messages") or 0) < int(
        getattr(config, "VOICE_NOTES_MIN_MESSAGES", 8) or 8
    ):
        return False, "too early in chat"

    mode = (getattr(decision, "mode", "") or "").lower()
    if mode in ("hard_sell", "chill"):
        return False, f"mode={mode}"

    horny = _horny_score(fan_message)
    emotional = bool(_EMOTIONAL.search(fan_message or ""))
    heat_pack = pack_id in _HEAT_PACKS
    reward = pack_id == "reward_purchase"

    trigger = False
    reason = ""
    if reward:
        trigger, reason = True, "post-purchase reward"
    elif horny >= 2:
        trigger, reason = True, f"very horny fan ({horny} hits)"
    elif horny >= 1 and heat_pack and mode in ("tease", "soft_sell", "rapport"):
        trigger, reason = True, "heating spiral"
    elif emotional and heat_pack:
        trigger, reason = True, "emotional bond moment"

    if not trigger:
        return False, "no key moment"

    if apply_roll:
        chance = float(getattr(config, "VOICE_NOTES_CHANCE", 0.55) or 0.55)
        if random.random() > chance:
            return False, f"roll miss ({reason})"

    return True, reason


def plan_send(
    *,
    fan_message: str,
    mem: dict,
    decision: Any,
    pack_id: str,
    unpaid: bool,
    media_sent_this_turn: bool,
    history_turns: Optional[List[Dict[str, Any]]] = None,
) -> tuple[bool, str]:
    """Pre-reply check (includes roll) so text can react naturally before audio."""
    return should_send(
        fan_message=fan_message,
        mem=mem,
        decision=decision,
        pack_id=pack_id,
        unpaid=unpaid,
        media_sent_this_turn=media_sent_this_turn,
        barged=False,
        apply_roll=True,
        history_turns=history_turns,
    )


def sync_commitment_from_thread(
    fan_uuid: str,
    *,
    fan_handle: str,
    fan_message: str,
    history_turns: Optional[List[Dict[str, Any]]],
    mem: Optional[dict] = None,
) -> Optional[dict]:
    """
    CODE updates open_commitment from the real thread — before DeepSeek runs.

    - Fan asks for audio → set/bump voice commitment
    - Emma stalled (pídemelo / promised) → set voice commitment
    - Thread debt without delivery → set voice commitment
    - Fan rejects audio → clear
    - Voice already delivered in recent history → clear
    """
    if not fan_uuid:
        return None
    if _FAN_REJECT_VOICE.search(fan_message or ""):
        fan_memory.clear_commitment(fan_uuid, ctype="voice", fan_handle=fan_handle)
        return None
    mem = mem or fan_memory.get(fan_uuid) or {}
    # Successful send clears debt. Stale thread asks must not reopen it.
    if voice_delivered_recently(history_turns, n=24, mem=mem) and not fan_asked_voice(
        fan_message
    ):
        fan_memory.clear_commitment(fan_uuid, ctype="voice", fan_handle=fan_handle)
        return None

    open_voice, open_why = _open_voice_state(
        mem,
        history_turns,
        fan_message,
    )
    if not open_voice:
        return fan_memory.get_commitment(fan_uuid)

    return fan_memory.set_commitment(
        fan_uuid,
        ctype="voice",
        source=open_why[:80],
        fan_handle=fan_handle,
        bump=True,
    )


def voice_blocks_photo(
    mem: Optional[dict],
    history_turns: Optional[List[Dict[str, Any]]],
    fan_message: str,
) -> tuple[bool, str]:
    """
    HARD rule: open voice debt / ask → never attach PPV or free photo this turn.

    Independent of whether ElevenLabs can actually send. Selling a $40 lock
    while the thread is about audio is a protocol failure.
    """
    if _FAN_REJECT_VOICE.search(fan_message or ""):
        return False, ""
    mem = mem or {}
    c = mem.get("open_commitment")
    if isinstance(c, dict) and c.get("type") == "voice":
        return True, "DB commitment=voice"
    # Audio already landed — don't keep blocking photos on stale thread asks
    if voice_delivered_recently(history_turns, n=24, mem=mem):
        if fan_asked_voice(fan_message):
            return True, "fan asked voice this turn (post-delivery)"
        return False, ""
    debt, debt_why = thread_voice_debt(history_turns, lookback=20)
    if debt:
        return True, f"thread voice debt ({debt_why})"
    if fan_asked_voice(fan_message):
        return True, "fan asked voice this turn"
    if fan_asked_voice_in_thread(history_turns, n=12):
        return True, "fan asked voice in recent thread"
    if emma_owed_voice(history_turns):
        return True, "emma voice stall in recent thread"
    return False, ""


def resolve_voice_action(
    *,
    fan_uuid: str,
    fan_handle: str,
    fan_message: str,
    mem: dict,
    decision: Any,
    pack_id: str,
    unpaid: bool,
    history_turns: Optional[List[Dict[str, Any]]],
) -> tuple[bool, str, dict, bool]:
    """
    Action-first voice gate.

    1) Sync DB commitment from thread (code)
    2) Decide send_voice from commitment + heuristics
    3) Decide whether photo/PPV is HARD-blocked (even if send fails)

    Returns (must_send, reason, mem_after, blocks_photo)
    """
    sync_commitment_from_thread(
        fan_uuid,
        fan_handle=fan_handle,
        fan_message=fan_message,
        history_turns=history_turns,
        mem=mem,
    )
    mem2 = fan_memory.get(fan_uuid) or mem
    blocks, block_why = voice_blocks_photo(mem2, history_turns, fan_message)
    ok, why = plan_send(
        fan_message=fan_message,
        mem=mem2,
        decision=decision,
        pack_id=pack_id,
        unpaid=unpaid,
        media_sent_this_turn=False,
        history_turns=history_turns,
    )
    # If heuristics say send, ensure commitment exists for next turns if send fails
    if ok:
        c = mem2.get("open_commitment")
        if not (isinstance(c, dict) and c.get("type") == "voice"):
            fan_memory.set_commitment(
                fan_uuid,
                ctype="voice",
                source=why[:80],
                fan_handle=fan_handle,
                bump=False,
            )
            mem2 = fan_memory.get(fan_uuid) or mem2
            blocks = True
            block_why = block_why or "send_voice planned"
    # Re-check after possible commitment write
    if not blocks:
        blocks, block_why = voice_blocks_photo(mem2, history_turns, fan_message)
    if blocks and not ok:
        # Debt open but cannot send (API down, etc.) — still never sell a PPV
        why = f"{why}; photo-blocked ({block_why})"
    return ok, why, mem2, blocks


def _generate_script(
    fan_message: str,
    reply: str,
    *,
    want_spanish: bool,
    trigger_reason: str,
) -> str:
    from openai import OpenAI

    api_key = (getattr(config, "DEEPSEEK_API_KEY", "") or "").strip()
    if not api_key:
        return _fallback_script(want_spanish, reply=reply)

    lang = "Spanish" if want_spanish else "English"
    system = (
        "You write a short spoken voice-note script for Emma (dirty girlfriend). "
        "HARD BAN: do NOT read, repeat, paraphrase, or finish Emma's text bubble. "
        "He already READ that message — the audio must be a NEW whispered beat "
        "(breath, confession, dirty aside, tease) that continues the mood without "
        "recycling her typed words. "
        "If her text apologized / cooled down — soft intimate, not random porn. "
        "If filthy/horny — breathy and dirty, still NEW words. "
        "15-35 words. Natural pauses with ... Sound spontaneous. "
        "NEVER mention photos, prices, PPV, unlocking, captions, or emojis. "
        "Output ONLY words she would SAY OUT LOUD into the mic. "
        "HARD BAN stage directions / delivery labels in ANY language — never write "
        "bajito, suspiro, susurro, suave, whispers, sighs, soft, breathy, "
        "[whispers], (suspiro), *sigh*, or similar. Those get read aloud and sound fake. "
        "No brackets, parentheses stage notes, quotes, or emoji."
    )
    user = (
        f"Language: {lang}\n"
        f"Trigger: {trigger_reason}\n"
        f"He just said: {(fan_message or '')[:280]}\n"
        f"Emma ALREADY typed (do NOT say this again): {(reply or '')[:320]}\n"
        "Write a DIFFERENT voice note — same vibe, zero recycled phrasing."
    )
    client = OpenAI(
        api_key=api_key,
        base_url=getattr(config, "DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1"),
    )
    max_chars = int(getattr(config, "VOICE_NOTE_MAX_CHARS", 320) or 320)
    try:
        for attempt in range(2):
            extra = ""
            if attempt:
                extra = (
                    "\nRETRY: your last draft echoed her text. "
                    "Invent a new spoken aside. Zero shared phrases."
                )
            resp = client.chat.completions.create(
                model=getattr(config, "DEEPSEEK_FAST_MODEL", None)
                or getattr(config, "DEEPSEEK_MODEL", "deepseek-v4-pro"),
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user + extra},
                ],
                max_tokens=90,
                temperature=0.85 if attempt else 0.75,
            )
            raw = (resp.choices[0].message.content or "").strip()
            raw = raw.strip("\"'")
            raw = re.sub(r"[\U0001F300-\U0001FAFF]+", "", raw).strip()
            raw = scrub_tts_stage_directions(raw)
            if not raw or len(raw) > max_chars:
                continue
            if script_echoes_reply(raw, reply):
                print("   🎙️ script rejected: echoed text bubble")
                continue
            return raw
    except Exception:
        pass
    return scrub_tts_stage_directions(_fallback_script(want_spanish, reply=reply))


def _fallback_script(want_spanish: bool, reply: str = "") -> str:
    """Prefer echoing the text beat over a random dirty stock line."""
    soft = bool(
        re.search(
            r"(?i)\b("
            r"sorry|perdon|perd[o\u00f3]n|disculp|spam|pressure|presi[o\u00f3]n|presion|"
            r"you're right|tienes raz[o\u00f3]n|me equivoqu|my bad|okay"
            r")\b",
            reply or "",
        )
    )
    if soft:
        if want_spanish:
            return (
                "Mmm... perdona, de verdad... no queria agobiarte... "
                "solo... te tenia en la cabeza..."
            )
        return (
            "Mmm... sorry, for real... I didn't mean to push... "
            "I just... had you on my mind..."
        )
    if want_spanish:
        opts = [
            "Mmm... me tienes en la cabeza ahora mismo... no puedo soltarte...",
            "Joder... lo que me acabas de decir... me ha dejado temblando...",
            "Ah... sigue hablandome asi... me vuelve loca...",
        ]
    else:
        opts = [
            "Mmm... you got me stuck on what you just said... can't shake it...",
            "Fuck... that last message... I'm still thinking about it...",
            "Ah... keep talking to me like that... you wreck me...",
        ]
    return random.choice(opts)


def maybe_send(
    fv,
    fan_uuid: str,
    fan_handle: str,
    creator_uuid: str,
    *,
    fan_message: str,
    reply: str,
    mem: dict,
    decision: Any,
    pack_id: str,
    unpaid: bool,
    media_sent_this_turn: bool,
    barged: bool,
    pre_planned: Optional[tuple[bool, str]] = None,
    history_turns: Optional[List[Dict[str, Any]]] = None,
) -> bool:
    """
    Optionally generate + upload + send a voice note after text bubbles.
    Returns True if a voice note was delivered.
    """
    if barged or media_sent_this_turn:
        return False
    if pre_planned is not None:
        ok, why = pre_planned
    else:
        ok, why = should_send(
            fan_message=fan_message,
            mem=mem,
            decision=decision,
            pack_id=pack_id,
            unpaid=unpaid,
            media_sent_this_turn=media_sent_this_turn,
            barged=barged,
            history_turns=history_turns,
        )
    if not ok:
        return False

    # Don't drop a random filthy audio after an apology / cooling text —
    # BUT never skip when the thread already owes him a voice note.
    debt_open, _ = thread_voice_debt(history_turns, lookback=20)
    committed_now = (
        fan_asked_voice(fan_message)
        or (emma_owed_voice(history_turns) and fan_complied_for_voice(fan_message))
        or debt_open
        or (why or "").startswith("kill beg-loop")
        or "owed voice" in (why or "")
    )
    if (
        not committed_now
        and re.search(
            r"(?i)\b("
            r"sorry|perdon|perd[o\u00f3]n|disculp|spam|pressure|presi[o\u00f3]n|"
            r"you're right|tienes raz[o\u00f3]n|me equivoqu|my bad|"
            r"no (quer[i\u00ed]a|queria) |didn't mean"
            r")\b",
            reply or "",
        )
    ):
        print("   voice skipped: text is apology/cooling ? wrong beat for audio")
        return False

    want_spanish = False if getattr(config, "ENGLISH_ONLY", True) else language.fan_wants_spanish(
        fan_message, mem
    )
    print(f"   \U0001f399\ufe0f voice note trigger: {why}")

    script = _generate_script(
        fan_message,
        reply,
        want_spanish=want_spanish,
        trigger_reason=why,
    )
    print(f"   \U0001f399\ufe0f script: {script[:80]}")

    audio_path = None
    try:
        try:
            fv.send_typing_indicator(fan_uuid, True)
        except Exception:
            pass

        script = scrub_tts_stage_directions(script)
        if not script:
            script = scrub_tts_stage_directions(
                _fallback_script(want_spanish, reply=reply)
            )
        audio_path = synthesize_to_file(
            script,
            language_code="es" if want_spanish else "en",
        )
        upload = fv.upload_file_to_vault(
            str(audio_path),
            name=f"voice-{fan_handle[:20]}-{int(time.time())}",
            media_type="audio",
            strip_ai_metadata=False,
            folder_name=getattr(config, "VOICE_NOTES_VAULT_FOLDER", "voice_notes") or None,
        )
        media_uuid = upload.get("mediaUuid") or upload.get("media_uuid")
        if not media_uuid:
            raise RuntimeError(f"upload missing mediaUuid: {upload!r}")

        time.sleep(float(getattr(config, "VOICE_NOTE_SEND_DELAY_SEC", 2.5) or 2.5))
        # Fanvue rejects empty text (400 too_small). Minimal quiet caption; audio is the beat.
        fv.send_media_message(
            fan_uuid,
            media_uuids=[media_uuid],
            text="…",
        )
        time.sleep(0.8)
        verified = fv.creator_media_in_chat(
            fan_uuid,
            creator_uuid,
            media_uuid,
        )
        if not verified:
            print("   \u26a0\ufe0f voice note sent but not verified in chat")
        fan_memory.record_voice_note(fan_uuid, fan_handle=fan_handle, script=script)
        print(f"   \U0001f399\ufe0f voice note sent to @{fan_handle}")
        return True
    except Exception as e:
        print(f"   \u274c voice note failed: {type(e).__name__}: {e}")
        return False
    finally:
        try:
            fv.send_typing_indicator(fan_uuid, False)
        except Exception:
            pass
        if audio_path:
            try:
                os.unlink(audio_path)
            except OSError:
                pass
