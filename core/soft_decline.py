"""Shared fan decline / broke signals — one regex source for router + playbook + sanitize."""
from __future__ import annotations

import re

_SOFT_DECLINE_RE = re.compile(
    r"(?i)\b("
    r"no,?\s*sorry|not\s+now|maybe\s+later|another\s+moment|"
    r"otro\s+momento|next\s+time|otro\s+d[ií]a|"
    r"not\s+so\s+horny|don'?t\s+want\s+to\s+spend|"
    r"spend\s+(my\s+)?money|no\s+thanks|no\s+gracias|"
    r"maybe\s+in\s+another|don'?t\s+worry.*another|"
    r"can'?t\s+right\s+now|cannot\s+right\s+now|"
    r"pay\s+my\s+bills|need\s+to\s+pay|bills\s+first|"
    r"no\s+money\s+for|can'?t\s+open\s+it\s+yet|can'?t\s+open\s+yet"
    r")\b"
)

_SOFT_DECLINE_FULLMATCH = re.compile(
    r"(?i)\s*(no|nope|nah|pass|not\s+now)\s*[.!,]?\s*(sorry)?\s*"
)

_CANT_RIGHT_NOW = re.compile(r"(?i)\bcan'?t\b.{0,24}\bright\s+now\b")

_BROKE_SOFT_RE = re.compile(
    r"(?i)\b("
    r"pelado|pelá|broke|can'?t afford|no money|"
    r"sin (plata|dinero|pasta|un duro)|"
    r"no tengo (plata|dinero|pasta|nada)|"
    r"estoy (sin plata|pelado|pelao)|"
    r"pay\s+my\s+bills|need\s+to\s+pay|bills\s+first|"
    r"can'?t\s+open\s+it\s+yet|can'?t\s+open\s+yet"
    r")\b"
)

_PRICE_PUSHBACK_RE = re.compile(
    r"(?i)\b("
    r"caro|car[ií]simo|expensive|too (much|expensive)|"
    r"muy caro|no (me )?lo (pago|compro)|descuento|"
    r"discount|cheaper|m[aá]s barato|no tengo (plata|dinero|money)|"
    r"can't afford|cant afford|later|despu[eé]s|nah\b|"
    r"not (gonna|going to) (pay|buy)|no voy a (pagar|comprar)|"
    r"pay\s+my\s+bills|bills\s+first|can'?t\s+open\s+it\s+yet|can'?t\s+right\s+now"
    r")\b"
)


def is_soft_decline(text: str) -> bool:
    low = (text or "").strip()
    if not low:
        return False
    if _SOFT_DECLINE_RE.search(low):
        return True
    if _CANT_RIGHT_NOW.search(low):
        return True
    return bool(_SOFT_DECLINE_FULLMATCH.fullmatch(low))


def is_broke_soft(text: str) -> bool:
    return bool(_BROKE_SOFT_RE.search((text or "").strip()))


def is_price_pushback(text: str) -> bool:
    low = (text or "").strip()
    return bool(_PRICE_PUSHBACK_RE.search(low)) or is_soft_decline(low)
