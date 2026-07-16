"""
Emma's clock — she lives in Los Angeles, her audience is US-based.

Every time reference (morning/night, "I just woke up", good-morning
openers) must follow LA time, NOT the server's local (Spain) time.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

try:
    from zoneinfo import ZoneInfo

    _LA = ZoneInfo("America/Los_Angeles")

    def la_now() -> datetime:
        return datetime.now(_LA)

except Exception:  # tzdata missing — approximate with PDT
    def la_now() -> datetime:
        return datetime.now(timezone.utc) - timedelta(hours=7)


def la_today() -> str:
    return la_now().strftime("%Y-%m-%d")


def _daypart(hour: int) -> str:
    if 5 <= hour < 12:
        return "morning"
    if 12 <= hour < 17:
        return "afternoon"
    if 17 <= hour < 21:
        return "evening"
    return "late night"


def time_system_block() -> str:
    now = la_now()
    return (
        f"YOUR CLOCK (you live in Los Angeles): it's {now.strftime('%A, %I:%M %p')} — "
        f"{_daypart(now.hour)} for you and your mostly-US fans. "
        "Any mention of morning/night/today/tonight must match THIS time, "
        "never another timezone."
    )
