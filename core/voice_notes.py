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
from utils.elevenlabs_client import is_configured, synthesize_to_file

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
        "phase_pull",
        "rapport",
        "reward_purchase",
        "phase_hook",
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
    r"(?i)\b("
    r"audio|audios|voice note|voice memo|voz|nota de voz|"
    r"gr\u00e1bame|grabame|m\u00e1ndame audio|mandame audio|"
    r"env\u00edame audio|enviame audio|escucharte|"
    r"whisper|susurra|al o\u00eddo|al oido"
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
) -> tuple[bool, str]:
    """Return (ok, reason) for logging."""
    if not _enabled():
        return False, "disabled or no API key"
    if barged:
        return False, "barge-in"
    if unpaid or pack_id in _BLOCK_PACKS:
        return False, "sell/objection/reengage block"
    if media_sent_this_turn:
        return False, "photo turn"
    if int(mem.get("messages") or 0) < int(getattr(config, "VOICE_NOTES_MIN_MESSAGES", 8) or 8):
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
    if fan_asked_voice(fan_message):
        trigger, reason = True, "fan asked voice"
    elif reward:
        trigger, reason = True, "post-purchase reward"
    elif horny >= 2:
        trigger, reason = True, f"very horny fan ({horny} hits)"
    elif horny >= 1 and heat_pack and mode in ("tease", "soft_sell", "rapport"):
        trigger, reason = True, "heating spiral"
    elif emotional and heat_pack:
        trigger, reason = True, "emotional bond moment"

    if not trigger:
        return False, "no key moment"

    if apply_roll and not fan_asked_voice(fan_message):
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
    )


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
        return _fallback_script(want_spanish)

    lang = "Spanish" if want_spanish else "English"
    system = (
        "You write the spoken script for a dirty girlfriend voice note. "
        "Like a real horny girl grabbing her phone because she HAD to say this right now. "
        "Raw, filthy, breathy. Use explicit dirty language naturally: "
        "cock, wet, dripping, I want you inside me, touching myself, "
        "you make me so horny, fuck me hard, I'm soaking for you, "
        "I keep thinking about your cock, etc. "
        "15-40 words. Heavy intonation: mmm, ah, ... pauses, moans, soft sighs. "
        "Sound completely spontaneous and real, not scripted or polished. "
        "NEVER mention photos, prices, PPV, unlocking, or anything salesy. "
        "Output ONLY the spoken words. No stage directions, no brackets, no quotes."
    )
    user = (
        f"Language: {lang}\n"
        f"Context: {trigger_reason}\n"
        f"He just said: {(fan_message or '')[:200]}\n"
        f"Emma's last text: {(reply or '')[:200]}\n"
        "Write the voice note she impulsively sends right now."
    )
    client = OpenAI(
        api_key=api_key,
        base_url=getattr(config, "DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1"),
    )
    try:
        resp = client.chat.completions.create(
            model=getattr(config, "DEEPSEEK_FAST_MODEL", None) or getattr(config, "DEEPSEEK_MODEL", "deepseek-v4-pro"),
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            max_tokens=80,
            temperature=1.0,
        )
        raw = (resp.choices[0].message.content or "").strip()
        raw = raw.strip('"\'')
        raw = re.sub(r"\[.*?\]", "", raw).strip()
        if raw and len(raw) <= int(getattr(config, "VOICE_NOTE_MAX_CHARS", 320) or 320):
            return raw
    except Exception:
        pass
    return _fallback_script(want_spanish)


def _fallback_script(want_spanish: bool) -> str:
    if want_spanish:
        opts = [
            "Mmm... me tienes tan mojada ahora mismo... no puedo parar de pensar en lo que me harias...",
            "Joder... llevo pensando en tu polla todo el dia... estoy empapada...",
            "Ah... me estoy tocando pensando en ti... ven aqui ya...",
        ]
    else:
        opts = [
            "Mmm... you got me so fucking wet right now... I can't stop thinking about you inside me...",
            "God... I've been thinking about your cock all day... I'm literally dripping...",
            "Ah... I'm touching myself thinking about you... get over here...",
            "Fuck... you have no idea what you do to me... I'm soaking right now...",
            "Mmm... I need you so bad right now... thinking about riding you...",
        ]
    return random.choice(opts)


def _caption_for(want_spanish: bool) -> str:
    return ""


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
        )
    if not ok:
        return False

    want_spanish = language.fan_wants_spanish(fan_message, mem)
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

        audio_path = synthesize_to_file(script)
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
        fv.send_media_message(
            fan_uuid,
            media_uuids=[media_uuid],
            text="",
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
