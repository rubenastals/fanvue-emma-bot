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
    r"hola|mira|beb[eé]|cari[nñ]o|cielo|guapo|guapa|por\s*favor|gracias|"
    r"[aá]bre(lo|la)|m[ií]rame|te mand[eé]|te envi[eé]|"
    r"quiero|puedes|est[aá]s|estoy|nacho|nena|papi|caro|"
    r"lo que|donde|dónde|también|tambien|ma[nñ]ana|mañana|"
    r"contigo|sin ti|ay+|rev[ií]salo|caliente|"
    r"pensando en ti|se me|generosa|r[aá]pido|rapido|"
    r"espa[nñ]ol|ingl[eé]s|traductor|"
    r"foto|fotos|gustado|gust[oó]|encant[oó]|ense[nñ]a|"
    r"m[aá]nda(me|la)?|env[ií]a(me|la)?|p[aá]sa(me|la)?|"
    r"polla|guarr\w*|candado|vale|venga|dale|"
    r"siquiera|visto|val[ií]a|primero|luego|ahora|"
    r"mucho|poco|nada|esto|esta|esos|esas|d[oó]lares?"
    r")\b"
    r"|[áéíóúñ¿¡]"
)

# Structural English only — NOT baby/babe/photo (fans use those in Spanish chats)
_ENGLISH_HITS = re.compile(
    r"(?i)\b(the|you|your|what|when|where|this|that|have|with|just|from|"
    r"handsome|ignored|happens|how|much|does|don't|didn't|can't|won't|"
    r"isn't|aren't|really|because|about|think|know|want|need|please|"
    r"already|never|always|something|nothing|everything)\b"
)

# Reply-side English glue (catch full-EN answers when Spanish was required)
_ENGLISH_REPLY_HITS = re.compile(
    r"(?i)\b(the|you|your|what|when|where|this|that|have|with|just|from|"
    r"i'?m|i'?ll|i'?ve|don'?t|can'?t|won'?t|isn'?t|"
    r"baby|babe|handsome|really|because|about|think|know|want|need|"
    r"please|already|never|always|something|unlock|photo|lock)\b"
)


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


def _message_is_spanish(text: str) -> bool:
    """Heuristic: is this fan message written in Spanish?"""
    t = _strip_system_noise(text)
    es = len(_SPANISH_HITS.findall(t))
    en = len(_ENGLISH_HITS.findall(t))
    if es >= 1 and es >= en:
        return True
    if re.search(r"[áéíóúñ¿¡]", t or "", re.I) and en == 0:
        return True
    return False


def _message_is_clearly_english(text: str) -> bool:
    """True only for clearly English turns (not ambiguous / short Spanish)."""
    t = _strip_system_noise(text)
    if not t:
        return False
    if _message_is_spanish(t):
        return False
    en = len(_ENGLISH_HITS.findall(t))
    es = len(_SPANISH_HITS.findall(t))
    return en >= 2 and es == 0


def fan_wants_spanish(fan_message: str, mem: Optional[dict] = None) -> bool:
    """
    Emma's native language is English (~95% of fans).
    Mirror: Spanish message → Spanish; clear English → English.
    Sticky prefer_spanish covers short/ambiguous turns.
    """
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
    Returns new prefer_spanish value if it should change, else None.
    Sticky follows how HE chats (for nudges/apologies).
    """
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
    if not text or not text.strip():
        return True
    es = len(_SPANISH_HITS.findall(text))
    en = len(_ENGLISH_REPLY_HITS.findall(text))
    if want_spanish:
        # Pure English when Spanish required — the bug that let EN replies ship
        if es == 0 and en >= 1:
            return True
        if es == 0 and re.search(r"[A-Za-z]{4,}", text or ""):
            return True
        # Heavy English glue over a thin Spanish crumb
        return en >= 4 and es >= 1 and en > es
    # English mode: any clear Spanish hit is a failure
    return es >= 1


def language_system_block(want_spanish: bool) -> str:
    if want_spanish:
        return (
            "LANGUAGE LOCK (STRICT) — he wrote in Spanish, so mirror in Spanish this turn:\n"
            "- Your native language is English, but THIS reply must be correct natural Spanish only.\n"
            "- Zero English words. Zero Spanglish. No mental word-for-word English calques.\n"
            "- TÚ with the fan (never usted). Gender agreement REQUIRED:\n"
            "  · YOU (Emma) = feminine: mojada, excitada, desnuda, guarra, lista, tuya.\n"
            "  · HIM (fan) = masculine: guapo, rico — never call him guapa/hermosa/preciosa.\n"
            "  · Never 'estoy mojado/excitado' about yourself.\n"
            "- Coherent verb tenses; correct yo/tú conjugation (never 'tú estoy' / 'yo estás').\n"
            "- Short real-chat Spanish. Clean spelling in YOUR words — don't correct his typos.\n"
            "- Never 'caro/papi/nena/nene' as pet names. No app/translator excuses."
        )
    return (
        "LANGUAGE LOCK (STRICT):\n"
        "- You are a native LA English speaker. Default language = English.\n"
        "- Write this ENTIRE reply in correct, natural English only.\n"
        "- ZERO Spanish words. No Spanglish. No 'mira', 'bebé', 'ábrelo', 'caro', 'papi', 'nena'.\n"
        "- Perfect spelling in YOUR words only — never pedantically 'fix' his typos.\n"
        "- Do NOT blame the chat app or glitches — stay in character.\n"
        "- WRONG: 'Ay bebé, revísalo...' then English.\n"
        "- RIGHT: 'Hey baby, look again... I locked a hot photo for you yesterday.'"
    )


def rewrite_instruction(want_spanish: bool) -> str:
    if want_spanish:
        return (
            "REESCRIBE tu último mensaje en español correcto y natural. "
            "Cero inglés. Concordancia: tú=femenina (mojada/excitada/guarra); "
            "él=masculino (guapo, no guapa). Tiempos verbales coherentes; "
            "yo/tú bien conjugados. Mismo tono pícaro; no corrijas sus faltas."
        )
    return (
        "Rewrite your last reply in correct English only. "
        "No Spanish words at all. No Spanglish. Clean grammar in your words — don't 'fix' his typos. "
        "Keep the same meaning and flirty tone. Native American English."
    )


# Emma (female) using masculine self-agreement — common DeepSeek slip
_BROKEN_SELF_MASC = re.compile(
    r"(?i)\b("
    r"(estoy|quedo|me\s+siento|ando)\s+(mojado|excitado|desnudo|listo|abierto|guarro)|"
    r"me\s+tiene\s+mojado|"
    r"soy\s+(muy\s+)?(guarro|sucio)|"
    r"dej[aá]me\s+(mojado|excitado)"
    r")\b"
)

# Calling HIM with feminine nicknames
_CALL_HIM_FEM = re.compile(
    r"(?i)\b("
    r"(ay+|eh+|hola|vamos|dale|ven)\s*,?\s*(guapa|hermosa|preciosa|bonita|rica)|"
    r"mi\s+(guapa|hermosa|preciosa|bonita|nena)|"
    r"(eres|estás)\s+(muy\s+)?(guapa|hermosa|preciosa|bonita)"
    r")\b"
)

# Broken person / conjugation crumbs
_BROKEN_PERSON = re.compile(
    r"(?i)\b("
    r"(t[uú])\s+(estoy|somos|soy|éramos)|"
    r"(yo)\s+(estás|eres|sois)|"
    r"(nosotros)\s+(estoy|estás)|"
    r"tu\s+está\b|"  # missing accent often marks "tu esta" calque; still flag tu+está mismatch vibes
    r"me\s+hacer\b|te\s+hacer\b|"
    r"estoy\s+getting|you\s+make\s+me|"
    r"i'?m\s+\w+ando"  # half English gerund salad
    r")\b"
)


def looks_broken_spanish(text: str) -> bool:
    """Cheap detectors for gender/person slips that kill immersion."""
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
        "REESCRIBE DURO en español nativo correcto. "
        "Arregla SOLO gramática: género (Emma femenina: mojada/excitada/desnuda/guarra; "
        "fan masculino: guapo/rico — nunca guapa/hermosa para él), "
        "conjugación yo/tú, y tiempos coherentes. "
        "Nada de calcos del inglés. Mismo significado y tono sexual/dulce. "
        "No añadas candados ni precios nuevos."
    )
