"""
Action-first turn planner.

Code decides WHAT happens this turn (send voice, attach PPV, flirt…).
DeepSeek only writes the text for that action — it does not own protocol.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional


ACTION_FLIRT = "flirt"
ACTION_SEND_VOICE = "send_voice"
ACTION_ATTACH_PPV = "attach_ppv"
ACTION_ATTACH_FREE = "attach_free"
ACTION_COMFORT = "comfort"


@dataclass
class TurnAction:
    action: str
    reason: str
    voice: bool = False
    offer: Optional[Dict[str, Any]] = None

    @property
    def blocks_photo(self) -> bool:
        return self.action == ACTION_SEND_VOICE


def commitment_prompt_line(mem: Optional[dict], *, voice_will_send: bool) -> str:
    """
    One code-truth line for the prompt. Not an essay — protocol lives in code.
    """
    mem = mem or {}
    c = mem.get("open_commitment")
    if not isinstance(c, dict):
        c = None
    ctype = (c or {}).get("type") or ""
    if voice_will_send or ctype == "voice":
        hits = int((c or {}).get("hits") or 0)
        hit_bit = f" (asked/teased x{hits})" if hits else ""
        return (
            "COMMITMENT (code — law this turn):\n"
            f"- type=voice{hit_bit}. System WILL send a voice note after your text "
            "if ACTION=send_voice. HARD BAN: pídemelo / ask me nicely / "
            "'quieres un audio?'. Do not re-open the beg loop."
        )
    return ""
