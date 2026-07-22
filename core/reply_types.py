"""Shared types for reply assemble → generate → sanitize (audit R4)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from core.turn_policy import TurnDecision


@dataclass
class AssembledTurn:
    """Output of assemble_emma_turn — everything post-draft belts need."""

    messages: List[Dict[str, str]]
    decision: TurnDecision
    pack_id: str
    tech_name: str
    phase_name: str
    want_spanish: bool
    fan_uuid: Optional[str]
    fan_handle: str
    fan_message: str
    usable_name: str
    name_confirmed: bool
    name_max_uses: int
    turns: List[Dict[str, str]]
    offer: Optional[dict]
    ppv_status: Optional[dict]
    delivery_truth: Optional[dict]
    voice_will_send: bool
    lock_active: Optional[bool]
    no_lock: bool
    status_active: bool
    unpaid_gate: bool
    never_bought: bool
    fan_saw_bluff: bool
    ghost_free_ban: bool
    turn_action: Any = None
