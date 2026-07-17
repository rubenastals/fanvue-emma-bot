"""
Phase 0 — DeepSeek READS the conversation + client card BEFORE creative reply.

Returns structured JSON:
  - which sales phase / pack we are in
  - what to remember about him (name, likes, avoid)
  - short situation summary

Hard API gates (unpaid PPV, delivery truth) still win over the analyst.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from core import packs

# Packs the analyst may choose (sales phases + common soft)
_ANALYST_PACKS = frozenset(
    {
        "phase_hook",
        "phase_spiral",
        "phase_pull",
        "phase_close",
        "price_objection",
        "reward_purchase",
        "post_sale_withdrawal",
        "phase_reengage",
        "ask_free_first",
        "escalate_paid",
        "tease_heat",
        "rapport",
        "chill",
        "react_fan_media",
        "billing_clarify",
    }
)

# Hard packs — analyst may NOT override these
_HARD_LOCK_PACKS = frozenset(
    {
        "ppv_unpaid",
        "delivery_scroll",
        "delivery_missing",
        "chill",  # chill window / reject cooloff from code
    }
)


@dataclass
class PhaseAnalysis:
    phase: str = ""
    pack_id: str = ""
    name_to_use: str = ""
    likes: List[str] = field(default_factory=list)
    avoid: List[str] = field(default_factory=list)
    summary: str = ""
    technique_hint: str = ""
    raw: Dict[str, Any] = field(default_factory=dict)

    def recall_block(self) -> str:
        """Loud block so creative Emma uses remembered facts."""
        likes = ", ".join(self.likes[:6]) if self.likes else "(none noted)"
        avoid = ", ".join(self.avoid[:5]) if self.avoid else "(none)"
        name = self.name_to_use or "(pet name only — no confirmed name)"
        return (
            "================================================\n"
            "  CLIENT RECALL — READ BEFORE YOU REPLY\n"
            "================================================\n"
            f"Phase diagnosed: {self.phase or '?'} -> pack {self.pack_id or '?'}\n"
            f"His name (use sometimes, not every turn): {name}\n"
            f"Likes / kinks to use: {likes}\n"
            f"Avoid: {avoid}\n"
            f"Conversation so far: {self.summary or '(see history)'}\n"
            "You MUST use these facts. Do not invent a different name or fake history."
        )


def analyze(
    *,
    fan_message: str,
    history_turns: List[Dict[str, str]],
    card_text: str,
    hard_pack: Optional[str] = None,
    code_pack: Optional[str] = None,
) -> Optional[PhaseAnalysis]:
    """
    DeepSeek analyst call. Returns None if disabled / failed.
    """
    from config import config
    from openai import OpenAI

    if not getattr(config, "PHASE_ANALYST", True):
        return None
    if not config.DEEPSEEK_API_KEY:
        return None

    # Build readable transcript (chronological)
    lines: List[str] = []
    for t in (history_turns or [])[-40:]:
        role = "FAN" if t.get("role") == "user" else "EMMA"
        content = (t.get("content") or "").strip()
        if not content:
            continue
        # Strip author notes from last user turn for cleaner read
        content = re.sub(r"\n\n\[Emma texting\.[\s\S]*$", "", content)
        lines.append(f"{role}: {content[:400]}")
    transcript = "\n".join(lines) if lines else f"FAN: {(fan_message or '')[:400]}"

    pack_list = ", ".join(sorted(_ANALYST_PACKS))
    hard_note = ""
    if hard_pack:
        hard_note = (
            f"\nHARD LOCK from system (do NOT change pack): {hard_pack}. "
            "Still fill name/likes/summary from card+chat."
        )

    sys = (
        "You are the PHASE ANALYST for Emma's Fanvue DM bot. "
        "You do NOT write Emma's reply. "
        "Read the FULL conversation and CLIENT CARD, then output ONLY compact JSON."
    )
    user = (
        f"CLIENT CARD:\n{(card_text or '(empty)')[:2000]}\n\n"
        f"FULL RECENT CONVERSATION:\n{transcript[-6000:]}\n\n"
        f"LATEST FAN MESSAGE:\n{(fan_message or '')[:500]}\n"
        f"{hard_note}\n\n"
        "Decide which sales PHASE we are in:\n"
        "1 hook | 2 spiral | 3 pull | 4 close | 5 price_objection | "
        "6 reward_purchase | 7 post_sale_withdrawal | 8 reengage | "
        "or special: ask_free / escalate / react_media / billing\n\n"
        "Return JSON keys:\n"
        "{\n"
        '  "phase": "hook|spiral|pull|close|price_objection|reward|withdrawal|reengage|...",\n'
        f'  "pack_id": one of [{pack_list}],\n'
        '  "name_to_use": "confirmed first name or empty",\n'
        '  "likes": ["..."],\n'
        '  "avoid": ["..."],\n'
        '  "summary": "1-2 sentences of where the chat is emotionally/sales-wise",\n'
        '  "technique_hint": "optional: love_bombing|guilt|fomo|ego|withdrawal|future_fake|..."\n'
        "}\n"
        f"Code router suggested pack={code_pack or 'none'} — override only if conversation clearly disagrees."
    )

    client = OpenAI(
        api_key=config.DEEPSEEK_API_KEY,
        base_url=config.DEEPSEEK_BASE_URL,
    )
    model = getattr(config, "PHASE_ANALYST_MODEL", None) or config.DEEPSEEK_MODEL
    kwargs: Dict[str, Any] = dict(
        model=model,
        messages=[
            {"role": "system", "content": sys},
            {"role": "user", "content": user},
        ],
        temperature=0,
        max_tokens=280,
    )
    if getattr(config, "DEEPSEEK_DISABLE_THINKING", False):
        kwargs["extra_body"] = {"thinking": {"type": "disabled"}}

    try:
        resp = client.chat.completions.create(**kwargs)
        raw = (resp.choices[0].message.content or "").strip()
    except Exception as e:
        print(f"   phase-analyst failed: {type(e).__name__}: {e}")
        return None

    data = _parse_json(raw)
    if not data:
        print("   phase-analyst: bad JSON")
        return None

    pack_id = str(data.get("pack_id") or "").strip()
    if hard_pack:
        pack_id = hard_pack
    elif pack_id not in _ANALYST_PACKS:
        pack_id = code_pack or packs.fallback_pack()

    likes = data.get("likes") or []
    avoid = data.get("avoid") or []
    if not isinstance(likes, list):
        likes = [str(likes)]
    if not isinstance(avoid, list):
        avoid = [str(avoid)]

    return PhaseAnalysis(
        phase=str(data.get("phase") or "").strip(),
        pack_id=pack_id,
        name_to_use=str(data.get("name_to_use") or "").strip(),
        likes=[str(x)[:40] for x in likes[:8]],
        avoid=[str(x)[:40] for x in avoid[:6]],
        summary=str(data.get("summary") or "").strip()[:280],
        technique_hint=str(data.get("technique_hint") or "").strip()[:60],
        raw=data,
    )


def _parse_json(raw: str) -> Optional[Dict[str, Any]]:
    if not raw:
        return None
    m = re.search(r"\{[\s\S]*\}", raw.strip())
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def apply_technique_hint(pack_id: str, hint: str) -> Optional[str]:
    """
    Map analyst technique_hint to a technique name used by manipulation.py catalogs.
    Returns technique name to force, or None to keep rotating picker.
    """
    h = (hint or "").lower().replace("-", "_").replace(" ", "_")
    if not h:
        return None
    table = {
        "love_bombing": "LOVE BOMBING",
        "love_bomb": "LOVE BOMBING",
        "withdrawal": "LOVE BOMBING + WITHDRAWAL",
        "love_bombing_withdrawal": "LOVE BOMBING + WITHDRAWAL",
        "intermittent": "INTERMITTENT REINFORCEMENT",
        "intermittent_reinforcement": "INTERMITTENT REINFORCEMENT",
        "guilt": "GUILT TRIP + RECIPROCITY",
        "guilt_trip": "GUILT TRIP + RECIPROCITY",
        "fomo": "SCARCITY + FOMO",
        "scarcity": "SCARCITY + FOMO",
        "scarcity_fomo": "SCARCITY + FOMO",
        "ego": "EGO CHALLENGE",
        "ego_challenge": "EGO CHALLENGE",
        "gaslight": "GASLIGHTING (soft)",
        "gaslighting": "GASLIGHTING (soft)",
        "future_fake": "FUTURE FAKING",
        "future_faking": "FUTURE FAKING",
    }
    # For pull pack, match catalog names
    if pack_id == "phase_pull":
        for key, name in table.items():
            if key in h or h in key:
                return name
        if "bomb" in h and "with" in h:
            return "LOVE BOMBING + WITHDRAWAL"
    if pack_id == "phase_close" and ("fomo" in h or "scarcity" in h or "close" in h):
        return "SCARCITY + FOMO (CLOSE)"
    if pack_id == "phase_hook":
        return "LOVE BOMBING"
    return table.get(h)
