"""
Language lock for Emma replies.

ENGLISH_ONLY (default): always English. Ignore Spanish fan messages and sticky prefs.
Detection helpers remain so Spanglish drafts can still be stripped/rewritten to EN.
"""
from __future__ import annotations

import re
from typing import Optional

from config import config

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

# Content / flirt lexicon (reply mix checks + detection)
_SPANISH_CONTENT = re.compile(
    r"(?i)\b("
    r"hola|mira|beb[eé]|cari[nñ]o|cielo|guapo|guapa|por\s*favor|porfavor|gracias|"
    r"[aá]bre(lo|la)|m[ií]rame|te mand[eé]|te envi[eé]|"
    r"quiero|puedes|est[aá]s|estoy|nacho|nena|papi|caro|"
    r"también|tambien|ma[nñ]ana|mañana|contigo|caliente|"
    r"foto|fotos|gustado|gust[oó]|encant[oó]|ense[nñ]a|"
    r"m[aá]nda(me|la)?|env[ií]a(me|la)?|polla|guarr\w*|candado|"
    r"vale|venga|dale|siquiera|visto|ahora|mucho|poco|nada|"
    r"d[oó]lares?|mentiros[ao]|enfado|masivo|llamado"
    r")\b"
    r"|[áéíóúñ¿¡]"
)

_SPANISH_STOPS = frozenset(
    """
    el la los las un una unos unas de del al que qué
    por para con sin como más pero porque cuando donde dónde
    me te se nos le les lo ya muy tan aquí ahí allí
    es está estás están soy eres somos hay tiene tengo
    mi tu su mis tus sus esto esta ese esa esos esas
    también ahora después antes nunca siempre nada todo
    no si sí
    """.split()
)

_ENGLISH_STOPS = frozenset(
    """
    the you your what when where this that have with just from
    how much does really because about think know want need
    please already never always something nothing everything
    are was were been being will would could should
    don't didn't can't won't isn't aren't i'm i'll i've
    """.split()
)

_ENGLISH_REPLY_HITS = re.compile(
    r"(?i)\b(the|you|your|what|when|where|this|that|have|with|just|from|"
    r"i'?m|i'?ll|i'?ve|don'?t|can'?t|won'?t|isn'?t|"
    r"baby|babe|handsome|really|because|about|think|know|want|need|"
    r"please|already|never|always|something|unlock|photo|lock|"
    r"okay|right|that's|sitting|excited)\b"
)

# Legacy aliases
_SPANISH_HITS = _SPANISH_CONTENT
_ENGLISH_HITS = re.compile(
    r"(?i)\b("
    + "|".join(re.escape(w) for w in sorted(_ENGLISH_STOPS, key=len, reverse=True))
    + r")\b"
)


def english_only() -> bool:
    return bool(getattr(config, "ENGLISH_ONLY", True))


def _strip_system_noise(text: str) -> str:
    """Drop vision/system stubs so they don't flip language detection."""
    t = text or ""
    t = re.sub(
        r"\[(?:fan sent a photo|attached photo)[^\]]*\]",
        " ",
        t,
        flags=re.I,
    )
    t = re.sub(r"\(You can see it:[^)]*\)", " ", t, flags=re.I)
    return t.strip()


def _words(text: str) -> list[str]:
    return re.findall(r"[a-záéíóúñü]+", (text or "").lower())


def _message_is_spanish(text: str) -> bool:
    """Heuristic: is this fan message written in Spanish?"""
    t = _strip_system_noise(text)
    if not t:
        return False
    if re.search(r"[áéíóúñ¿¡]", t):
        return True
    words = _words(t)
    if not words:
        return False
    stop_es = sum(1 for w in words if w in _SPANISH_STOPS)
    content_es = len(_SPANISH_CONTENT.findall(t))
    en = sum(1 for w in words if w in _ENGLISH_STOPS)
    es = stop_es + content_es
    if content_es >= 1 and es >= en:
        return True
    return stop_es >= 2 and stop_es >= en


def _message_is_clearly_english(text: str) -> bool:
    t = _strip_system_noise(text)
    if not t or _message_is_spanish(t):
        return False
    words = _words(t)
    en = sum(1 for w in words if w in _ENGLISH_STOPS)
    es = sum(1 for w in words if w in _SPANISH_STOPS)
    return en >= 2 and es == 0


def fan_wants_spanish(fan_message: str, mem: Optional[dict] = None) -> bool:
    """
    Always False when ENGLISH_ONLY (live default).
    Legacy mirror path kept only if ENGLISH_ONLY=0.
    """
    if english_only():
        return False
    text = _strip_system_noise(fan_message or "")
    if _ASK_ENGLISH.search(text):
        return False
    if _ASK_SPANISH.search(text):
        return True
    if text.strip() and _message_is_spanish(text):
        return True
    if text.strip() and _message_is_clearly_english(text):
        return False
    if mem and mem.get("prefer_spanish"):
        return True
    return False


def update_language_pref(mem: dict, fan_message: str) -> Optional[bool]:
    """
    Persist sticky language. Under ENGLISH_ONLY, always force English (False).
    """
    if english_only():
        return False
    text = _strip_system_noise(fan_message or "")
    if _ASK_ENGLISH.search(text):
        return False
    if _ASK_SPANISH.search(text):
        return True
    if text.strip() and _message_is_spanish(text):
        return True
    if text.strip() and _message_is_clearly_english(text):
        return False
    return None


def is_mixed_or_wrong(text: str, *, want_spanish: bool) -> bool:
    """Detect Spanglish or wrong-language leakage."""
    if english_only():
        want_spanish = False
    if not text or not text.strip():
        return True
    es = len(_SPANISH_CONTENT.findall(text)) + sum(
        1 for w in _words(text) if w in _SPANISH_STOPS
    )
    en = len(_ENGLISH_REPLY_HITS.findall(text))
    if want_spanish:
        if es == 0 and en >= 1:
            return True
        if es == 0 and re.search(r"[A-Za-z]{4,}", text or ""):
            return True
        return en >= 4 and es >= 1 and en > es
    if re.search(r"[áéíóúñ¿¡]", text or ""):
        return True
    if en >= 2 and es <= 1:
        return False
    return es >= 2


def language_system_block(want_spanish: bool = False) -> str:
    if english_only() or not want_spanish:
        return (
            "LANGUAGE LOCK (STRICT — ENGLISH ONLY):\n"
            "- Reply in correct, natural American English only. Every turn.\n"
            "- ZERO Spanish words. No Spanglish. No 'mira', 'bebé', 'ábrelo', "
            "'joder', 'guapo', 'cielo', 'caro', 'papi', 'nena'.\n"
            "- Even if HE writes in Spanish: answer in English. Do not mirror Spanish.\n"
            "- Perfect spelling in YOUR words only — never pedantically 'fix' his typos.\n"
            "- You are a native LA English speaker texting on WhatsApp.\n"
            "- WRONG: 'Ay bebé, revísalo...' then English.\n"
            "- RIGHT: 'Hey baby, look again... I locked a hot photo for you yesterday.'"
        )
    return (
        "LANGUAGE LOCK (STRICT):\n"
        "- He wrote in Spanish → reply in FULL correct natural Spanish only.\n"
        "- Zero English. Zero Spanglish.\n"
        "- Gender: YOU=feminine (mojada, excitada, guarra); HIM=masculine (guapo).\n"
        "- Clean spelling in YOUR words — never pedantically fix HIS typos.\n"
        "- Never use 'caro/papi/nena/nene' as pet names."
    )


def rewrite_instruction(want_spanish: bool = False) -> str:
    if english_only() or not want_spanish:
        return (
            "Rewrite your last reply in correct English only. "
            "No Spanish words at all. No Spanglish. Clean grammar in your words — "
            "don't 'fix' his typos. Keep the same meaning and flirty tone. "
            "Native American English. Even if he wrote in Spanish — English reply."
        )
    return (
        "REESCRIBE tu último mensaje en español correcto y natural. "
        "Cero inglés. Concordancia: tú=femenina; él=masculino (guapo). "
        "Mismo tono pícaro; no corrijas sus faltas."
    )


_BROKEN_SELF_MASC = re.compile(
    r"(?i)\b("
    r"(estoy|quedo|me\s+siento)\s+(mojado|excitado|desnudo|listo|abierto|guarro)|"
    r"me\s+tiene\s+mojado|"
    r"soy\s+(muy\s+)?(guarro|sucio)"
    r")\b"
)

_CALL_HIM_FEM = re.compile(
    r"(?i)\b("
    r"(ay+|eh+|hola|vamos|dale|ven)\s*,?\s*(guapa|hermosa|preciosa|bonita)|"
    r"mi\s+(guapa|hermosa|preciosa|bonita|nena)|"
    r"(eres|estás)\s+(muy\s+)?(guapa|hermosa|preciosa|bonita)"
    r")\b"
)

_BROKEN_PERSON = re.compile(
    r"(?i)\b("
    r"(t[uú])\s+(estoy|somos|soy)|"
    r"(yo)\s+(estás|eres)|"
    r"estoy\s+getting|you\s+make\s+me"
    r")\b"
)


def looks_broken_spanish(text: str) -> bool:
    """Cheap detectors for gender/person slips (legacy; unused under ENGLISH_ONLY)."""
    if english_only():
        return False
    t = (text or "").strip()
    if not t:
        return False
    return bool(
        _BROKEN_SELF_MASC.search(t)
        or _CALL_HIM_FEM.search(t)
        or _BROKEN_PERSON.search(t)
    )


def grammar_rewrite_instruction() -> str:
    return (
        "Rewrite in informal WhatsApp English: natural, short. "
        "Fix only broken grammar. Keep chat slang (u, rn, lol, babe…). "
        "Same idea. No new locks or prices."
    )
