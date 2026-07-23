"""
Daily life state — Emma has a day, and it's the SAME day for every fan.

Why: "always available, nothing ever happens to her" is a top bot tell.
This generates one coherent day per (account, LA-date): a plan by time slot,
a mood, and 1-2 micro-events. Deterministic via seeded RNG → no storage, no
migrations: every process asking about today gets the identical day.

Deliberately excluded from all pools: crises, emergencies, money troubles,
health scares. Her day adds texture and consistency — it is never a lever.
"""
from __future__ import annotations

import hashlib
import random
from datetime import datetime
from typing import Optional

from core.persona_time import la_now

_MORNING = [
    "slow morning, coffee in bed scrolling",
    "early gym session (legs day)",
    "gym then a smoothie she's proud of",
    "slept in, woke up late and cozy",
    "errands / groceries run",
    "tidying the apartment with music on",
]
_AFTERNOON = [
    "shooting content for her page",
    "editing / picking photos from a shoot",
    "lunch out with her roommate",
    "beach walk, golden light",
    "lazy afternoon, series marathon",
    "trying to cook a new recipe (chaotically)",
    "shopping, found nothing she liked",
]
_EVENING = [
    "night in: skincare, series, phone",
    "dinner with her roommate",
    "wine + music, chill mood",
    "planning tomorrow's shoot outfits",
    "long bath, phone propped on the sink",
    "out for drinks with a girlfriend (replying between rounds)",
]
_MOODS = [
    "playful and energetic",
    "soft / cuddly mood",
    "a little lazy and cozy",
    "bratty, wants attention",
    "good mood, gym endorphins",
    "slightly bored → extra chatty",
    "tired but affectionate",
]
_MICRO_EVENTS = [
    "her roommate borrowed her charger and lost it (mock outrage)",
    "she nailed a new gym PR and is smug about it",
    "the coffee place got her order wrong",
    "she found the perfect bikini for the next shoot",
    "her series dropped a wild episode, mild obsession",
    "it rained right when she wanted the beach",
    "she burned the first pancake, ate it anyway",
    "a song is stuck in her head all day",
    "she reorganized her closet and feels powerful",
    "neighbor's dog adopted her for ten minutes",
]


def _rng(account_id: str, day: str) -> random.Random:
    seed = int(hashlib.sha256(f"day:{account_id}:{day}".encode()).hexdigest()[:12], 16)
    return random.Random(seed)


def get_day(account_id: str = "emma", now: Optional[datetime] = None) -> dict:
    now = now or la_now()
    day = now.strftime("%Y-%m-%d")
    r = _rng(account_id, day)
    return {
        "date": day,
        "morning": r.choice(_MORNING),
        "afternoon": r.choice(_AFTERNOON),
        "evening": r.choice(_EVENING),
        "mood": r.choice(_MOODS),
        "events": r.sample(_MICRO_EVENTS, k=2),
    }


def current_slot(hour: int) -> str:
    if 5 <= hour < 12:
        return "morning"
    if 12 <= hour < 18:
        return "afternoon"
    return "evening"


def turn_block(account_id: str = "emma", now: Optional[datetime] = None) -> str:
    """ONE line for the TURN section. Facts she can draw on — never a script."""
    now = now or la_now()
    d = get_day(account_id, now)
    slot = current_slot(now.hour)
    return (
        f"HER DAY TODAY (real, keep consistent with every fan): "
        f"now: {d[slot]}. mood: {d['mood']}. "
        f"small things that happened: {d['events'][0]}; {d['events'][1]}. "
        f"Mention naturally ONLY if it fits the flow — never dump the list."
    )


if __name__ == "__main__":
    for aid in ("emma", "sophia"):
        d1 = get_day(aid)
        d2 = get_day(aid)
        assert d1 == d2, f"{aid}: unstable intraday"
        print(f"{aid} {d1['date']}: {d1[current_slot(la_now().hour)]} | {d1['mood']}")
