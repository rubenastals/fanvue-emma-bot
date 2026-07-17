"""
Deterministic scheme compliance checks (no DeepSeek).

Catches hard NEVER violations after the creative reply — cheap, always-on.
DeepSeek critic (SCHEME rule) judges softer pack/technique fit.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional


# Claims an unpaid lock is waiting / he should unlock
_CLAIM_LOCK_WAITING = re.compile(
    r"(?i)\b("
    r"candado|unlock|desbloque|sigue (ah[ií]|esperando)|"
    r"est[aá] esperando|check (the )?lock|el lock|"
    r"foto bloquead|locked (photo|pic)|"
    r"abre(lo|la)?\b.{0,20}(candado|lock|foto)"
    r")\b"
)

# Claims media was sent / in inbox
_CLAIM_SENT = re.compile(
    r"(?i)\b("
    r"te (lo |la )?(envi[eé]|mand[eé]|regal[eé]|pas[eé])|"
    r"(i |just )?(sent|gifted|dropped)|"
    r"(en|in) (tu |your )?(bandeja|inbox|chat)"
    r")\b"
)

_BANNED_NICK = re.compile(r"(?i)\b(caro|papi|nena|nene)\b")
_FAKE_TRANSMIT = re.compile(r"\[(?:Transmite|envi[oó]|you can send|You locked)", re.I)
_INVENTED_GLITCH = re.compile(
    r"(?i)\b(app (ate|comi[oó]|block)|glitch|refresca (la )?app|"
    r"se (me )?(bloque[oó]|trab[oó])|photo is blocked)\b"
)


def check_reply(
    reply: str,
    *,
    pack_id: str = "",
    lock_active: Optional[bool] = None,
    media_attached: bool = False,
    technique: str = "",
) -> List[Dict[str, Any]]:
    """
    Return list of {rule, severity, what}. Empty = looks compliant on hard rails.
    """
    text = (reply or "").strip()
    if not text:
        return [{"rule": "SCHEME", "severity": 2, "what": "empty reply"}]

    errs: List[Dict[str, Any]] = []
    pid = (pack_id or "").strip()

    if _BANNED_NICK.search(text):
        errs.append(
            {
                "rule": "SCHEME",
                "severity": 3,
                "what": "banned nickname caro/papi/nena/nene",
            }
        )
    if _FAKE_TRANSMIT.search(text):
        errs.append(
            {
                "rule": "SCHEME",
                "severity": 3,
                "what": "fake Transmit / stage-direction brackets",
            }
        )

    # LOCK STATUS obedience
    if lock_active is False and _CLAIM_LOCK_WAITING.search(text):
        errs.append(
            {
                "rule": "SCHEME",
                "severity": 3,
                "what": "invented waiting candado but LOCK STATUS=none",
            }
        )
    if not media_attached and _CLAIM_SENT.search(text):
        # soft — delivery rewriter may already catch; still flag
        errs.append(
            {
                "rule": "SCHEME",
                "severity": 2,
                "what": "claimed send/gift with no media attached this turn",
            }
        )
    if _INVENTED_GLITCH.search(text) and not media_attached:
        errs.append(
            {
                "rule": "SCHEME",
                "severity": 3,
                "what": "invented app glitch / tech excuse",
            }
        )

    # Pack-specific hard rails
    if pid == "ppv_unpaid" and lock_active is not True:
        errs.append(
            {
                "rule": "SCHEME",
                "severity": 2,
                "what": "pack=ppv_unpaid but lock_active is not true",
            }
        )
    if pid == "reward_purchase" and re.search(
        r"(?i)\b(unlock|desbloque|candado|\$\d|€\d|compra)\b", text
    ):
        errs.append(
            {
                "rule": "SCHEME",
                "severity": 2,
                "what": "reward_purchase pitched another unlock",
            }
        )
    if pid == "billing_clarify" and re.search(
        r"(?i)\b(unlock now|abre(lo)? ya|fomo|otros fans)\b", text
    ):
        errs.append(
            {
                "rule": "SCHEME",
                "severity": 2,
                "what": "billing_clarify still hard-selling / FOMO",
            }
        )
    if pid == "react_fan_media" and re.search(
        r"(?i)\b(unlock|desbloque|\$\d|precio|ppv)\b", text
    ):
        errs.append(
            {
                "rule": "SCHEME",
                "severity": 2,
                "what": "react_fan_media pitched price/PPV",
            }
        )

    # Technique presence is soft — only note if technique set and reply is tiny generic
    if technique and len(text) < 8:
        errs.append(
            {
                "rule": "SCHEME",
                "severity": 1,
                "what": f"technique={technique} but reply too thin to execute it",
            }
        )

    return errs


def summarize(errors: List[Dict[str, Any]]) -> str:
    if not errors:
        return "scheme_ok"
    bits = [f"{e.get('rule')}:{e.get('what', '')[:40]}" for e in errors[:3]]
    return "scheme_fail " + " | ".join(bits)
