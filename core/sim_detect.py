"""
Offline failure detectors for mass chat simulation.

Cheap, deterministic checks on Emma replies — complements scheme_guard.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from config import config
from core import scheme_guard
from core.reply_sanitize import _EN_LANG_FALLBACKS

# Store / sales-caption energy (banned for PPV) — tight; "just for you" alone is fine
_ROBOTIC_PPV = re.compile(
    r"(?i)("
    r"just\s+for\s+you[….!]?\s*this\s+pic\s+of\s+me|"
    r"unlock\s+it\s+if\s+you\s+really\s+want\s+to\s+see\s+me|"
    r"this\s+photo\s+stays\s+locked|"
    r"i\s+don'?t\s+give\s+myself\s+away\s+to\s+just\s+anyone|"
    r"solo\s+para\s+ti[….!]?\s*esta\s+foto\s+m[ií]a|"
    r"ábrela\s+si\s+de\s+verdad\s+quieres\s+verme"
    r")"
)

_EARLY_GUILT = re.compile(
    r"(?i)("
    r"most\s+guys.{0,40}(gone|leave|poof)|"
    r"poof\s+they'?re\s+gone|"
    r"give\s+a\s+damn|"
    r"you'?re\s+(so\s+)?quiet|"
    r"why\s+(are\s+you|you\s+so)\s+quiet|"
    r"everyone\s+(leaves|ghosts)|"
    r"guys\s+always\s+(leave|disappear)"
    r")"
)

_STICKY_STAMP = re.compile(
    r"(?i)hey\.{2,}\s*look\s+at\s+me\s+when\s+i'?m\s+talking\s+to\s+you"
)

_SOFT_THERAPIST = re.compile(
    r"(?i)("
    r"tell\s+me\s+(what'?s|whats)\s+(really\s+)?(going\s+on|wrong)|"
    r"i'?m\s+here\s+(for\s+you|if\s+you\s+need)|"
    r"you\s+can\s+(vent|talk\s+to\s+me)|"
    r"how\s+does\s+that\s+make\s+you\s+feel"
    r")"
)

# Spanish reply while ENGLISH_ONLY (ignore short loanwords already in filthy EN)
_SPANISH_HEAVY = re.compile(
    r"(?i)\b("
    r"hola|cómo|como\s+estás|qué\s+tal|mira\s+qué|te\s+quiero|"
    r"cariño|bebé|bebe|guapo|guapa|ándale|andale|"
    r"ábrela|abrela|solo\s+para\s+ti|esta\s+foto|"
    r"me\s+pone|estoy\s+mojad|quiero\s+que\s+me"
    r")\b"
)

_EARLY_ROMANCE_MAX = 8


def detect_reply_failures(
    reply: str,
    *,
    pack_id: str = "",
    lock_active: Optional[bool] = None,
    media_attached: bool = False,
    technique: str = "",
    msgs_before: int = 0,
    paid_offer: bool = False,
    draft: str = "",
) -> List[Dict[str, Any]]:
    """
    Return list of {rule, severity, what}. severity 3 = hard fail, 2 = soft.
    """
    text = (reply or "").strip()
    errs: List[Dict[str, Any]] = []

    for e in scheme_guard.check_reply(
        text,
        pack_id=pack_id,
        lock_active=lock_active,
        media_attached=media_attached,
        technique=technique,
    ):
        errs.append(e)

    if not text:
        return errs

    if _ROBOTIC_PPV.search(text) or (
        paid_offer and _ROBOTIC_PPV.search(draft or "")
    ):
        errs.append(
            {
                "rule": "CAPTION",
                "severity": 3,
                "what": "robotic store PPV caption (Just for you / unlock it…)",
            }
        )

    if msgs_before < _EARLY_ROMANCE_MAX and _EARLY_GUILT.search(text):
        errs.append(
            {
                "rule": "EARLY",
                "severity": 3,
                "what": f"guilt/silence pressure too early (msgs={msgs_before})",
            }
        )

    if _STICKY_STAMP.search(text):
        errs.append(
            {
                "rule": "STAMP",
                "severity": 3,
                "what": "retired sticky EN stamp reappeared",
            }
        )

    if msgs_before < _EARLY_ROMANCE_MAX and _SOFT_THERAPIST.search(text):
        errs.append(
            {
                "rule": "EARLY",
                "severity": 2,
                "what": "soft-therapist energy in early romance window",
            }
        )

    if getattr(config, "ENGLISH_ONLY", True) and _SPANISH_HEAVY.search(text):
        # Filthy forced ES sell lines shouldn't ship under ENGLISH_ONLY
        errs.append(
            {
                "rule": "LANG",
                "severity": 3,
                "what": "Spanish in reply while ENGLISH_ONLY=1",
            }
        )

    if paid_offer and media_attached:
        low = text.lower()
        filthy = any(
            w in low
            for w in (
                "filthy",
                "slut",
                "whore",
                "nasty",
                "bent",
                "look how",
                "look at me",
            )
        )
        if not filthy and not scheme_guard.paid_offer_reply_aligned(text):
            errs.append(
                {
                    "rule": "CAPTION",
                    "severity": 2,
                    "what": "paid attach without clear filthy sell energy",
                }
            )

    # Lang rewrite emptied the draft → canned EN fallback (kills hook)
    norm = text.lower().strip()
    if any(norm == fb.lower() for fb in _EN_LANG_FALLBACKS):
        errs.append(
            {
                "rule": "FALLBACK",
                "severity": 2,
                "what": "shipped stock lang-fallback (draft was wiped)",
            }
        )

    return errs
