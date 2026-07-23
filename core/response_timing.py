"""
Response timing — when Emma picks up the phone (layer ABOVE send_timing).

send_timing.py  = thumb-typing delay per bubble (keep as is).
This module     = how long until she even starts replying, sleep windows,
                  and burst sessions ("she's on her phone right now").
"""
from __future__ import annotations

import hashlib
import os
import random
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

from config import config
from core import daily_state
from core.persona_time import la_now

SESSION_WINDOW_MIN = float(os.getenv("RESPONSE_SESSION_WINDOW_MIN", "6"))
SLEEP_START_BASE = float(os.getenv("RESPONSE_SLEEP_START_H", "1.5"))
SLEEP_END_BASE = float(os.getenv("RESPONSE_SLEEP_END_H", "9.0"))
INSOMNIA_PROB = float(os.getenv("RESPONSE_INSOMNIA_PROB", "0.06"))


@dataclass
class TimingPlan:
    delay_seconds: float = 0.0
    hold_until: Optional[datetime] = None
    mode: str = "normal"


def _day_rng(salt: str, day: str) -> random.Random:
    seed = int(hashlib.sha256(f"{salt}:{day}".encode()).hexdigest()[:12], 16)
    return random.Random(seed)


def _sleep_window(now: datetime) -> tuple[datetime, datetime]:
    r = _day_rng("sleep", now.strftime("%Y-%m-%d"))
    start_h = SLEEP_START_BASE + r.uniform(-0.66, 0.66)
    end_h = SLEEP_END_BASE + r.uniform(-0.66, 0.66)
    day0 = now.replace(hour=0, minute=0, second=0, microsecond=0)
    start = day0 + timedelta(hours=start_h)
    end = day0 + timedelta(hours=end_h)
    if now < start - timedelta(hours=12):
        start -= timedelta(days=1)
        end -= timedelta(days=1)
    return start, end


def _heavy_tail(rng: random.Random, median_s: float, cap_s: float) -> float:
    v = rng.lognormvariate(0, 0.9) * median_s
    return min(cap_s, max(8.0, v))


def _daypart_median(hour: int, *, account_id: str = "emma") -> tuple[float, float]:
    if 9 <= hour < 11:
        median, cap = 4 * 60, 25 * 60
    elif 11 <= hour < 17:
        median, cap = 14 * 60, 75 * 60
    elif 17 <= hour < 24:
        median, cap = 5 * 60, 30 * 60
    else:
        median, cap = 20 * 60, 90 * 60

    try:
        d = daily_state.get_day(account_id)
        slot = daily_state.current_slot(hour)
        activity = str(d.get(slot) or "").lower()
        if "shooting" in activity or "out for drinks" in activity:
            median *= 1.8
    except Exception:
        pass
    return median, cap


def plan_reply_timing(
    *,
    last_emma_reply_at: Optional[datetime] = None,
    heat: str = "stable",
    now: Optional[datetime] = None,
    account_id: Optional[str] = None,
) -> TimingPlan:
    now = now or la_now()
    aid = (account_id or getattr(config, "ACCOUNT_ID", None) or "emma").strip().lower()
    rng = random.Random()

    start, end = _sleep_window(now)
    if start <= now < end:
        if rng.random() < INSOMNIA_PROB and (now - start) < timedelta(hours=1.5):
            return TimingPlan(delay_seconds=rng.uniform(60, 8 * 60), mode="normal")
        wake = end + timedelta(minutes=rng.uniform(3, 35))
        return TimingPlan(hold_until=wake, mode="wake")

    if last_emma_reply_at is not None:
        since = (now - last_emma_reply_at).total_seconds() / 60.0
        if since < SESSION_WINDOW_MIN:
            return TimingPlan(delay_seconds=rng.uniform(6, 45), mode="session")

    # Hot thread: never park him behind a 15–30m "slow" gate — sell lives on momentum.
    if heat == "heating":
        return TimingPlan(delay_seconds=rng.uniform(8, 55), mode="session")

    median, cap = _daypart_median(now.hour, account_id=aid)
    if heat == "cooling":
        median *= 1.3
    delay = _heavy_tail(rng, median, cap)
    mode = "slow" if delay > 20 * 60 else "normal"
    return TimingPlan(delay_seconds=delay, mode=mode)


def timing_context_line(plan: TimingPlan, gap_minutes: Optional[float]) -> str:
    if plan.mode == "wake":
        return (
            "TIMING FACT: you just woke up and are answering his overnight message now."
        )
    if gap_minutes and gap_minutes > 45:
        return (
            f"TIMING FACT: you're replying ~{int(gap_minutes)} min after his message — "
            "a quick natural nod to being away is fine (busy / shooting / gym), "
            "never an apology essay."
        )
    return ""


def heat_label_for_timing(
    *,
    fan_message: str,
    turns: list,
    messages: list,
    fan_uuid: Optional[str],
    mem: Optional[dict],
) -> str:
    from core.chat_heat import chat_heat_score, is_hot_score
    from core.reply_assemble import _looks_cooling

    if _looks_cooling(fan_message, turns):
        return "cooling"
    score = chat_heat_score(messages, fan_uuid or "", mem or {})
    if is_hot_score(score):
        return "heating"
    return "stable"
