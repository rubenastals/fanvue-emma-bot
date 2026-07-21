"""
Automatic re-engagement — hot/cold ladder + visto-gated victim.

TIMING (no farewell / conversation left open):
  1st nudge ≥ NUDGE_FIRST_MINUTES (default 7, hot and cold same gate)
  2nd nudge ≥ NUDGE_SECOND_MINUTES (default 36), only if still silent
  Max 2 mid-flow nudges per silence episode.

Victim "me has olvidado" ONLY when Fanvue marks Emma's last msg isRead (visto)
AND we are still inside VICTIM_AFTER_SEEN_MINUTES (default 60) of first visto detect.
Never the default angle — rotating soft angles otherwise.

If they said goodbye → skip mid-flow nudges; only next-day good morning.

Nudge messages are generated from hardcoded templates (no DeepSeek call).
"""
from __future__ import annotations

import os
import random
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

from core import convo_log, fan_memory, language, persona_time
from core.reply_engine import split_into_messages
from core.turn_policy import TurnDecision

NUDGE_HOT_MINUTES = int(os.getenv("NUDGE_HOT_MINUTES", "7"))
NUDGE_COLD_MINUTES = int(os.getenv("NUDGE_COLD_MINUTES", "7"))
NUDGE_FIRST_MINUTES = int(
    os.getenv("NUDGE_FIRST_MINUTES", str(max(NUDGE_HOT_MINUTES, NUDGE_COLD_MINUTES)))
)
NUDGE_SECOND_MINUTES = int(os.getenv("NUDGE_SECOND_MINUTES", "36"))
if os.getenv("NUDGE_FIRST_MINUTES") and not os.getenv("NUDGE_COLD_MINUTES"):
    NUDGE_COLD_MINUTES = int(os.getenv("NUDGE_FIRST_MINUTES", "5"))

GOODMORNING_AFTER_HOURS = int(os.getenv("GOODMORNING_AFTER_HOURS", "14"))
GOODMORNING_HOUR_START = int(os.getenv("GOODMORNING_HOUR_START", "8"))
GOODMORNING_HOUR_END = int(os.getenv("GOODMORNING_HOUR_END", "13"))
MAX_NUDGES_PER_EPISODE = int(os.getenv("MAX_NUDGES_PER_EPISODE", "2"))
VICTIM_AFTER_SEEN_MINUTES = int(os.getenv("VICTIM_AFTER_SEEN_MINUTES", "60"))
VICTIM_COOLDOWN_HOURS = int(os.getenv("VICTIM_COOLDOWN_HOURS", "12"))

_FAREWELL = re.compile(
    r"(?i)\b("
    r"good ?night|gn|bye|see (you|ya)|talk (later|soon|tomorrow)|ttyl|gtg|"
    r"going to (bed|sleep)|sleep well|sweet dreams|"
    r"adi[oó]s|buenas noches|hasta (ma[nñ]ana|luego|pronto)|me voy|"
    r"nos vemos|descansa|dulces sue[nñ]os|a dormir|chao|cuidate|te cuidas"
    r")\b"
)

_HEAT_WORDS = re.compile(
    r"(?i)\b("
    r"hard|horny|wet|cock|dick|pussy|fuck|cum|stroke|jerk|"
    r"duro|caliente|mojada|polla|follar|correr|"
    r"besos|folla|xxx|desnuda|touch|kiss|babe|bebe|mi vida|"
    r"te quiero|te deseo|harder|m[aá]s duro|mandala|dale|unlock"
    r")\b"
)

# ---------------------------------------------------------------------------
# Template nudges — zero DeepSeek calls
# ---------------------------------------------------------------------------
_TEMPLATES: Dict[str, Dict[str, List[str]]] = {
    "unfinished_thread": {
        "es": [
            "Oye… te perdí por el camino 😏 ¿Sigues ahí?",
            "Me dejaste con las ganas… ¿qué pasó? 👀",
            "Te fuiste justo cuando se estaba poniendo interesante 😒",
            "Hola?? estás desaparecido 🙄",
        ],
        "en": [
            "Hey… you disappeared on me 😏 Still there?",
            "You left me hanging… what happened? 👀",
            "You vanished right when it was getting good 😒",
            "Hello?? you went ghost on me 🙄",
        ],
    },
    "soft_checkin": {
        "es": [
            "¿Todo bien? Te quedaste callado de repente 🥺",
            "Oye, ¿estás bien? Pensé que seguíamos hablando…",
            "¿Se te fue la luz o me ignoras? 😏",
            "Eh, ¿sigues vivo? 😂",
        ],
        "en": [
            "Hey, you good? You went quiet on me 🥺",
            "Everything okay? I thought we were still talking…",
            "Did you lose signal or are you ignoring me? 😏",
            "Oi, still alive? 😂",
        ],
    },
    "playful_brat": {
        "es": [
            "Me dejaste con el mensaje en visto y te fuiste… qué malo eres 😒",
            "Vaya con el hombre misterioso… ¿dónde te metiste? 🙄",
            "Hey babe, you can't just disappear like that 😤",
            "¿Me ignorás o se te olvidó que estábamos hablando? 😏",
        ],
        "en": [
            "Left me on read and just bounced… rude 😒",
            "Look at Mr. Mysterious vanishing… where'd you go? 🙄",
            "Hey babe, you can't just disappear like that 😤",
            "Are you ignoring me or did you forget we were talking? 😏",
        ],
    },
    "almost_sent": {
        "es": [
            "Estaba a punto de mandarte algo… y desapareciste 👀",
            "Iba a sorprenderte con algo pero… ¿te fuiste? 😏",
            "Tenía algo especial para ti y te esfumaste 😒",
            "Casi te mando algo muy bueno… ¿apareces o qué? 😏",
        ],
        "en": [
            "Was just about to send you something… and you vanished 👀",
            "Had a little surprise for you but… you disappeared? 😏",
            "Had something special and you ghosted me 😒",
            "Almost sent you something good… you coming back or what? 😏",
        ],
    },
    "busy_withdrawal": {
        "es": [
            "Bueno… me voy que tengo cosas que hacer 😏 Escríbeme cuando puedas.",
            "Oye, me voy un rato. Si vuelves, aquí estaré 😉",
            "Vale, me pierdo. No tardes mucho 😏",
            "Me voy, que si no voy a estar esperando toda la noche 😒",
        ],
        "en": [
            "Okay… I'm heading out, got things to do 😏 Write me when you're back.",
            "Hey, stepping away for a bit. I'll be here if you come back 😉",
            "Alright, I'm off. Don't keep me waiting too long 😏",
            "I'm going — I'm not waiting all night you know 😒",
        ],
    },
    "victim_soft": {
        "es": [
            "Lo viste y no contestaste… eso duele un poquito 🥺",
            "Me dejaste en visto… ¿en serio? 😢",
            "Vaya, lo leíste y nada… pensé que éramos algo especial 😏",
            "¿Tan malo fue lo que dije? 🥺",
        ],
        "en": [
            "You read it and didn't answer… that stings a little 🥺",
            "Left me on read… seriously? 😢",
            "Wow, you read it and nothing… thought we had something special 😏",
            "Was what I said that bad? 🥺",
        ],
    },
    "goodmorning": {
        "es": [
            "Good morning babe… you were the first thing I thought of 😏",
            "Buenas… ¿dormiste bien? Yo soñé cosas muy malas 😈",
            "Morning 😏 ¿Sigues ahí o te perdí para siempre?",
            "Despertándome y ya pensando en ti… eso es tu culpa 😒",
        ],
        "en": [
            "Good morning… you were the first thing I thought of 😏",
            "Morning… did you sleep well? I had very bad dreams 😈",
            "Morning 😏 Still there or did I lose you forever?",
            "Waking up already thinking about you… that's your fault 😒",
        ],
    },
}


def _pick_nudge_template(style: str, want_spanish: bool, mem: dict) -> str:
    """Pick a template line, avoiding the last used one."""
    pool = _TEMPLATES.get(style, _TEMPLATES["soft_checkin"])
    lines = pool["es"] if want_spanish else pool["en"]
    last = (mem.get("last_nudge_text") or "")
    choices = [l for l in lines if l != last] or lines
    return random.choice(choices)


# Keep angle metadata for step/weight routing (no trigger string needed).
NUDGE_ANGLES: Dict[str, dict] = {
    "unfinished_thread": {"steps": (1,), "weight": 3},
    "soft_checkin": {"steps": (1, 2), "weight": 3},
    "playful_brat": {"steps": (1,), "weight": 3},
    "almost_sent": {"steps": (1, 2), "weight": 2},
    "busy_withdrawal": {"steps": (2,), "weight": 3},
    "victim_soft": {"steps": (2,), "weight": 2},
}

GOODMORNING_TRIGGER = "goodmorning"


def _msg_ts(msg: dict) -> Optional[datetime]:
    for key in ("createdAt", "created_at", "sentAt", "sent_at", "timestamp"):
        v = msg.get(key)
        if not v:
            continue
        try:
            return datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        except ValueError:
            continue
    return None


def _sender_uuid(msg: dict) -> Optional[str]:
    sender = msg.get("sender")
    if isinstance(sender, dict):
        return sender.get("uuid")
    if isinstance(sender, str):
        return sender
    return None


def _last_fan_text(messages: List[dict], fan_uuid: str) -> str:
    for msg in messages:
        if _sender_uuid(msg) == fan_uuid and (msg.get("text") or "").strip():
            return msg["text"].strip()
    return ""


def _ended_with_farewell(messages: List[dict]) -> bool:
    texts = [(m.get("text") or "") for m in messages[:2]]
    return any(_FAREWELL.search(t) for t in texts if t)


def _parse_iso(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except ValueError:
        return None


def _chat_is_hot(messages: List[dict], fan_uuid: str, mem: dict) -> bool:
    """Hot = recent dirty/buy energy or spender heat — nudge sooner."""
    status = (mem.get("status") or "").lower()
    if status in ("spender", "whale"):
        return True
    # Last few fan texts
    hits = 0
    checked = 0
    for msg in messages[:8]:
        if _sender_uuid(msg) != fan_uuid:
            continue
        text = (msg.get("text") or "").strip()
        if not text:
            continue
        checked += 1
        if _HEAT_WORDS.search(text):
            hits += 1
        if checked >= 4:
            break
    if hits >= 1:
        return True
    # Dense chat recently
    if int(mem.get("messages") or 0) >= 12 and status in ("warm", "spender", "whale"):
        return True
    return False


def _creator_last_is_read(
    messages: List[dict], creator_uuid: str
) -> Tuple[bool, Optional[datetime]]:
    """Fanvue isRead on Emma's newest message (= visto)."""
    for msg in messages:
        if _sender_uuid(msg) != creator_uuid:
            continue
        return bool(msg.get("isRead")), _msg_ts(msg)
    return False, None


def _victim_window_open(
    mem: dict,
    *,
    is_read: bool,
    fan_uuid: str,
    fan_handle: str,
    now: datetime,
) -> bool:
    """
    Victim only inside 1h of first visto detection (isRead=true).
    """
    if not is_read:
        return False
    seen_at = _parse_iso(mem.get("last_seen_by_fan_at"))
    if not seen_at:
        stamp = fan_memory.mark_seen_by_fan(fan_uuid, fan_handle=fan_handle)
        seen_at = _parse_iso(stamp)
    if not seen_at:
        return False
    if now - seen_at > timedelta(minutes=VICTIM_AFTER_SEEN_MINUTES):
        return False
    last_vic = _parse_iso(mem.get("last_victim_nudge_at"))
    if last_vic and now - last_vic < timedelta(hours=VICTIM_COOLDOWN_HOURS):
        return False
    return True


def pick_nudge_angle(
    mem: dict,
    step: int,
    now: datetime,
    *,
    victim_ok: bool,
) -> str:
    """
    Pick a re-engagement angle for this step.
    Avoid last style; victim_soft only when victim_ok (visto ≤1h).
    """
    last = (mem.get("last_nudge_style") or "").strip()
    candidates: List[Tuple[str, int]] = []
    for name, meta in NUDGE_ANGLES.items():
        if step not in meta["steps"]:
            continue
        if name == "victim_soft" and not victim_ok:
            continue
        if name == last and len(NUDGE_ANGLES) > 1:
            continue
        candidates.append((name, int(meta.get("weight") or 1)))
    if not candidates:
        for name, meta in NUDGE_ANGLES.items():
            if step in meta["steps"] and name != "victim_soft":
                candidates.append((name, 1))
    if not candidates:
        return "soft_checkin"
    names, weights = zip(*candidates)
    return random.choices(list(names), weights=list(weights), k=1)[0]


def _nudge_step_for_silence(
    silence: timedelta, mem: dict, *, hot: bool
) -> Optional[int]:
    """
    step 1 at ≥ NUDGE_FIRST_MINUTES
    step 2 at ≥ NUDGE_SECOND_MINUTES if episode count 1
    """
    count = int(mem.get("nudge_episode_count") or 0)
    if count >= MAX_NUDGES_PER_EPISODE:
        return None
    mins = silence.total_seconds() / 60.0
    first_gate = NUDGE_FIRST_MINUTES
    if count == 0 and mins >= first_gate:
        return 1
    if count == 1 and mins >= NUDGE_SECOND_MINUTES:
        return 2
    return None


def _send_generated(
    fv,
    fan_uuid: str,
    fan_handle: str,
    messages: List[dict],
    creator_uuid: str,
    trigger: str,
    kind: str,
    *,
    style: str = "",
) -> bool:
    mem = fan_memory.get(fan_uuid) or {}
    last_fan = _last_fan_text(messages, fan_uuid)
    want_spanish = language.fan_wants_spanish(last_fan, mem) if last_fan else bool(
        mem.get("prefer_spanish")
    )

    # Template path — no DeepSeek call needed for nudges
    nudge_style = style or kind
    reply = _pick_nudge_template(nudge_style, want_spanish, mem)
    # Store last nudge text to avoid repetition next time
    try:
        from core import fan_memory as _fm
        _fm.patch_fanvue_platform(fan_uuid, {"last_nudge_text": reply}, fan_handle=fan_handle)
    except Exception:
        pass
    if not reply.strip():
        return False

    bubbles = split_into_messages(reply, max_bubbles=2)
    for i, bubble in enumerate(bubbles):
        try:
            fv.send_typing_indicator(fan_uuid, True)
        except Exception:
            pass
        # Same human-ish cadence as live chat (not 7s walls)
        time.sleep(random.uniform(2.0, 3.5) if i == 0 else random.uniform(1.2, 2.5))
        fv.send_message(fan_uuid, bubble)
        if i + 1 < len(bubbles):
            try:
                fv.send_typing_indicator(fan_uuid, True)
            except Exception:
                pass
        else:
            try:
                fv.send_typing_indicator(fan_uuid, False)
            except Exception:
                pass

    fan_memory.mark_nudge(
        fan_uuid, kind, fan_handle=fan_handle, style=style
    )
    try:
        convo_log.log_turn(
            fan_uuid,
            fan_handle=fan_handle,
            fan_message=f"[silence — {kind}:{style or '-'}]",
            reply=reply,
            bubbles=len(bubbles),
            mode=kind,
            mode_reason=f"auto re-engagement {kind}/{style}",
            pack_id="phase_reengage",
        )
    except Exception:
        pass
    print(
        f"   💌 {kind}/{style or '-'} sent to @{fan_handle}: {reply[:70]}"
    )
    return True


def run_pass(fv, chats: List[dict], creator_uuid: str) -> int:
    """Check silent chats; send at most a few re-engagements per pass."""
    sent = 0
    now = datetime.now(timezone.utc)
    local_hour = persona_time.la_now().hour

    for chat in chats:
        if sent >= 3:
            break
        user = chat.get("user", {})
        fan_uuid = user.get("uuid")
        fan_handle = user.get("handle", "fan")
        if not fan_uuid:
            continue

        mem = fan_memory.get(fan_uuid)
        if not mem or int(mem.get("messages") or 0) < 1:
            continue

        try:
            messages = fv.get_messages(fan_uuid, size=8)
        except Exception:
            continue
        if not messages:
            continue

        newest = messages[0]
        if _sender_uuid(newest) != creator_uuid:
            continue
        ts = _msg_ts(newest)
        if not ts:
            continue
        silence = now - ts
        pass_farewell = _ended_with_farewell(messages)
        hot = _chat_is_hot(messages, fan_uuid, mem)
        is_read, _ = _creator_last_is_read(messages, creator_uuid)
        if is_read and not mem.get("last_seen_by_fan_at"):
            fan_memory.mark_seen_by_fan(fan_uuid, fan_handle=fan_handle)
            mem = fan_memory.get(fan_uuid) or mem

        # RULE — next-day good morning
        today = persona_time.la_today()
        if (
            silence >= timedelta(hours=GOODMORNING_AFTER_HOURS)
            and mem.get("last_goodmorning_day") != today
            and GOODMORNING_HOUR_START <= local_hour < GOODMORNING_HOUR_END
        ):
            trigger = GOODMORNING_TRIGGER
            if _send_generated(
                fv,
                fan_uuid,
                fan_handle,
                messages,
                creator_uuid,
                trigger,
                "goodmorning",
                style="goodmorning",
            ):
                sent += 1
            continue

        if pass_farewell:
            continue  # closed politely — don't mid-flow guilt

        step = _nudge_step_for_silence(silence, mem, hot=hot)
        if not step:
            continue

        # Don't fire a second nudge too soon after the first (step 2 still needs NUDGE_SECOND_MINUTES silence)
        last_nudge = _parse_iso(mem.get("last_nudge_at"))
        min_gap = max(5, NUDGE_FIRST_MINUTES // 2)
        if last_nudge and now - last_nudge < timedelta(minutes=min_gap):
            continue

        victim_ok = step >= 2 and _victim_window_open(
            mem,
            is_read=is_read,
            fan_uuid=fan_uuid,
            fan_handle=fan_handle,
            now=now,
        )
        style = pick_nudge_angle(mem, step, now, victim_ok=victim_ok)
        heat_label = "HOT" if hot else "COLD"
        print(
            f"   reengage @{fan_handle}: step={step} angle={style} "
            f"heat={heat_label} visto={is_read} "
            f"silence={int(silence.total_seconds() // 60)}m"
        )
        if _send_generated(
            fv,
            fan_uuid,
            fan_handle,
            messages,
            creator_uuid,
            style,
            "nudge",
            style=style,
        ):
            sent += 1

    return sent
