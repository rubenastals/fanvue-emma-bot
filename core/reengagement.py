"""
Automatic re-engagement — timed ladder + rotating angles.

TIMING (no farewell / conversation left open):
  1st nudge  ≥ NUDGE_FIRST_MINUTES  (default 15)
  2nd nudge  ≥ NUDGE_SECOND_MINUTES (default 30), only if still silent
  Max 2 mid-flow nudges per silence episode.

If they said goodbye → skip mid-flow nudges; only next-day good morning.

ANGLES rotate — never spam the same "tan poco te importo" victim line.
Victim-soft is allowed at most once per VICTIM_COOLDOWN_HOURS.
"""
from __future__ import annotations

import os
import random
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

from core import convo_log, fan_memory, language, persona_time
from core.reply_engine import (
    fanvue_messages_to_turns,
    generate_emma_reply,
    split_into_messages,
)
from core.turn_policy import TurnDecision

NUDGE_FIRST_MINUTES = int(os.getenv("NUDGE_FIRST_MINUTES", "15"))
NUDGE_SECOND_MINUTES = int(os.getenv("NUDGE_SECOND_MINUTES", "30"))
# Back-compat alias if someone still sets the old env
if os.getenv("NUDGE_AFTER_MINUTES") and not os.getenv("NUDGE_FIRST_MINUTES"):
    NUDGE_FIRST_MINUTES = int(os.getenv("NUDGE_AFTER_MINUTES", "15"))

GOODMORNING_AFTER_HOURS = int(os.getenv("GOODMORNING_AFTER_HOURS", "14"))
GOODMORNING_HOUR_START = int(os.getenv("GOODMORNING_HOUR_START", "8"))
GOODMORNING_HOUR_END = int(os.getenv("GOODMORNING_HOUR_END", "13"))
MAX_NUDGES_PER_EPISODE = int(os.getenv("MAX_NUDGES_PER_EPISODE", "2"))
VICTIM_COOLDOWN_HOURS = int(os.getenv("VICTIM_COOLDOWN_HOURS", "12"))

_FAREWELL = re.compile(
    r"(?i)\b("
    r"good ?night|gn|bye|see (you|ya)|talk (later|soon|tomorrow)|ttyl|gtg|"
    r"going to (bed|sleep)|sleep well|sweet dreams|"
    r"adi[oó]s|buenas noches|hasta (ma[nñ]ana|luego|pronto)|me voy|"
    r"nos vemos|descansa|dulces sue[nñ]os|a dormir"
    r")\b"
)

# Intelligent alternatives — DeepSeek writes the words; we pick the ANGLE.
NUDGE_ANGLES: Dict[str, dict] = {
    "unfinished_thread": {
        "steps": (1,),
        "weight": 3,
        "trigger": (
            "[SYSTEM: He went quiet {minutes}m ago mid-conversation (no goodbye). "
            "ANGLE = unfinished thread. Pick up the last vibe/topic lightly — "
            "curiosity, not accusation. 1–2 short lines. Question at the end. "
            "No selling. No 'you don't care about me'. Do NOT mention this note.]"
        ),
    },
    "soft_checkin": {
        "steps": (1, 2),
        "weight": 2,
        "trigger": (
            "[SYSTEM: He went quiet {minutes}m ago (conversation left open). "
            "ANGLE = soft check-in. Warm, brief: are you okay / still there / "
            "did something come up. Cute, not needy walls. 1–2 lines. No selling. "
            "Do NOT use heavy guilt. Do NOT mention this note.]"
        ),
    },
    "playful_brat": {
        "steps": (1,),
        "weight": 2,
        "trigger": (
            "[SYSTEM: He went quiet {minutes}m ago mid-flow. "
            "ANGLE = playful brat. Light tease that he left you hanging — "
            "smirk energy, not real hurt. 1–2 lines + question. No selling. "
            "Do NOT mention this note.]"
        ),
    },
    "almost_sent": {
        "steps": (1, 2),
        "weight": 2,
        "trigger": (
            "[SYSTEM: He went quiet {minutes}m ago. "
            "ANGLE = intermittent FOMO. You were ABOUT to send/share something "
            "special then noticed he vanished — imply the moment, never claim a "
            "photo already arrived. 1–2 lines. No hard sell / no price. "
            "Do NOT mention this note.]"
        ),
    },
    "busy_withdrawal": {
        "steps": (2,),
        "weight": 3,
        "trigger": (
            "[SYSTEM: Still silent after {minutes}m (2nd touch). "
            "ANGLE = busy withdrawal. Warm but you have to go / someone else / "
            "life — leave an open loop so HE chases. Short. No begging. No selling. "
            "Do NOT mention this note.]"
        ),
    },
    "victim_soft": {
        "steps": (2,),
        "weight": 1,
        "trigger": (
            "[SYSTEM: Still silent after {minutes}m (2nd touch). "
            "ANGLE = soft victim (USE RARELY). Tiny hurt: feel a bit forgotten / "
            "like you don't matter — cute needy, never angry, never essay. "
            "1–2 lines max. No selling. Do NOT mention this note.]"
        ),
    },
}

GOODMORNING_TRIGGER = (
    "[SYSTEM: He never answered and it's now morning in Los Angeles "
    "({hours}h silence). ANGLE = warm morning open. Good morning, thought of him, "
    "missed the chat — fresh and personal to YOUR conversation. 1–2 lines. "
    "Light, no guilt-tripping, no selling. Do NOT mention this note.]"
)


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


def _victim_on_cooldown(mem: dict, now: datetime) -> bool:
    last = _parse_iso(mem.get("last_victim_nudge_at"))
    if not last:
        return False
    return now - last < timedelta(hours=VICTIM_COOLDOWN_HOURS)


def pick_nudge_angle(mem: dict, step: int, now: datetime) -> str:
    """
    Pick a re-engagement angle for this step.
    Avoid last style; restrict victim_soft.
    """
    last = (mem.get("last_nudge_style") or "").strip()
    candidates: List[Tuple[str, int]] = []
    for name, meta in NUDGE_ANGLES.items():
        if step not in meta["steps"]:
            continue
        if name == "victim_soft" and _victim_on_cooldown(mem, now):
            continue
        if name == last and len(NUDGE_ANGLES) > 1:
            continue
        candidates.append((name, int(meta.get("weight") or 1)))
    if not candidates:
        # Fallback if everything filtered
        for name, meta in NUDGE_ANGLES.items():
            if step in meta["steps"] and name != "victim_soft":
                candidates.append((name, 1))
    if not candidates:
        return "soft_checkin"
    names, weights = zip(*candidates)
    return random.choices(list(names), weights=list(weights), k=1)[0]


def _nudge_step_for_silence(silence: timedelta, mem: dict) -> Optional[int]:
    """
    Which ladder step is due now?
    step 1 at ≥15m if episode count 0
    step 2 at ≥30m if episode count 1
    """
    count = int(mem.get("nudge_episode_count") or 0)
    if count >= MAX_NUDGES_PER_EPISODE:
        return None
    mins = silence.total_seconds() / 60.0
    if count == 0 and mins >= NUDGE_FIRST_MINUTES:
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
    turns = fanvue_messages_to_turns(messages, fan_uuid, creator_uuid, max_messages=14)
    mem = fan_memory.get(fan_uuid)
    last_fan = _last_fan_text(messages, fan_uuid)
    want_spanish = language.fan_wants_spanish(last_fan, mem) if last_fan else bool(
        mem.get("prefer_spanish")
    )

    decision = TurnDecision(
        mode="chill",
        reason=f"re-engagement:{kind}:{style or '-'}",
        max_bubbles=2,
        allow_ppv_talk=False,
        allow_price=False,
    )
    try:
        reply, _ = generate_emma_reply(
            trigger,
            history_turns=turns,
            fan_handle=fan_handle,
            fan_uuid=fan_uuid,
            decision=decision,
            want_spanish=want_spanish,
            pack_id="phase_reengage",
        )
    except Exception as e:
        print(f"   ⚠️ {kind} generation failed for @{fan_handle}: {e}")
        return False
    if not reply.strip():
        return False

    bubbles = split_into_messages(reply, max_bubbles=2)
    for i, bubble in enumerate(bubbles):
        try:
            fv.send_typing_indicator(fan_uuid, True)
        except Exception:
            pass
        time.sleep(random.uniform(3.0, 7.0) if i == 0 else random.uniform(2.5, 5.0))
        fv.send_message(fan_uuid, bubble)
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

        # RULE — next-day good morning
        today = persona_time.la_today()
        if (
            silence >= timedelta(hours=GOODMORNING_AFTER_HOURS)
            and mem.get("last_goodmorning_day") != today
            and GOODMORNING_HOUR_START <= local_hour < GOODMORNING_HOUR_END
        ):
            trigger = GOODMORNING_TRIGGER.format(
                hours=int(silence.total_seconds() // 3600)
            )
            if _send_generated(
                fv,
                fan_uuid,
                fan_handle,
                messages,
                creator_uuid,
                trigger,
                "goodmorning",
                style="warm_morning",
            ):
                sent += 1
            continue

        if pass_farewell:
            continue  # closed politely — don't mid-flow guilt

        step = _nudge_step_for_silence(silence, mem)
        if not step:
            continue

        # Don't fire a second nudge too soon after the first send
        last_nudge = _parse_iso(mem.get("last_nudge_at"))
        if last_nudge and now - last_nudge < timedelta(minutes=10):
            continue

        style = pick_nudge_angle(mem, step, now)
        meta = NUDGE_ANGLES[style]
        trigger = meta["trigger"].format(
            minutes=int(silence.total_seconds() // 60)
        )
        print(
            f"   reengage @{fan_handle}: step={step} angle={style} "
            f"silence={int(silence.total_seconds() // 60)}m"
        )
        if _send_generated(
            fv,
            fan_uuid,
            fan_handle,
            messages,
            creator_uuid,
            trigger,
            "nudge",
            style=style,
        ):
            sent += 1

    return sent
