"""Human-ish typing delays scaled by character count."""
from __future__ import annotations

import random


def human_typing_delay(
    text: str,
    *,
    first: bool,
    prev_text: str = "",
) -> float:
    """
    Pause before sending a bubble — think time + typing at ~4–6 chars/sec.
    Longer messages = longer pause (capped so we don't feel frozen).
    """
    n = max(1, len((text or "").strip()))
    chars_per_sec = random.uniform(4.0, 6.0)
    typing = n / chars_per_sec
    think = random.uniform(1.8, 3.2) if first else random.uniform(1.0, 2.2)
    # Reading previous bubble before typing the next
    read_prev = len((prev_text or "").strip()) / 140.0 if not first else 0.0
    delay = think + typing + read_prev
    floor = 4.5 if first else 3.5
    ceiling = 28.0 if first else 20.0
    return min(ceiling, max(floor, delay))
