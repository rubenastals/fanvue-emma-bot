"""
Automatic re-engagement — hot/cold ladder + visto-gated victim.

TIMING (no farewell / conversation left open):
  1st nudge ≥ NUDGE_FIRST_MINUTES (default 12, hot and cold same gate)
  2nd nudge ≥ NUDGE_SECOND_MINUTES (default 45), only if still silent
  Max 2 mid-flow nudges per silence episode.
  Silence clock = time since Emma's last message (fan must not have replied).

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
from core.chat_heat import active_window_minutes, chat_heat_score, heat_label, is_hot_score, is_warm_score
from core.farewell import (
    conversation_closed,
    fan_closed_in_messages,
    mark_conversation_closed,
    reengage_paused,
)
from core.reply_engine import split_into_messages
from core.turn_policy import TurnDecision

# Respect silence: first nudge after a real pause (shorter when hot / visto).
NUDGE_HOT_MINUTES = int(os.getenv("NUDGE_HOT_MINUTES", "6"))
NUDGE_COLD_MINUTES = int(os.getenv("NUDGE_COLD_MINUTES", "12"))
NUDGE_HOT_SEEN_MINUTES = int(os.getenv("NUDGE_HOT_SEEN_MINUTES", "4"))
NUDGE_WARM_SEEN_MINUTES = int(os.getenv("NUDGE_WARM_SEEN_MINUTES", "7"))
NUDGE_REACTION_MINUTES = int(os.getenv("NUDGE_REACTION_MINUTES", "3"))
NUDGE_FIRST_MINUTES = int(
    os.getenv("NUDGE_FIRST_MINUTES", str(max(NUDGE_HOT_MINUTES, NUDGE_COLD_MINUTES)))
)
NUDGE_HOT_SECOND_MINUTES = int(os.getenv("NUDGE_HOT_SECOND_MINUTES", "18"))
NUDGE_COLD_SECOND_MINUTES = int(os.getenv("NUDGE_SECOND_MINUTES", "45"))
NUDGE_SECOND_MINUTES = NUDGE_COLD_SECOND_MINUTES  # legacy alias
if os.getenv("NUDGE_FIRST_MINUTES") and not os.getenv("NUDGE_COLD_MINUTES"):
    NUDGE_COLD_MINUTES = int(os.getenv("NUDGE_FIRST_MINUTES", "12"))

GOODMORNING_AFTER_HOURS = int(os.getenv("GOODMORNING_AFTER_HOURS", "14"))
GOODMORNING_HOUR_START = int(os.getenv("GOODMORNING_HOUR_START", "8"))
GOODMORNING_HOUR_END = int(os.getenv("GOODMORNING_HOUR_END", "13"))
MAX_NUDGES_PER_EPISODE = int(os.getenv("MAX_NUDGES_PER_EPISODE", "2"))
VICTIM_AFTER_SEEN_MINUTES = int(os.getenv("VICTIM_AFTER_SEEN_MINUTES", "60"))
VICTIM_COOLDOWN_HOURS = int(os.getenv("VICTIM_COOLDOWN_HOURS", "12"))


def _ended_with_farewell(
    messages: List[dict],
    fan_uuid: str,
    creator_uuid: str,
    mem: dict,
) -> bool:
    return conversation_closed(messages, fan_uuid, creator_uuid, mem)


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
# Keep angles DISTINCT (not all "me dejaste en visto"). WhatsApp-short.
# ---------------------------------------------------------------------------
_TEMPLATES: Dict[str, Dict[str, List[str]]] = {
    "unfinished_thread": {
        "es": [
            "oye y eso? te callaste a la mitad jaja",
            "espera que no terminamos eso",
            "volvé un toque, me quedé a medias",
            "jaj ok seguimos o lo dejamos ahí?",
            "a ver, respondeme eso nomás",
            "te perdí justo en lo bueno, dale",
        ],
        "en": [
            "wait what — you went quiet mid-sentence lol",
            "hold up we didn't finish that",
            "come back a sec, I was mid-thought",
            "ok so are we still on that or what",
            "just answer that one thing",
            "lost you right at the good part, c'mon",
        ],
    },
    "soft_checkin": {
        "es": [
            "eh todo bien?",
            "seguís ahí o te fumaste jaja",
            "hola? solo un hola cuenta",
            "che, apareciste?",
            "estás ocupado o me invento una historia",
            "oye, ¿sigues por acá?",
        ],
        "en": [
            "hey you good?",
            "still there or did you vanish lol",
            "hello? even a hi counts",
            "yo, you around?",
            "busy or should I invent a story",
            "hey, still here?",
        ],
    },
    "playful_brat": {
        "es": [
            "ok misterio, dale un signo de vida",
            "jaj qué silencio más raro eh",
            "no seas así, un mensajito",
            "te estoy mirando el chat como tonta",
            "mmm… te portás mal a veces",
            "bueno ya, aparecé un segundo",
        ],
        "en": [
            "ok mystery man, give me a sign",
            "lol this silence is weird",
            "don't be like that, one little text",
            "I'm staring at the chat like an idiot",
            "mmm… you're being naughty",
            "alright come back for a sec",
        ],
    },
    "almost_sent": {
        "es": [
            "iba a mandarte algo y me trabé jaja",
            "tengo una cosa en la cabeza y no sé si decírtela",
            "casi te mando una foto… casi",
            "estaba eligiendo algo para ti y me distraje",
            "umm tengo un secreto tonto, ¿lo quieres?",
            "pensé en mandarte algo y después dije nah",
        ],
        "en": [
            "was about to send you something and froze lol",
            "got something on my mind not sure if I should say",
            "almost sent you a pic… almost",
            "was picking something for you and got distracted",
            "umm tiny secret, want it?",
            "thought about sending something then said nah",
        ],
    },
    "share_moment": {
        "es": [
            "acabo de hacer café y pensé en ti random",
            "estoy aburrida, entreténeme un toque",
            "mira, me pasó algo tonto hoy",
            "estaba en la cama y me acordé de vos",
            "jaja estoy viendo una serie malísima, qué hacés",
            "tengo sueño pero no quiero dormir sola en el chat",
        ],
        "en": [
            "just made coffee and thought of you random",
            "I'm bored, entertain me a sec",
            "ok something dumb happened today",
            "was in bed and you popped into my head",
            "lol watching a terrible show, what you doing",
            "sleepy but don't wanna sleep alone in this chat",
        ],
    },
    "curious_hook": {
        "es": [
            "pregunta rápida: qué estás haciendo ahora?",
            "a ver una cosa… preferís dulce o salado jaja",
            "ok dime la verdad, estás en el cel y me ignorás?",
            "si pudieras estar acá ahora, qué harías",
            "contame algo random de tu día",
            "una sola pregunta y te dejo en paz… o no",
        ],
        "en": [
            "quick q: what are you doing rn?",
            "ok one thing… sweet or salty lol",
            "be honest, phone in hand and ignoring me?",
            "if you were here right now what would you do",
            "tell me one random thing about your day",
            "one question then I'll leave you alone… or not",
        ],
    },
    "flirty_tease": {
        "es": [
            "estaba pensando una cosa mala y te callaste jaja",
            "ojo que me pongo creativa cuando me dejan sola",
            "tú te perdés y yo me pongo peor 😏",
            "bueno… me estoy imaginando cosas, culpa tuya",
            "si volvés te cuento lo que estaba pensando",
            "no digas nada serio, solo vení a jugar un toque",
        ],
        "en": [
            "was thinking something bad and you went quiet lol",
            "careful I get creative when left alone",
            "you disappear and I get worse 😏",
            "ok… imagining things, your fault",
            "come back and I'll tell you what I was thinking",
            "nothing serious, just come play a bit",
        ],
    },
    "busy_withdrawal": {
        "es": [
            "bueno me voy un rato, escribime cuando puedas",
            "ok me pierdo un toque, no tardes mucho",
            "me voy a hacer cosas, después hablamos",
            "te dejo, pero avisame cuando vuelvas",
            "chau por ahora… o no del todo 😏",
            "me voy que si no me quedo mirando el chat",
        ],
        "en": [
            "ok stepping away a bit, text when you can",
            "gonna disappear a sec, don't take forever",
            "going to do stuff, talk later",
            "leaving you but ping me when you're back",
            "bye for now… or not really 😏",
            "heading out before I just stare at the chat",
        ],
    },
    "victim_soft": {
        "es": [
            "lo viste y nada… ok jaja raro",
            "umm leíste y silencio, qué pasó",
            "visto y paz? qué fuerte",
            "pensé que ibas a decir algo…",
        ],
        "en": [
            "you saw it and nothing… ok lol weird",
            "umm you read it and silence, what happened",
            "read and peace? damn",
            "thought you were gonna say something…",
        ],
    },
    "goodmorning": {
        "es": [
            "buenas… dormiste?",
            "ey buenos días, pensé en ti recién",
            "morning jaja qué tal la noche",
            "desperté y el chat eras tú, típico",
            "hola, café y tú en la cabeza",
            "buenas babe, apareces hoy o qué",
        ],
        "en": [
            "morning… sleep ok?",
            "hey good morning, just thought of you",
            "morning lol how was the night",
            "woke up and the chat was you, classic",
            "hi, coffee and you on my mind",
            "morning babe, you showing up today or what",
        ],
    },
}

# Guilt / "en visto" vibes — rotate away from these if used recently.
_GUILT_MARKERS = re.compile(
    r"(?i)(en visto|left me on read|me dejaste|qué malo|ghost|desaparec|"
    r"te fuiste|vanished|ignor)"
)


def _recent_nudge_texts(mem: dict) -> List[str]:
    raw = mem.get("last_nudge_texts")
    if isinstance(raw, list):
        return [str(x) for x in raw if x][-8:]
    last = (mem.get("last_nudge_text") or "").strip()
    return [last] if last else []


def _remember_nudge_text(fan_uuid: str, fan_handle: str, text: str) -> None:
    mem = fan_memory.get(fan_uuid) or {}
    recent = _recent_nudge_texts(mem)
    recent.append(text)
    recent = recent[-8:]
    try:
        fan_memory.patch_fanvue_platform(
            fan_uuid,
            {"last_nudge_text": text, "last_nudge_texts": recent},
            fan_handle=fan_handle,
        )
    except Exception:
        pass


def _pick_nudge_template(style: str, want_spanish: bool, mem: dict) -> str:
    """Pick a template line, avoiding recent texts and guilt repeats."""
    from config import config

    if getattr(config, "ENGLISH_ONLY", True):
        want_spanish = False
    pool = _TEMPLATES.get(style, _TEMPLATES["soft_checkin"])
    lines = list(pool["es"] if want_spanish else pool["en"])
    recent = set(_recent_nudge_texts(mem))
    recent_guilt = any(_GUILT_MARKERS.search(t) for t in recent)

    def _ok(line: str) -> bool:
        if line in recent:
            return False
        if recent_guilt and _GUILT_MARKERS.search(line):
            return False
        return True

    choices = [l for l in lines if _ok(l)]
    if not choices:
        choices = [l for l in lines if l not in recent] or lines
    return random.choice(choices)


# Keep angle metadata for step/weight routing (no trigger string needed).
NUDGE_ANGLES: Dict[str, dict] = {
    "unfinished_thread": {"steps": (1,), "weight": 2},
    "soft_checkin": {"steps": (1, 2), "weight": 3},
    "playful_brat": {"steps": (1,), "weight": 2},
    "almost_sent": {"steps": (1, 2), "weight": 2},
    "share_moment": {"steps": (1, 2), "weight": 3},
    "curious_hook": {"steps": (1, 2), "weight": 3},
    "flirty_tease": {"steps": (1,), "weight": 2},
    "busy_withdrawal": {"steps": (2,), "weight": 3},
    "victim_soft": {"steps": (2,), "weight": 1},  # rare; only when visto window
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


def _parse_iso(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except ValueError:
        return None


def _chat_is_hot(messages: List[dict], fan_uuid: str, mem: dict) -> bool:
    """Legacy bool — prefer chat_heat_score() for timing."""
    return is_hot_score(chat_heat_score(messages, fan_uuid, mem))


def _fan_active_recently(
    messages: List[dict],
    fan_uuid: str,
    *,
    minutes: Optional[int] = None,
    heat_score: int = 0,
) -> bool:
    """True if the fan sent anything in the last N minutes (even if Emma replied after)."""
    window = minutes if minutes is not None else active_window_minutes(heat_score)
    now = datetime.now(timezone.utc)
    for msg in messages[:14]:
        if _sender_uuid(msg) != fan_uuid:
            continue
        ts = _msg_ts(msg)
        if ts and now - ts < timedelta(minutes=window):
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
    heat_score: int = 0,
) -> str:
    """
    Pick a re-engagement angle for this step.
    Avoid the last 2 styles; victim_soft only when victim_ok (visto ≤1h).
    """
    last = (mem.get("last_nudge_style") or "").strip()
    recent_styles = mem.get("last_nudge_styles")
    avoid: set = set()
    if isinstance(recent_styles, list):
        avoid.update(str(s) for s in recent_styles[-2:] if s)
    elif last:
        avoid.add(last)
    candidates: List[Tuple[str, int]] = []
    for name, meta in NUDGE_ANGLES.items():
        if step not in meta["steps"]:
            continue
        if name == "victim_soft" and not victim_ok:
            continue
        if name in avoid:
            continue
        w = int(meta.get("weight") or 1)
        if is_hot_score(heat_score) and name in ("flirty_tease", "almost_sent", "unfinished_thread"):
            w += 2
        candidates.append((name, w))
    if not candidates:
        for name, meta in NUDGE_ANGLES.items():
            if step in meta["steps"] and name != "victim_soft":
                candidates.append((name, 1))
    if not candidates:
        return "soft_checkin"
    names, weights = zip(*candidates)
    return random.choices(list(names), weights=list(weights), k=1)[0]


def _nudge_step_for_silence(
    silence: timedelta,
    mem: dict,
    *,
    heat_score: int,
    is_read: bool,
    now: datetime,
) -> Optional[int]:
    """
    step 1 — hot+visto uses NUDGE_HOT_SEEN_MINUTES from visto clock.
    step 2 — shorter second gate when heat_score is high.
    """
    count = int(mem.get("nudge_episode_count") or 0)
    if count >= MAX_NUDGES_PER_EPISODE:
        return None

    silence_mins = silence.total_seconds() / 60.0
    seen_mins: Optional[float] = None
    seen_at = _parse_iso(mem.get("last_seen_by_fan_at"))
    if is_read and seen_at:
        seen_mins = (now - seen_at).total_seconds() / 60.0

    react_at = _parse_iso(mem.get("last_fan_reaction_at"))
    if react_at and count == 0:
        react_mins = (now - react_at).total_seconds() / 60.0
        if react_mins >= NUDGE_REACTION_MINUTES and silence_mins >= 2:
            return 1

    if count == 0:
        if is_hot_score(heat_score) and is_read and seen_mins is not None:
            if seen_mins >= NUDGE_HOT_SEEN_MINUTES and silence_mins >= 3:
                return 1
        if is_hot_score(heat_score) and silence_mins >= NUDGE_HOT_MINUTES:
            return 1
        if is_warm_score(heat_score) and is_read and seen_mins is not None:
            if seen_mins >= NUDGE_WARM_SEEN_MINUTES and silence_mins >= 4:
                return 1
        if silence_mins >= NUDGE_COLD_MINUTES:
            return 1
        return None

    if count == 1:
        second = (
            NUDGE_HOT_SECOND_MINUTES
            if is_hot_score(heat_score)
            else NUDGE_COLD_SECOND_MINUTES
        )
        if silence_mins >= second:
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
    want_spanish = language.fan_wants_spanish(last_fan or "", mem)

    # Template path — no DeepSeek call needed for nudges
    nudge_style = style or kind
    reply = _pick_nudge_template(nudge_style, want_spanish, mem)
    _remember_nudge_text(fan_uuid, fan_handle, reply)
    # Rolling style history so we don't loop the same 1–2 angles
    try:
        styles = mem.get("last_nudge_styles")
        if not isinstance(styles, list):
            styles = [mem.get("last_nudge_style")] if mem.get("last_nudge_style") else []
        styles = [str(s) for s in styles if s]
        if nudge_style:
            styles.append(nudge_style)
        fan_memory.patch_fanvue_platform(
            fan_uuid,
            {"last_nudge_styles": styles[-4:]},
            fan_handle=fan_handle,
        )
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

        if int(chat.get("unreadMessagesCount") or 0) > 0:
            continue

        mem = fan_memory.get(fan_uuid)
        if not mem or int(mem.get("messages") or 0) < 1:
            continue

        if reengage_paused(mem):
            print(
                f"   reengage skip @{fan_handle}: paused until fan writes "
                f"({mem.get('reengage_pause_reason') or 'manual'})"
            )
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
        pass_farewell = _ended_with_farewell(messages, fan_uuid, creator_uuid, mem)
        if pass_farewell:
            closed, reason = fan_closed_in_messages(messages, fan_uuid)
            if closed:
                mark_conversation_closed(
                    fan_uuid, fan_handle=fan_handle, reason=reason
                )
        is_read, _ = _creator_last_is_read(messages, creator_uuid)
        if is_read and not mem.get("last_seen_by_fan_at"):
            fan_memory.mark_seen_by_fan(fan_uuid, fan_handle=fan_handle)
            mem = fan_memory.get(fan_uuid) or mem

        heat_score = chat_heat_score(
            messages,
            fan_uuid,
            mem,
            creator_uuid=creator_uuid,
            is_read=is_read,
        )
        try:
            fan_memory.set_chat_heat_score(fan_uuid, heat_score, fan_handle=fan_handle)
        except Exception:
            pass

        if _fan_active_recently(messages, fan_uuid, heat_score=heat_score):
            continue

        hot = is_hot_score(heat_score)

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
            print(
                f"   reengage skip @{fan_handle}: conversation closed "
                f"({mem.get('conversation_closed_reason') or 'farewell'})"
            )
            continue  # closed politely — don't mid-flow guilt

        step = _nudge_step_for_silence(
            silence, mem, heat_score=heat_score, is_read=is_read, now=now
        )
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
        style = pick_nudge_angle(
            mem, step, now, victim_ok=victim_ok, heat_score=heat_score
        )
        label = heat_label(heat_score)
        print(
            f"   reengage @{fan_handle}: step={step} angle={style} "
            f"heat={label}({heat_score}) visto={is_read} "
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
