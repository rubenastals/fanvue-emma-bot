"""
Layered prompt assembly with HARD budgets.

Priority (never inverted):
  1. CORE (immutable) — who Emma is + hard bans
  2. CLIENT CARD — durable facts about him
  3. HISTORY — recent chat turns
  4. TURN — only what this turn needs (lang, offer, vision, delivery)
  5. AUTHOR — one short steer line

Soft lessons / fat sales essays / lore floods are FORBIDDEN in live path.
"""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from core.prompt_core import EMMA_CORE_PROMPT

# Hard ceilings (chars). If exceeded, truncate with a marker — never silently grow.
BUDGET_CORE = 2800
BUDGET_CARD = 2500
BUDGET_TURN_SYSTEM = 3500  # all ephemeral system blocks combined
BUDGET_AUTHOR = 400


def _clip(text: str, budget: int, label: str) -> str:
    t = (text or "").strip()
    if len(t) <= budget:
        return t
    return t[: max(0, budget - 40)].rstrip() + f"\n…[{label} truncated]"


def build_system_layers(
    *,
    card_block: str = "",
    language_block: str = "",
    time_block: str = "",
    name_block: str = "",
    turn_blocks: Optional[List[str]] = None,
) -> Tuple[List[Dict[str, str]], Dict[str, int]]:
    """
    Returns (messages, sizes) for the system prefix before history.
    """
    turn_blocks = [b for b in (turn_blocks or []) if (b or "").strip()]
    core = _clip(EMMA_CORE_PROMPT, BUDGET_CORE, "CORE")
    card = _clip(card_block, BUDGET_CARD, "CARD") if card_block else ""

    ephemeral_parts: List[str] = []
    for b in (language_block, time_block, name_block, *turn_blocks):
        if b and b.strip():
            ephemeral_parts.append(b.strip())
    ephemeral = _clip("\n\n".join(ephemeral_parts), BUDGET_TURN_SYSTEM, "TURN")

    messages: List[Dict[str, str]] = [{"role": "system", "content": core}]
    if card:
        messages.append({"role": "system", "content": card})
    if ephemeral:
        messages.append({"role": "system", "content": ephemeral})

    sizes = {
        "core": len(core),
        "card": len(card),
        "turn": len(ephemeral),
        "system_total": len(core) + len(card) + len(ephemeral),
    }
    return messages, sizes


def clip_author(note: str) -> str:
    return _clip(note, BUDGET_AUTHOR, "AUTHOR")
