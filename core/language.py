"""
Language lock for Emma replies.

Mirror policy: reply in the fan's language — Spanish message gets a full
correct Spanish reply, anything else gets English. Explicit asks
("speak english" / "habla español") override. Never Spanglish.
"""
from __future__ import annotations

import re
from typing import Optional

# Explicit ask to switch language
_ASK_SPANISH = re.compile(
    r"(?i)\b("
    r"speak spanish|in spanish|talk spanish|español|espanol|"
    r"habla espa[nñ]ol|en espa[nñ]ol|dime en espa[nñ]ol|"
    r"responde en espa[nñ]ol|can you speak spanish"
    r")\b"
)
_ASK_ENGLISH = re.compile(
    r"(?i)\b("
    r"speak english|in english|talk english|habla ingl[eé]s|en ingl[eé]s"
    r")\b"
)

# Strong Spanish lexical hits (enough to flag Spanglish / Spanish mode text)
_SPANISH_HITS = re.compile(
    r"(?i)\b("
    r"hola|mira|beb[eé]|cari[nñ]o|cielo|guapo|guapa|por favor|gracias|"
    r"[aá]brelo|abrelo|m[ií]rame|mirame|te mand[eé]|te envi[eé]|"
    r"quiero|puedes|est[aá]s|estoy|nacho|nena|papi|caro|"
    r"lo que|donde|dónde|también|tambien|ma[nñ]ana|mañana|"
    r"contigo|sin ti|ay+|rev[ií]salo|revisalo|caliente|"
    r"pensando en ti|se me|generosa|r[aá]pido|rapido|"
    r"espa[nñ]ol|ingl[eé]s|traductor"
    r")\b"
    r"|[áéíóúñ¿¡]"
)

_ENGLISH_HITS = re.compile(
    r"(?i)\b(the|you|your|what|when|where|this|that|have|with|just|from|"
    r"unlock|photo|baby|babe|handsome|ignored|happens)\b"
)


def _message_is_spanish(text: str) -> bool:
    """Heuristic: is this fan message written in Spanish?"""
    es = len(_SPANISH_HITS.findall(text or ""))
    en = len(_ENGLISH_HITS.findall(text or ""))
    return es >= 1 and es > en


def fan_wants_spanish(fan_message: str, mem: Optional[dict] = None) -> bool:
    """
    Mirror policy: reply in the language HE uses.
    - explicit ask ("speak english"/"habla español") always wins
    - else: Spanish message → Spanish reply; otherwise English
    - memory pref (set by explicit asks) is the tie-breaker
    """
    text = fan_message or ""
    if _ASK_ENGLISH.search(text):
        return False
    if _ASK_SPANISH.search(text):
        return True
    if _message_is_spanish(text):
        return True
    if mem and mem.get("prefer_spanish"):
        return True
    return False


def update_language_pref(mem: dict, fan_message: str) -> Optional[bool]:
    """
    Returns new prefer_spanish value if it should change, else None.
    Caller persists via fan_memory.
    """
    text = fan_message or ""
    if _ASK_ENGLISH.search(text):
        return False
    if _ASK_SPANISH.search(text):
        return True
    return None


def is_mixed_or_wrong(text: str, *, want_spanish: bool) -> bool:
    """Detect Spanglish or wrong-language leakage."""
    if not text or not text.strip():
        return True
    es = len(_SPANISH_HITS.findall(text))
    en = len(_ENGLISH_HITS.findall(text))
    if want_spanish:
        # Spanish reply with a lot of English glue = bad mix
        return en >= 3 and es >= 1
    # English mode: any clear Spanish hit is a failure
    return es >= 1


def language_system_block(want_spanish: bool) -> str:
    if want_spanish:
        return (
            "LANGUAGE LOCK (STRICT):\n"
            "- Write this ENTIRE reply in correct, natural Spanish only.\n"
            "- Zero English words. Zero Spanglish.\n"
            "- Perfect spelling in YOUR words only — never pedantically 'fix' or quote back his typos.\n"
            "- Do NOT blame the chat app, translator, or glitches — stay in character.\n"
            "- Never use the word 'caro' as a pet name."
        )
    return (
        "LANGUAGE LOCK (STRICT):\n"
        "- Write this ENTIRE reply in correct, natural English only.\n"
        "- ZERO Spanish words. No Spanglish. No 'mira', 'bebé', 'ábrelo', 'caro', 'papi', 'nena'.\n"
        "- Perfect spelling in YOUR words only — never pedantically 'fix' his typos.\n"
        "- Do NOT blame the chat app or glitches — stay in character.\n"
        "- You are a native LA English speaker.\n"
        "- WRONG: 'Ay bebé, revísalo...' then English.\n"
        "- RIGHT: 'Hey baby, look again... I locked a hot photo for you yesterday.'"
    )


def rewrite_instruction(want_spanish: bool) -> str:
    if want_spanish:
        return (
            "Rewrite your last reply in correct Spanish only. "
            "No English. Clean grammar in your words — don't 'fix' his typos. "
            "Keep the same meaning and flirty tone."
        )
    return (
        "Rewrite your last reply in correct English only. "
        "No Spanish words at all. No Spanglish. Clean grammar in your words — don't 'fix' his typos. "
        "Keep the same meaning and flirty tone. Native American English."
    )
