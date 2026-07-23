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
    Pause before sending a bubble — think time + thumb typing.

    Real DMs: she reads, thinks, then types slowly. Not instant paragraphs.
    Uses BUBBLE_DELAY_* from config as floor; scales up with message length.
    """
    try:
        from config import config

        first_lo = float(getattr(config, "BUBBLE_DELAY_FIRST_MIN", 6.0))
        first_hi = float(getattr(config, "BUBBLE_DELAY_FIRST_MAX", 10.0))
        next_lo = float(getattr(config, "BUBBLE_DELAY_NEXT_MIN", 4.0))
        next_hi = float(getattr(config, "BUBBLE_DELAY_NEXT_MAX", 7.0))
    except Exception:
        first_lo, first_hi, next_lo, next_hi = 6.0, 10.0, 4.0, 7.0

    n = max(1, len((text or "").strip()))
    # ~2–3.5 chars/sec — phone typing, not paste
    chars_per_sec = random.uniform(2.0, 3.5)
    typing = n / chars_per_sec
    think = random.uniform(3.5, 7.0) if first else random.uniform(2.0, 4.5)
    read_prev = len((prev_text or "").strip()) / 100.0 if not first else 0.0

    base = random.uniform(first_lo, first_hi) if first else random.uniform(next_lo, next_hi)
    delay = base + think + typing + read_prev
    floor = first_lo + 2.0 if first else next_lo + 1.0
    ceiling = 50.0 if first else 35.0
    return min(ceiling, max(floor, delay))
