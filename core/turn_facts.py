"""
TurnFacts — boolean + API facts for one fan message.

Hard facts come from code/API. Soft intents from regex (and optional JSON).
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Optional


@dataclass
class TurnFacts:
    # Hard / API
    free_in_chat: Optional[bool] = None
    ppv_unpaid: bool = False
    cooloff_active: bool = False
    chill_window: bool = False
    recent_purchase: bool = False
    recent_reject: bool = False
    fan_sent_media: bool = False

    # Soft intents (regex / classifier)
    ask_free: bool = False
    missing_delivery: bool = False
    missing_free: bool = False
    buying: bool = False
    want_another: bool = False
    horny: bool = False
    smalltalk: bool = False
    pushback_billing: bool = False
    heated: bool = False

    # Memory snapshot
    msgs: int = 0
    frees_done: int = 0
    status: str = "new"
    spent: float = 0.0

    # Meta
    hard_pack: Optional[str] = None  # if hard gate locked a pack
    soft_source: str = "none"  # none | regex | json
    ambiguous: bool = False

    def to_log(self) -> Dict[str, Any]:
        return asdict(self)

    def facts_line(self) -> str:
        bits = []
        if self.free_in_chat is True:
            bits.append("free_in_chat=YES")
        elif self.free_in_chat is False:
            bits.append("free_in_chat=NO")
        if self.ppv_unpaid:
            bits.append("ppv_unpaid=YES")
        if self.cooloff_active:
            bits.append("cooloff=YES")
        if self.fan_sent_media:
            bits.append("fan_sent_media=YES")
        if self.frees_done:
            bits.append(f"frees_done={self.frees_done}")
        return "; ".join(bits) if bits else "none"
