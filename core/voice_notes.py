"""
Sensual voice notes — ElevenLabs TTS → Fanvue vault audio → free chat bubble.

DeepSeek reads the chat and decides when a voice note fits (no keyword lists).
Code only enforces hard limits: cooldown, daily cap, no photo turn, block packs.
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
from utils.elevenlabs_client import is_configured, synthesize_to_file

_BLOCK_PACKS = frozenset(
    {
        "price_objection",
        "delivery_missing",
        "ask_free_first",
    }
)


def _enabled() -> bool:
    return bool(getattr(config, "VOICE_NOTES_ENABLED", True)) and is_configured()


def _deepseek_create(client, **kwargs):
    """DeepSeek v4 returns empty content if thinking mode is left on."""
    if getattr(config, "DEEPSEEK_DISABLE_THINKING", False):
        extra = dict(kwargs.get("extra_body") or {})
        extra["thinking"] = {"type": "disabled"}
        kwargs["extra_body"] = extra
    return client.chat.completions.create(**kwargs)


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


def _history_snippet(history_turns: Optional[List], *, limit: int = 12) -> str:
    lines: List[str] = []
    for t in (history_turns or [])[-limit:]:
        role = (t.get("role") or "").lower()
        who = "Emma" if role == "assistant" else "Fan"
        content = (t.get("content") or "").replace("\n", " ")[:220]
        if content:
            lines.append(f"{who}: {content}")
    return "\n".join(lines) or "(no prior turns)"


def _voice_thread_active(
    fan_message: str, history_turns: Optional[List]
) -> tuple[bool, str]:
    """
    Fan is clearly in an audio/voice thread — send without a second AI gate.
    Reads recent chat context, not single-keyword activation.
    """
    parts: List[str] = [(fan_message or "").lower()]
    for t in (history_turns or [])[-10:]:
        parts.append((t.get("content") or "").lower())
    blob = " ".join(parts)
    waiting = any(
        p in blob
        for p in (
            "esperando", "waiting for", "prometiste", "promised",
            "no me has pasado", "no me mand", "no eres capaz",
            "where is the audio", "mandame el audio", "mándame el audio",
            "y el audio", "sigo esperando",
        )
    )
    audio_ask = any(
        p in blob
        for p in (
            "audio", "audios", "voz", "voice note", "escúchame", "escuchame",
            "susurr", "oírme", "oírte", "grábame", "grabame", "🎙",
        )
    )
    # Emma offered voice in last 2 assistant turns + fan replied
    emma_offered = False
    for t in reversed((history_turns or [])[-6:]):
        if t.get("role") == "assistant":
            c = (t.get("content") or "").lower()
            if any(
                p in c
                for p in ("escúchame", "escuchame", "susurr", "🎙", "voice note", "al oído")
            ):
                emma_offered = True
            break
    if waiting:
        return True, "fan waiting for promised audio"
    if emma_offered and (fan_message or "").strip():
        return True, "emma offered voice — fan replied"
    if audio_ask and any(
        p in (fan_message or "").lower()
        for p in ("audio", "voz", "susurr", "escúch", "🎙", "oír", "oir", "graba")
    ):
        return True, "fan asking for voice now"
    return False, ""


def _hard_blocks(
    *,
    mem: dict,
    decision: Any,
    pack_id: str,
    media_sent_this_turn: bool,
    barged: bool,
    fan_message: str = "",
    history_turns: Optional[List] = None,
    voice_thread: bool = False,
) -> Optional[str]:
    if not _enabled():
        return "disabled or no API key"
    if barged:
        return "barge-in"
    # unpaid PPV photo does NOT block voice — fan may want audio instead of unlocking
    if pack_id in _BLOCK_PACKS:
        return "objection/delivery block"
    if media_sent_this_turn:
        return "photo turn"
    if int(mem.get("messages") or 0) < int(getattr(config, "VOICE_NOTES_MIN_MESSAGES", 8) or 8):
        return "too early in chat"
    if _voice_count_today(mem) >= int(getattr(config, "VOICE_NOTES_MAX_PER_DAY", 2) or 2):
        if not voice_thread:
            return "daily cap"
        print("   🎙️ daily cap bypass — fan waiting for voice")
    cooldown_h = float(getattr(config, "VOICE_NOTES_COOLDOWN_HOURS", 6) or 6)
    last = _parse_iso(mem.get("last_voice_at"))
    if last and datetime.now(timezone.utc) - last < timedelta(hours=cooldown_h):
        if not voice_thread:
            return "cooldown"
        print("   🎙️ cooldown bypass — fan waiting for voice")
    mode = (getattr(decision, "mode", "") or "").lower()
    if mode in ("hard_sell", "chill"):
        return f"mode={mode}"
    return None


def _ai_should_send_voice(
    fan_message: str,
    history_turns: Optional[List],
    *,
    pack_id: str,
    mode: str,
    unpaid: bool = False,
) -> tuple[bool, str]:
    """DeepSeek reads context — no keyword triggers."""
    from openai import OpenAI

    api_key = (getattr(config, "DEEPSEEK_API_KEY", "") or "").strip()
    if not api_key:
        return False, "no deepseek key"

    snippet = _history_snippet(history_turns)
    system = (
        "You decide if Emma should send a FREE sensual voice note THIS turn on Fanvue.\n"
        "Voice notes are intimate spoken audio (whisper, dirty talk) — NOT photos, NOT PPV.\n"
        "They are rare (max ~2/day). Read the full thread, not just keywords.\n\n"
        "YES when examples like:\n"
        "- Fan wants to hear her / whisper / audio / something spoken dirty\n"
        "- She offered to whisper or record and fan agreed (sii, vava, do it…)\n"
        "- Hot peak where voice fits better than pushing a paid photo right now\n"
        "- Fan complained last audio was weak — she should redo it with voice, not sell a pic\n\n"
        "NO when:\n"
        "- Fan wants a photo/video, price, or unlock\n"
        "- Objection, cold, billing dispute\n"
        "- Better to sell PPV or stay text-only this turn\n\n"
        "IMPORTANT: An unpaid PPV photo in chat does NOT block voice. "
        "If fan wants audio / is waiting for a voice note, say YES — voice is free, separate from the lock.\n\n"
        "Reply ONE line only: YES: <short reason>  OR  NO: <short reason>"
    )
    unpaid_note = " (unpaid photo lock open in chat)" if unpaid else ""
    user = (
        f"Pack: {pack_id} | Mode: {mode}{unpaid_note}\n\n"
        f"Recent chat:\n{snippet}\n\n"
        f"Fan message now: {(fan_message or '')[:400]}"
    )
    client = OpenAI(
        api_key=api_key,
        base_url=getattr(config, "DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1"),
    )
    try:
        resp = _deepseek_create(
            client,
            model=getattr(config, "DEEPSEEK_MODEL", "deepseek-v4-pro"),
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            max_tokens=60,
            temperature=0.2,
        )
        raw = (resp.choices[0].message.content or "").strip()
        upper = raw.upper()
        if upper.startswith("YES"):
            reason = raw.split(":", 1)[1].strip() if ":" in raw else raw[3:].strip()
            return True, reason or "ai yes"
        if upper.startswith("NO"):
            reason = raw.split(":", 1)[1].strip() if ":" in raw else raw[2:].strip()
            return False, reason or "ai no"
        print(f"   🎙️ ai voice parse unclear: {raw[:80]!r}")
        return False, "ai unclear"
    except Exception as e:
        print(f"   🎙️ ai voice check failed: {type(e).__name__}: {e}")
        return False, "ai error"


def should_send(
    *,
    fan_message: str,
    mem: dict,
    decision: Any,
    pack_id: str,
    unpaid: bool,
    media_sent_this_turn: bool,
    barged: bool,
    history_turns: Optional[List] = None,
) -> tuple[bool, str]:
    """Return (ok, reason) for logging."""
    thread_ok, thread_why = _voice_thread_active(fan_message, history_turns)
    blocked = _hard_blocks(
        mem=mem,
        decision=decision,
        pack_id=pack_id,
        media_sent_this_turn=media_sent_this_turn,
        barged=barged,
        fan_message=fan_message,
        history_turns=history_turns,
        voice_thread=thread_ok,
    )
    if blocked:
        return False, blocked

    if thread_ok:
        print(f"   🎙️ voice thread: YES — {thread_why}")
        return True, thread_why

    mode = (getattr(decision, "mode", "") or "").lower()
    ok, reason = _ai_should_send_voice(
        fan_message,
        history_turns,
        pack_id=pack_id,
        mode=mode,
        unpaid=unpaid,
    )
    if ok:
        print(f"   🎙️ ai voice: YES — {reason[:100]}")
    else:
        print(f"   🎙️ ai voice: NO — {reason[:100]}")
    return ok, reason


def plan_send(
    *,
    fan_message: str,
    mem: dict,
    decision: Any,
    pack_id: str,
    unpaid: bool,
    media_sent_this_turn: bool,
    history_turns: Optional[List] = None,
) -> tuple[bool, str]:
    """Pre-reply: DeepSeek + hard limits. Voice beats photo when this returns True."""
    return should_send(
        fan_message=fan_message,
        mem=mem,
        decision=decision,
        pack_id=pack_id,
        unpaid=unpaid,
        media_sent_this_turn=media_sent_this_turn,
        barged=False,
        history_turns=history_turns,
    )


_V3_TAG = re.compile(r"\[[^\]]+\]")
_EMOJI = re.compile(
    r"[\U0001F300-\U0001FAFF\U00002700-\U000027BF\U0001F600-\U0001F64F]+",
    flags=re.UNICODE,
)

_V3_TAGS_DELIVERY = (
    "[whispers]", "[sighs]", "[exhales]", "[mischievously]", "[playfully]", "[excited]",
    "[curious]", "[snorts]", "[nervous]", "[cheerfully]",
)
_V3_TAGS_REACTIONS = (
    "[chuckles]", "[laughs]", "[laughing]", "[gulps]", "[gasps]", "[clears throat]",
)
_V3_TAGS_PAUSES = (
    "[short pause]", "[long pause]", "[inhales deeply]", "[exhales sharply]",
)


def _v3_tags_for_prompt() -> str:
    d = ", ".join(_V3_TAGS_DELIVERY)
    r = ", ".join(_V3_TAGS_REACTIONS)
    p = ", ".join(_V3_TAGS_PAUSES)
    return (
        f"Delivery/emotion: {d}\n"
        f"Reactions: {r}\n"
        f"Pauses/breath: {p}\n"
        "(Official Eleven v3 set — you may use similar tags from the same families.)"
    )


def _finalize_script(raw: str) -> str:
    """Keep v3 audio tags; strip emojis; never force extra tags."""
    s = (raw or "").strip().strip('"\'')
    s = _EMOJI.sub("", s).strip()
    s = re.sub(r"\s{2,}", " ", s)
    return s


def _generate_script(
    fan_message: str,
    reply: str,
    *,
    want_spanish: bool,
    trigger_reason: str,
) -> str:
    from openai import OpenAI

    api_key = (getattr(config, "DEEPSEEK_API_KEY", "") or "").strip()
    max_c = int(getattr(config, "VOICE_NOTE_MAX_CHARS", 320) or 320)
    min_c = int(getattr(config, "VOICE_NOTE_MIN_CHARS", 100) or 100)
    if not api_key:
        return _fallback_script(want_spanish)

    lang = "Spanish" if want_spanish else "English"
    lang_code = "es" if want_spanish else "en"
    tags_block = _v3_tags_for_prompt()
    system = (
        "You write ONLY the spoken script for Emma's Fanvue voice note — ElevenLabs v3 TTS.\n"
        f"Language: {lang} ONLY (language_code={lang_code}).\n"
        f"Length: 25–50 words, {min_c}–{max_c} chars (~10–18 sec).\n"
        "Tone: filthy hungry girlfriend — explicit (Spanish: coño, mojada, empapada, polla… / "
        "English: wet, cock, dripping…).\n\n"
        "ELEVEN v3 AUDIO TAGS (official — like the web 'Enhance' button):\n"
        f"{tags_block}\n"
        "RULES (do not over-tag):\n"
        "- Use 0–2 tags total. Zero tags is fine if dirty talk + punctuation carry the moment.\n"
        "- Tag only when it adds real delivery (tease, sigh, whisper) — not every sentence.\n"
        "- Place tag immediately BEFORE the phrase it affects, or after a line for trailing reaction.\n"
        "- Prefer … .... !!! ??? and CAPS for rhythm; tags are seasoning.\n"
        "- Tags are NOT spoken — square brackets only.\n\n"
        "Examples:\n"
        "  [chuckles] ¿Sigues ahí, travieso?.... [sighs] Me dejaste toda mojada y desapareciste…\n"
        "  [whispers] Estoy empapada pensando en ti.... ¿Estás duro ahora mismo???\n"
        "  Joder.... no paras de metérteme en la cabeza.... Estoy MOJADA.... ¿Vas a contestarme???\n"
        "Never mention photos, PPV, prices. No emojis. Output ONLY the script."
    )
    whisper_moment = any(
        p in ((fan_message or "") + " " + trigger_reason).lower()
        for p in ("susurr", "whisper", "escúch", "escuch", "oído", "oido", "guarrad")
    )
    if whisper_moment:
        system += (
            "\n\nThis moment needs intimate WHISPER delivery — start with [whispers] "
            "and keep it filthy, close, al oído."
        )
    user = (
        f"Moment: {trigger_reason}\n"
        f"He said: {(fan_message or '')[:280]}\n"
        f"Emma just texted: {(reply or '')[:280]}\n"
        f"Write one v3 voice note in {lang}. Use 0–2 official tags only if they fit."
    )
    client = OpenAI(
        api_key=api_key,
        base_url=getattr(config, "DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1"),
    )
    try:
        resp = _deepseek_create(
            client,
            model=getattr(config, "DEEPSEEK_MODEL", "deepseek-v4-pro"),
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            max_tokens=200,
            temperature=1.0,
        )
        raw = (resp.choices[0].message.content or "").strip()
        if not raw:
            print("   🎙️ script: DeepSeek returned empty — using fallback")
            return _fallback_script(want_spanish, whisper=whisper_moment)
        script = _finalize_script(raw)
        if not script:
            print("   🎙️ script: empty after finalize — using fallback")
            return _fallback_script(want_spanish, whisper=whisper_moment)
        n_tags = len(_V3_TAG.findall(script))
        if n_tags > 2:
            print(f"   🎙️ script has {n_tags} tags (prefer ≤2)")
        if script and min_c <= len(script) <= max_c:
            return script
        if script and len(script) > max_c:
            return script[:max_c].rsplit(" ", 1)[0]
        if script and len(script) < min_c:
            print(f"   🎙️ script too short ({len(script)}c) — using fallback")
    except Exception as e:
        print(f"   🎙️ script generation failed: {type(e).__name__}: {e}")
    return _fallback_script(want_spanish, whisper=whisper_moment)


def _fallback_script(want_spanish: bool, *, whisper: bool = False) -> str:
    if want_spanish:
        if whisper:
            opts = [
                (
                    "[whispers] Escucha, travieso.... Estoy empapada pensando en tu polla.... "
                    "Quiero sentirte dentro.... ¿Estás duro ahora mismo??? "
                    "[sighs] No me dejes sola así...."
                ),
                (
                    "[whispers] ¿Sigues ahí, baby?.... Me prometiste que ibas a escucharme.... "
                    "Estoy tan mojada.... Dime qué me harías.... ahora...."
                ),
            ]
        else:
            opts = [
                (
                    "[chuckles] ¿Sigues ahí, travieso?.... [sighs] Me dejaste toda mojada "
                    "y desapareciste.... ¿Vas a contestarme o qué???"
                ),
                (
                    "Joder.... no paras de metérteme en la cabeza.... "
                    "[sighs] Me estoy tocando sola.... ¿Estás duro ahora mismo???"
                ),
                (
                    "[whispers] Escucha.... Estoy tan mojada que no aguanto.... "
                    "Dime qué me harías.... ahora...."
                ),
            ]
    else:
        opts = [
            (
                "[chuckles] You still there, trouble?.... [sighs] You got me dripping "
                "and vanished.... Are you hard right now???"
            ),
            (
                "Fuck.... I can't stop thinking about your cock.... "
                "[exhales sharply] I'm touching myself.... Don't leave me hanging...."
            ),
        ]
    return random.choice(opts)


_VOICE_CAPTIONS_ES = (
    "cierra los ojos…. 😈",
    "solo para ti…. 🔥",
    "al oído, guapo…. 💋",
    "shhh…. 🤫",
    "no se lo cuentes a nadie…. 😏",
    "pensé en ti grabando esto…. 💦",
    "para cuando estés duro…. 🫦",
    "te lo susurro…. 😈",
    "dime si te pones…. 💋",
    "una confesión tuya…. 🔥",
    "ponme en altavoz…. 😏",
    "esto no es para todos…. 🤫",
)
_VOICE_CAPTIONS_EN = (
    "close your eyes…. 😈",
    "just for you…. 🔥",
    "in your ear, babe…. 💋",
    "shhh…. 🤫",
    "don't share this…. 😏",
    "made this thinking of you…. 💦",
    "for when you're hard…. 🫦",
    "whispering this one…. 😈",
    "tell me if it gets you…. 💋",
    "a confession…. 🔥",
    "put me on speaker…. 😏",
    "not for everyone…. 🤫",
)


def _pick_caption(want_spanish: bool, mem: dict) -> str:
    pool = _VOICE_CAPTIONS_ES if want_spanish else _VOICE_CAPTIONS_EN
    recent = set((mem.get("recent_voice_captions") or [])[-6:])
    choices = [c for c in pool if c not in recent] or list(pool)
    return random.choice(choices)


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
    history_turns: Optional[List] = None,
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

    want_spanish = language.fan_wants_spanish(fan_message, mem)
    print(f"   🎙️ voice note trigger: {why}")

    script = _generate_script(
        fan_message,
        reply,
        want_spanish=want_spanish,
        trigger_reason=why,
    )
    print(f"   🎙️ script ({len(script)}c): {script}")

    audio_path = None
    try:
        try:
            fv.send_typing_indicator(fan_uuid, True)
        except Exception:
            pass

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
        caption = _pick_caption(want_spanish, mem)
        fv.send_media_message(
            fan_uuid,
            media_uuids=[media_uuid],
            text=caption[:500],
        )
        time.sleep(0.8)
        verified = fv.creator_media_in_chat(
            fan_uuid,
            creator_uuid,
            media_uuid,
        )
        if not verified:
            print("   ⚠️ voice note sent but not verified in chat")
        fan_memory.record_voice_note(
            fan_uuid, fan_handle=fan_handle, script=script, caption=caption
        )
        print(f"   🎙️ voice note sent to @{fan_handle}")
        return True
    except Exception as e:
        print(f"   ❌ voice note failed: {type(e).__name__}: {e}")
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
