"""
Layered prompt assembly with HARD budgets.

Order (context before rules — models weight the start hard):
  1. CONTEXT FIRST — read card + chat, then answer as that thread
  2. CLIENT CARD — durable facts about him
  3. CORE — who Emma is + hard bans
  4. TURN — only what this turn needs (lang, offer, vision, delivery)
  5. HISTORY — recent chat turns (appended by reply_engine)
  6. AUTHOR — short steer on the last user turn

Soft lessons / fat sales essays / lore floods are FORBIDDEN in live path.
"""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from core.prompt_core import EMMA_CORE_PROMPT

# Hard ceilings (chars). If exceeded, truncate with a marker — never silently grow.
# Simple mode folds tactics + sell priority into CORE — needs more room.
BUDGET_CORE = 5600
BUDGET_CARD = 2500
BUDGET_TURN_SYSTEM = 4200  # pack + manipulation banner need room
BUDGET_AUTHOR = 650

_CONTEXT_FIRST = (
    "CONTEXT FIRST (do this before writing):\n"
    "1) Read the CLIENT CARD — who he is, spend, facts, language, what you already sent.\n"
    "2) Read the full CHAT HISTORY below — what you two just said; newest message is last.\n"
    "3) Answer as a continuation of THAT specific man and thread.\n"
    "The persona / turn rules that follow are HOW you speak — they do NOT replace the card "
    "or the chat. Never invent memories, names, purchases, or photo details that are not "
    "in the card or recent history. If the card is thin, stay with the chat only."
)


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
    core_prompt: Optional[str] = None,
) -> Tuple[List[Dict[str, str]], Dict[str, int]]:
    """
    Returns (messages, sizes) for the system prefix before history.
    `core_prompt` overrides the default CORE (e.g. the self-contained SIMPLE core).
    """
    turn_blocks = [b for b in (turn_blocks or []) if (b or "").strip()]
    core = _clip(core_prompt or EMMA_CORE_PROMPT, BUDGET_CORE, "CORE")
    card = _clip(card_block, BUDGET_CARD, "CARD") if card_block else ""

    ephemeral_parts: List[str] = []
    for b in (language_block, time_block, name_block, *turn_blocks):
        if b and b.strip():
            ephemeral_parts.append(b.strip())
    ephemeral = _clip("\n\n".join(ephemeral_parts), BUDGET_TURN_SYSTEM, "TURN")

    # Card before CORE so durable facts are not buried under the persona wall.
    messages: List[Dict[str, str]] = [
        {"role": "system", "content": _CONTEXT_FIRST},
    ]
    if card:
        messages.append({"role": "system", "content": card})
    else:
        messages.append(
            {
                "role": "system",
                "content": (
                    "CLIENT CARD: (empty / new fan — rely only on CHAT HISTORY; "
                    "do not invent a backstory.)"
                ),
            }
        )
    messages.append({"role": "system", "content": core})
    if ephemeral:
        messages.append({"role": "system", "content": ephemeral})

    sizes = {
        "core": len(core),
        "card": len(card),
        "turn": len(ephemeral),
        "system_total": len(_CONTEXT_FIRST) + len(card) + len(core) + len(ephemeral),
    }
    return messages, sizes


def clip_author(note: str) -> str:
    return _clip(note, BUDGET_AUTHOR, "AUTHOR")
