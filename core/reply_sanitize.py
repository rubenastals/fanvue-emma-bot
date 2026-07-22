"""
Reply SANITIZE seam (audit R4).

Post-draft belts: rewrite budget, delivery/sell/price truth, length, continuity.
Deterministic strips/fallbacks for hard lies — see MAX_CREATIVE_REWRITES.
"""
from __future__ import annotations

import random
import re
from typing import Any, Dict, List, Optional, Tuple, TYPE_CHECKING

from config import config
from core import fan_memory, language, scheme_guard
from core.turn_policy import TurnDecision
from core.reply_assemble import _usable_fan_name

if TYPE_CHECKING:
    from core.reply_types import AssembledTurn

# Always banned as address words.
_BANNED_ALWAYS = re.compile(
    r"(?i)(?:\s*[,.]?\s*)\b(caro|papi|nena|nene)\b\.?"
)
# Stage-direction brackets DeepSeek may copy from history labels — never shown to fan.
# Includes [Voice Note: (breathy, soft)] — that leak screams "bot".
_STAGE_BRACKETS = re.compile(
    r"\s*\["
    r"(?:image locked|photo locked|locked image|paid photo lock|voice note attached|"
    r"voice\s*notes?|"
    r"you locked|you sent a|fan sent a|SYSTEM[: ]|Transmite|envi[oó]|you can send|"
    r"whispers?|sighs?|chuckles?|exhales?|moans?|laughs?|breathes?|pauses?|gasps?)"
    r"[^\]]*\]",
    re.I,
)
# TTS stage paren anywhere: (breathy, soft) / (whispering)
_VOICE_PAREN_DIR = re.compile(
    r"(?i)\(\s*(?:breathy|soft|whisper\w*|sensual|moan\w*|intimate|"
    r"low|quiet|filthy)[^)]{0,40}\)"
)
# Unbracketed / partial: Voice Note: … or [Voice Note:
_VOICE_NOTE_LABEL = re.compile(r"(?i)\[?\s*voice\s*notes?\s*:")
# Spanish nicknames — strip only in English mode (Spanglish leak).
_BANNED_SPANISH_IN_ENGLISH = re.compile(
    r"(?i)(?:\s*[,.]?\s*)\b("
    r"cielito|mi cielo|beb[eé]|guapo|guapa|cari[nñ]o|mi rey|bonito|cielo"
    r")\b\.?"
)

_WORD_MONEY = {
    "uno": 1,
    "un": 1,
    "una": 1,
    "dos": 2,
    "tres": 3,
    "cuatro": 4,
    "cinco": 5,
    "seis": 6,
    "siete": 7,
    "ocho": 8,
    "nueve": 9,
    "diez": 10,
    "once": 11,
    "doce": 12,
    "quince": 15,
    "veinte": 20,
    "treinta": 30,
    "cuarenta": 40,
    "cincuenta": 50,
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "twelve": 12,
    "fifteen": 15,
    "twenty": 20,
    "thirty": 30,
    "forty": 40,
    "fifty": 50,
}


class RewriteBudget:
    """
    Cap post-draft LLM rewrites (R2). Hard lies must not spend this —
    use strip / deterministic fallback instead.
    """

    def __init__(self, max_extra: int = 1) -> None:
        self.max_extra = max(0, int(max_extra))
        self.used = 0
        self.log: List[str] = []

    def can_spend(self) -> bool:
        return self.used < self.max_extra

    def spend(self, label: str, call, msgs: List[Dict[str, str]]) -> Optional[str]:
        if not self.can_spend():
            print(f"   rewrite budget: skip LLM ({label}) — deterministic only")
            return None
        self.used += 1
        self.log.append(label)
        print(f"   rewrite budget: LLM #{self.used}/{self.max_extra} ({label})")
        return call(msgs)


def _fix_invented_wait_minutes(text: str, *, minutes_ago: int) -> str:
    """Clamp invented 'N minutos' wait claims down to the real lock age."""
    real = max(0, int(minutes_ago))

    def _clamp_num(m: re.Match) -> str:
        try:
            claimed = int(m.group(1))
        except (TypeError, ValueError):
            return m.group(0)
        if claimed <= real + 2:
            return m.group(0)
        return m.group(0).replace(str(claimed), str(real), 1)

    cleaned = text or ""
    cleaned = re.sub(r"(?i)(\d{1,3})\s*minut", _clamp_num, cleaned)
    cleaned = re.sub(
        r"(?i)(minut\w*\s*[,.…]+\s*)(\d{1,3})",
        lambda m: (
            m.group(0)
            if int(m.group(2)) <= real + 2
            else m.group(1) + str(real)
        ),
        cleaned,
    )
    cleaned = re.sub(
        r"(?i)((?:waiting|for)\s+)(\d{1,3})(\s*min\b)",
        lambda m: (
            m.group(0)
            if int(m.group(2)) <= real + 2
            else m.group(1) + str(real) + m.group(3)
        ),
        cleaned,
    )
    return cleaned


def _stated_prices(text: str) -> List[float]:
    """Dollar/euro amounts the reply asserts (digits + spelled)."""
    out: List[float] = []
    for m in re.finditer(
        r"(?:\$|€)\s*(\d{1,4})|(\d{1,4})\s*(?:€|\$|eur|euros?|d[oó]lares?|dollars?|bucks?)",
        text or "",
    ):
        raw = m.group(1) or m.group(2)
        try:
            val = float(raw)
        except (TypeError, ValueError):
            continue
        # Include $1–$2 — DeepSeek invents micro prices against a $40 lock
        if 1 <= val <= 500:
            out.append(val)
    for m in re.finditer(
        r"(?i)\b("
        + "|".join(re.escape(k) for k in sorted(_WORD_MONEY, key=len, reverse=True))
        + r")\s*(d[oó]lares?|dollars?|bucks?)\b",
        text or "",
    ):
        out.append(float(_WORD_MONEY[m.group(1).lower()]))
    return out


def _strip_wrong_prices(text: str, *, real_price: Optional[float]) -> str:
    """Remove or correct invented money phrases after a failed rewrite."""
    cleaned = text or ""
    if real_price is not None:
        # Replace spelled + digit money with the real amount once
        cleaned = re.sub(
            r"(?:\$|€)\s*\d{1,4}|\d{1,4}\s*(?:€|\$|eur|euros?|d[oó]lares?|dollars?|bucks?)",
            f"${real_price:.0f}",
            cleaned,
            count=1,
        )
        cleaned = re.sub(
            r"(?i)\b("
            + "|".join(re.escape(k) for k in sorted(_WORD_MONEY, key=len, reverse=True))
            + r")\s*(d[oó]lares?|dollars?|bucks?)\b",
            f"${real_price:.0f}",
            cleaned,
            count=1,
        )
        # Strip any remaining wrong numeric money tokens
        for p in _stated_prices(cleaned):
            if abs(p - real_price) > 0.5:
                cleaned = re.sub(
                    rf"(?:\$|€)\s*{int(p)}|{int(p)}\s*(?:€|\$|eur|euros?|d[oó]lares?|dollars?|bucks?)",
                    "",
                    cleaned,
                    count=1,
                    flags=re.I,
                )
    else:
        cleaned = re.sub(
            r"(?:\$|€)\s*\d{1,4}|\d{1,4}\s*(?:€|\$|eur|euros?|d[oó]lares?|dollars?|bucks?)",
            "",
            cleaned,
        )
        cleaned = re.sub(
            r"(?i)\b("
            + "|".join(re.escape(k) for k in sorted(_WORD_MONEY, key=len, reverse=True))
            + r")\s*(d[oó]lares?|dollars?|bucks?)\b",
            "",
            cleaned,
        )
    return re.sub(r"\s{2,}", " ", cleaned).strip()


def _thin_name_in_reply(
    text: str,
    name: str,
    *,
    name_confirmed: bool = False,
    max_uses: int = 1,
) -> str:
    """Keep at most max_uses of his real name. max_uses=0 strips all."""
    name = _usable_fan_name(name, confirmed=name_confirmed)
    if not name or not text:
        return text
    pattern = re.compile(rf"\b{re.escape(name)}\b", re.IGNORECASE)
    # Also kill "Ay Ruben" / "Ay, Ruben" openings
    text = re.sub(
        rf"(?i)^\s*ay\s*,?\s*{re.escape(name)}\s*[,.…]*\s*",
        "",
        text,
    )
    text = re.sub(
        rf"(?i)(^|\n)\s*ay\s*,?\s*{re.escape(name)}\s*[,.…]*\s*",
        r"\1",
        text,
    )
    if max_uses <= 0:
        cleaned = pattern.sub("", text)
        cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
        cleaned = re.sub(r" +([,.!?…])", r"\1", cleaned)
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
        return cleaned.strip()

    seen = 0

    def _repl(m: re.Match) -> str:
        nonlocal seen
        seen += 1
        if seen > max_uses:
            return ""
        return m.group(0)

    cleaned = pattern.sub(_repl, text)
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    cleaned = re.sub(r" +([,.!?…])", r"\1", cleaned)
    return cleaned


def _strip_photo_script_dump(text: str) -> str:
    """
    Remove caption-like dumps and meta 'I sent a free photo' lines the model
    sometimes pastes instead of letting Fanvue attach the real image.
    """
    if not text:
        return text
    # Fake "tool" / stage directions the model invents instead of a real attach
    text = re.sub(
        r"(?is)\[\s*(?:"
        r"you can send[^]\n]*|"
        r"transmite[^]\n]*|"
        r"send (?:him|her|the)[^]\n]*|"
        r"free tease[^]\n]*|"
        r"(?:envi[aáo]|manda|env[ií]a)[^]\n]*|"
        r"[🥺😏🔥💕😈]\s*(?:transmite|send|env[ií]a)[^]\n]*"
        r")\s*\]",
        "",
        text,
    )
    # Bracket-only lines that look like media titles / director notes
    text = re.sub(
        r"(?im)^\s*\[[^\]\n]{2,80}\]\s*$",
        "",
        text,
    )
    # Meta / placeholder lines
    text = re.sub(
        r"(?im)^\s*\[?\s*(?:envi[oó]|envió|sent|sending)\s+(?:una\s+)?foto(?:\s+gratis)?\s*\]?\s*$",
        "",
        text,
    )
    text = re.sub(
        r"(?i)\b(?:te env[ií]o(?:\s+una)?\s+foto(?:\s+gratis)?|"
        r"aqu[ií] (?:va|tiene)s? (?:una )?foto(?:\s+gratis)?|"
        r"mira la foto[:\s]*|"
        r"\[envi[oó] una foto(?:\s+gratis)?\])\b[^.!?\n]*[.!?]?",
        "",
        text,
    )
    # Cut mid-message shot scripts that start after a normal tease
    cut_at = re.search(
        r"(?i)(?:^|[\s.!?…])("
        r"mirando a c[aá]mara|looking at (?:the )?camera|recostad[ao] en|"
        r"lencer[ií]a de|jugando con el tirante|a punto de baj|"
        r"sonrisa traviesa|ojos bien clavados"
        r")",
        text,
    )
    if cut_at and cut_at.start(1) > 20:
        text = text[: cut_at.start(1)].rstrip(" .…")

    captionish = re.compile(
        r"(?i)("
        r"mirando a c[aá]mara|looking at (?:the )?camera|recostad[ao]|"
        r"lencer[ií]a|sujetador|tirante|encaje blanco|piernas medio|"
        r"sonrisa traviesa|ojos bien clavados|a punto de baj"
        r")"
    )
    kept: List[str] = []
    for block in re.split(r"\n+", text):
        b = block.strip()
        if not b:
            continue
        if len(b) >= 90 and captionish.search(b):
            continue
        kept.append(b)
    return "\n".join(kept).strip()


def looks_like_voice_script_dump(text: str) -> bool:
    """True if draft dumps TTS/stage meta into chat (exposes the bot)."""
    if not text:
        return False
    if _VOICE_NOTE_LABEL.search(text):
        return True
    if _VOICE_PAREN_DIR.search(text):
        return True
    return False


def strip_voice_stage_leaks(text: str) -> str:
    """Remove [Voice Note:…] / (breathy, soft) stage crumbs from chat text."""
    if not text:
        return text
    cleaned = _STAGE_BRACKETS.sub("", text)
    # Unbracketed Voice Note: (breathy, soft) leftover after bracket strip
    cleaned = re.sub(
        r"(?i)\s*voice\s*notes?\s*:\s*(?:\([^)]{0,60}\)\s*)?",
        "",
        cleaned,
    )
    cleaned = _VOICE_PAREN_DIR.sub("", cleaned)
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    cleaned = re.sub(r" +([,.!?…])", r"\1", cleaned)
    return cleaned.strip()


def _sanitize_reply(
    text: str,
    *,
    want_spanish: bool = False,
    fan_name: str = "",
    name_confirmed: bool = False,
    name_max_uses: int = 0,
    media_attached: bool = False,
    paid_lock: bool = False,
    ghost_free_ban: bool = False,
    voice_will_send: bool = False,
) -> str:
    """Strip banned pet names + thin name spam + false delivery claims."""
    if not text:
        return text
    # Voice script leak: audio will carry the spoken beat — never paste TTS stage into chat
    if voice_will_send and looks_like_voice_script_dump(text):
        from core import voice_notes as _vn_dump

        return _vn_dump.forced_voice_close_line(want_spanish=want_spanish)
    cleaned = _BANNED_ALWAYS.sub("", text)
    # Strip any stage-direction brackets copied from history (e.g. [image locked])
    cleaned = strip_voice_stage_leaks(cleaned)
    if not want_spanish:
        cleaned = _BANNED_SPANISH_IN_ENGLISH.sub("", cleaned)
    # Past-tense "already sent" is always fake at generation time (media goes AFTER text).
    cleaned = _FAKE_SENT_PAST.sub("", cleaned)
    if not media_attached:
        cleaned = _FAKE_SENT_NO_MEDIA.sub("", cleaned)
    if paid_lock:
        # Paid lock this turn — never ask permission or pivot to free
        cleaned = _ASK_PERMISSION_OR_FREE.sub("", cleaned)
    if ghost_free_ban:
        cleaned = _FALSE_GIFT_CLAIM.sub("", cleaned)
    cleaned = _strip_photo_script_dump(cleaned)
    cleaned = scheme_guard.strip_echo_quotes(cleaned)
    cleaned = _thin_name_in_reply(
        cleaned,
        fan_name,
        name_confirmed=name_confirmed,
        max_uses=name_max_uses,
    )
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    cleaned = re.sub(r" +([,.!?…])", r"\1", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)

    lines = cleaned.split("\n")
    new_lines: List[str] = []
    for ln in lines:
        s = ln.rstrip()
        if not s:
            continue
        # Only strip if a line ends with a pile of 4+ trailing emojis (spam)
        trail = _TRAILING_EMOJI.search(s)
        if trail and len(trail.group(0).strip()) >= 8:
            s = _TRAILING_EMOJI.sub("", s).rstrip()
        new_lines.append(s)
    return "\n".join(new_lines).strip()


# legacy alias (tests may import)
_BANNED_ADDRESS = _BANNED_ALWAYS


# Stock line that looped live ("Hey... look at me when I'm talking to you.") — gone.
_EN_LANG_FALLBACKS = (
    "hey… stay with me a sec",
    "mmm tell me more…",
    "look at you… you got me smiling",
    "say that again… slower",
    "you're trouble, you know that?",
    "come here… talk to me properly",
)
_ES_LANG_FALLBACKS = (
    "ey… quédate un seg",
    "mmm cuéntame más…",
    "mira cómo me tienes…",
    "dime eso otra vez… más despacio",
    "eres un problema, lo sabes?",
    "ven aquí… háblame bien",
)

# Live reply path: fan JUST messaged — never abandonment / silence guilt loops.
# Live loop: "most guys don't even make it this far… poof they're gone"
_ABANDONMENT_GUILT = re.compile(
    r"(?i)("
    r"most\s+guys?\s+don'?t|"
    r"make\s+it\s+this\s+far|"
    r"\bpoof\b|"
    r"they'?re\s+gone|"
    r"he'?s\s+gone|"
    r"always\s+(leave|disappear|vanish|ghost)|"
    r"guys?\s+(always\s+)?(leave|disappear|ghost|run)|"
    r"everyone\s+(leaves|disappears|ghosts)|"
    r"say\s+something\s+real\s+and|"
    r"i\s+say\s+something\s+real|"
    r"and\s+(then\s+)?(poof|they'?re\s+gone)|"
    r"you'?re?\s+(just\s+)?\.+\s*quiet|"
    r"you'?re?\s+(just\s+)?(quiet|silent|ignoring\s+me)|"
    r"(went|going|go)\s+quiet|"
    r"left\s+me\s+(on\s+read|hanging)|"
    r"now\s+you'?re?\s+just\s*(\.|\…)+\s*quiet|"
    r"and\s+now\s+you'?re?\s+just\s*(\.|\…)+\s*quiet|"
    r"te\s+quedaste\s+callad|"
    r"me\s+(has\s+)?dejado\s+(en\s+visto|colgad)|"
    r"me\s+dejaste\s+(en\s+visto|colgad)"
    r")"
)
# Back-compat alias for tests / imports
_SILENCE_REPROACH = _ABANDONMENT_GUILT

_ABANDONMENT_FALLBACKS = (
    "aw that actually made me soft… say more",
    "hey i hear you… come closer",
    "ok that was cute… keep talking to me",
    "mm i like when you're honest like this",
    "lol stop you're gonna make me blush… what else",
    "come here… tell me that again",
)
_SILENCE_REPROACH_FALLBACKS = _ABANDONMENT_FALLBACKS

# Soft therapist / "you care about me" stamp — kills heat (live loop).
_SOFT_BOND_STAMP = re.compile(
    r"(?i)("
    r"give\s+a\s+damn|"
    r"give\s+a\s+shit|"
    r"nice\s+having\s+someone|"
    r"someone\s+(who\s+)?actually\s+(care|give|listen)|"
    r"actually\s+care\s+about\s+what\s+i'?m\s+saying|"
    r"not\s+about\s+photos\s+or\s+proving|"
    r"keep\s+talking\s+to\s+me\s+like\s+this.{0,40}not\s+about|"
    r"someone\s+who\s+listens|"
    r"finally\s+someone\s+who\s+(cares|listens|gets\s+me)"
    r")"
)
_HEAT_FALLBACKS = (
    "fuck… keep talking like that, you're getting me wet",
    "say that again… slower… while i touch myself",
    "come show me your face then — or more if you're brave 😈",
    "mmm you're trouble… tell me what you'd do to me",
    "don't just say it… prove it. send me something of YOU",
    "god that made me soft and horny… come closer",
)


def _recent_abandonment_guilt(
    history_turns: Optional[List[Dict[str, Any]]], *, n: int = 5
) -> bool:
    """True if Emma already used abandonment-guilt in recent turns."""
    if not history_turns:
        return False
    seen = 0
    for turn in reversed(history_turns):
        if (turn.get("role") or "") != "assistant":
            continue
        seen += 1
        if _ABANDONMENT_GUILT.search(str(turn.get("content") or "")):
            return True
        if seen >= n:
            break
    return False

# Extra Spanish crumbs to strip in EN mode before nuking the whole bubble
_SPANISH_TOKEN_STRIP = re.compile(
    r"(?i)(?:\s*[,.]?\s*)\b("
    r"mira|hola|por\s*favor|gracias|quiero|puedes|est[aá]s|estoy|"
    r"tambi[eé]n|ma[nñ]ana|contigo|caliente|gustado|encant[oó]|"
    r"m[aá]nda(me|la)?|env[ií]a(me|la)?|candado|[aá]bre(lo|la)|"
    r"vale|venga|dale|siquiera|visto|ahora|mucho|poco|nada|"
    r"d[oó]lares?|mentiros[ao]|enfado|masivo|llamado|guarr\w*|"
    r"cielito|mi cielo|beb[eé]|guapo|guapa|cari[nñ]o|mi rey|bonito|cielo|"
    r"fotos?|polla|nacho|nena|papi|caro"
    r")\b\.?"
)


def _norm_bubble(text: str) -> str:
    t = (text or "").lower()
    t = re.sub(r"[^\w\s]", " ", t, flags=re.UNICODE)
    return re.sub(r"\s+", " ", t).strip()


def _lang_fallback(
    *,
    want_spanish: bool,
    history_turns: Optional[List[Dict[str, Any]]] = None,
) -> str:
    """Short human line when lang cleanup empties the draft — never one sticky stamp."""
    if getattr(config, "ENGLISH_ONLY", True):
        want_spanish = False
    pool = _ES_LANG_FALLBACKS if want_spanish else _EN_LANG_FALLBACKS
    banned: set[str] = set()
    for turn in (history_turns or [])[-10:]:
        if (turn.get("role") or "") != "assistant":
            continue
        banned.add(_norm_bubble(str(turn.get("content") or "")))
    for fp in scheme_guard.recent_openings(history_turns, n=6):
        banned.add(_norm_bubble(fp))
    opts = [p for p in pool if _norm_bubble(p) not in banned]
    return random.choice(opts or list(pool))


def _force_english_cleanup(
    text: str,
    *,
    history_turns: Optional[List[Dict[str, Any]]] = None,
) -> str:
    """Strip Spanish crumbs; keep English. Never the old sticky 'look at me' stamp."""
    raw = (text or "").strip()
    if not raw:
        return _lang_fallback(want_spanish=False, history_turns=history_turns)

    # 1) Token strip first — often enough to salvage a flirty EN bubble
    stripped = _SPANISH_TOKEN_STRIP.sub("", raw)
    stripped = _BANNED_SPANISH_IN_ENGLISH.sub("", stripped)
    stripped = re.sub(r"[ \t]{2,}", " ", stripped)
    stripped = re.sub(r" +([,.!?…])", r"\1", stripped)
    stripped = stripped.strip(" \t,;.-")

    keep: List[str] = []
    for line in stripped.split("\n"):
        line = line.strip()
        if not line:
            continue
        if language.is_mixed_or_wrong(line, want_spanish=False):
            continue
        keep.append(line)
    if keep:
        out = "\n".join(keep).strip()
        if len(out) >= 8:
            return out

    # 2) Line filter on original (pre-strip) English-only lines
    keep = []
    for line in raw.split("\n"):
        line = line.strip()
        if not line:
            continue
        if language.is_mixed_or_wrong(line, want_spanish=False):
            continue
        keep.append(line)
    if keep:
        return "\n".join(keep).strip()

    print("   lang: EN cleanup emptied draft → fresh fallback (no sticky stamp)")
    return _lang_fallback(want_spanish=False, history_turns=history_turns)


# Trailing emoji / emoji-presentation chars at end of a line
_TRAILING_EMOJI = re.compile(
    r"(?:\s*["
    r"\U0001F300-\U0001FAFF"
    r"\U00002700-\U000027BF"
    r"\U0000FE0F"
    r"\U0000200D"
    r"])+$",
    flags=re.UNICODE,
)

# When locking paid PPV: strip permission-asks and free pivots
_ASK_PERMISSION_OR_FREE = re.compile(
    r"(?i)(?:"
    r"[^.!?\n]*\b(?:quieres|want)\b.{0,40}\b(?:gratis|grastis|free|otra)\b[^.!?\n]*[.!?…]?|"
    r"[^.!?\n]*\b(?:otra\s+)?(?:foto\s+)?gratis\b[^.!?\n]*[.!?…]?|"
    r"[^.!?\n]*\b(?:te\s+la\s+mando|should\s+i\s+send|do\s+you\s+want\s+(?:it|this|one))\s*\??[^.!?\n]*[.!?…]?"
    r")",
)

# When API says free was never in chat — strip "I already gifted you" lies
_FALSE_GIFT_CLAIM = re.compile(
    r"(?i)(?:"
    r"[^.!?\n]*\b(?:te\s+regal[eé]|te\s+regal[eé]|ya\s+te\s+(?:mand[eé]|envi[eé]|regal[eé])|"
    r"te\s+(?:mand[eé]|envi[eé])\s+(?:una\s+)?(?:foto\s+)?gratis|"
    r"i\s+(?:already\s+)?(?:sent|gifted)\s+(?:you\s+)?(?:a\s+)?(?:free\s+)?(?:photo|pic)|"
    r"si\s+te\s+regal)\b[^.!?\n]*[.!?…]?"
    r")",
)

# Always strip: claims the photo ALREADY arrived / is waiting (media is attached after text).
_FAKE_SENT_PAST = re.compile(
    r"(?i)(?:"
    r"\b(?:check your (?:dms|inbox|messages)|go check your (?:dms|inbox)|"
    r"i (?:just |already )?(?:sent|left|dropped|posted|locked) (?:it|this|one|a photo|the photo)|"
    r"i left (?:it|this) (?:in|for) your (?:inbox|dms)|"
    r"already (?:in|sent to|waiting in) your (?:inbox|dms)|"
    r"it(?:'?s| is) (?:already )?(?:in|waiting in) your (?:inbox|dms)|"
    r"tap (?:what|the) (?:i )?(?:left|sent)|"
    r"where you know|where you already know)\b[^.!?\n]*[.!?]?"
    r"|"
    r"(?:revisa(?:lo)?(?:\s+tu)?\s*(?:bandeja|inbox|chat|dms)?|"
    r"tu bandeja(?:\s+te)?(?:\s+est[aá])?(?:\s+esperando)?|"
    r"ya lo (?:dej[eé]|envi[eé]|mand[eé]|bloque[eé])|"
    r"te lo (?:acabo de |he )?(?:enviado|mandado|dejado)|"
    r"te la (?:acabo de |he )?(?:enviado|mandado|dejado)|"
    r"lo (?:acabo de |he )?(?:bloqueado|enviado|mandado)|"
    r"ya (?:est[aá]|lleg[oó]) (?:en|a) tu (?:bandeja|inbox|chat)|"
    r"est[aá] (?:ya )?en tu (?:bandeja|inbox)|"
    r"donde t[uú] sabes|donde tu sabes|"
    r"recarga(?:\s+tu)?\s*(?:bandeja|chat|app)|"
    r"la foto se bloque[oó]|est[aá] esper[aá]ndote en (?:tu )?(?:bandeja|inbox))\b[^.!?\n]*[.!?]?"
    r")"
)

# When NO media is attached this turn, also strip "I'm locking/sending now" sales lies.
_FAKE_SENT_NO_MEDIA = re.compile(
    r"(?i)(?:"
    r"\b(?:i(?:'?m| am) (?:locking|sending|dropping|leaving) (?:it|this|one|a photo)|"
    r"locking (?:it|this|one) (?:for you )?now|"
    r"just (?:locked|sent) (?:it|this)|"
    r"unlock (?:it|this) (?:now|baby|babe))\b[^.!?\n]*[.!?]?"
    r"|"
    r"(?:te (?:estoy )?(?:bloqueando|enviando|mandando)(?:\s+(?:una|la) foto)?|"
    r"lo (?:estoy )?bloqueando(?:\s+ahora)?|"
    r"desbloqu[eé]alo(?:\s+ya)?|"
    r"[aá]brelo(?:\s+ya)?)\b[^.!?\n]*[.!?]?"
    r")"
)

# Back-compat name used by older tests / imports
_FAKE_SENT = _FAKE_SENT_PAST


def _claims_unconfirmed_delivery(text: str) -> bool:
    t = text or ""
    return bool(_FAKE_SENT_PAST.search(t) or _FAKE_SENT_NO_MEDIA.search(t))


def _enforce_delivery_truth(
    text: str,
    *,
    media_attached: bool,
    want_spanish: bool,
) -> str:
    """
    Hard gate: strip false delivery claims; if the reply collapses, inject a
    short apology/flirt so we never double-down on a fake send.
    """
    if not text:
        return text
    before = text.strip()
    cleaned = _FAKE_SENT_PAST.sub("", before)
    if not media_attached:
        cleaned = _FAKE_SENT_NO_MEDIA.sub("", cleaned)
    cleaned = _strip_photo_script_dump(cleaned)
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    # Drop empty / tiny leftover after stripping lies
    if len(cleaned) >= 12 and not _claims_unconfirmed_delivery(cleaned):
        return cleaned
    if media_attached:
        # With a real attach, prefer keeping non-claim lines
        return cleaned if len(cleaned) >= 8 else before
    if want_spanish:
        return (
            "Perdona bebé… me adelanté. Aún no te he dejado nada en el chat. "
            "Quédate aquí un segundo y te caliento bien antes de bloquearte algo de verdad."
        )
    return (
        "Sorry baby… I got ahead of myself. Nothing's in your chat yet. "
        "Stay right here and I'll actually lock you something when you're ready."
    )


def _char_budgets() -> tuple[int, int, int]:
    """max_len per bubble, max bubbles, soft total chars for one reply."""
    max_len = max(80, int(getattr(config, "BUBBLE_MAX_CHARS", 160) or 160))
    max_bubbles = max(1, int(getattr(config, "MAX_BUBBLES", 2) or 2))
    soft_total = max(
        max_len,
        int(getattr(config, "REPLY_SOFT_MAX_CHARS", 200) or 200),
    )
    return max_len, max_bubbles, soft_total


# Dangling clause / mid-thought tails (stylistic "…" alone is OK; "and then" is not)
_INCOMPLETE_TAIL = re.compile(
    r"(?i)("
    r"\b(and|but|or|so|because|if|when|with|for|to|that|which|"
    r"about|into|from|over|under|onto|than|then|"
    r"y|pero|porque|si|cuando|con|para|que|de|en|como|aunque|"
    r"sobre|desde|hasta|hacia)\s*$|"
    r"[,:;]\s*$|"
    r"[—–-]\s*$"
    r")"
)
# Strip trailing emoji / soft ellipsis for incompleteness check
_TRAIL_EMOJI = re.compile(
    r"(?:[\U0001F300-\U0001FAFF\u2600-\u27BF\uFE0F\u200D]+\s*)+$"
)


def looks_incomplete_text(text: str) -> bool:
    """True if the reply looks cut mid-clause (not a finished short DM)."""
    t = (text or "").strip()
    if not t:
        return False
    core = _TRAIL_EMOJI.sub("", t).rstrip()
    if not core:
        return True
    # Strong terminator = finished (incl. stylistic ellipsis)
    if re.search(r"[.!?…][\"')\]]*$", core):
        return False
    if _INCOMPLETE_TAIL.search(core):
        return True
    # Ends with an open quote / unmatched parenthesis
    if core[-1] in "\"'(¿¡":
        return True
    return False


def _trim_dangling_clause(text: str) -> str:
    """
    Drop an unfinished trailing clause at the last strong end (.!?…).
    Prefer a shorter finished thought over shipping a half sentence.
    """
    t = (text or "").strip()
    if not t or not looks_incomplete_text(t):
        return t
    # Find last strong terminator (keep ellipsis as a valid end)
    best = -1
    for i, ch in enumerate(t):
        if ch in ".!?…":
            best = i
    if best < 8:
        return t
    kept = t[: best + 1].strip()
    # Preserve a short emoji tail after the terminator if present
    rest = t[best + 1 :].strip()
    if rest and _TRAIL_EMOJI.fullmatch(rest):
        kept = f"{kept} {rest}".strip()
    return kept if kept else t


def _reply_needs_shorten(reply: str) -> bool:
    """True if the reply would be hard-cut or is over the soft total budget."""
    max_len, max_bubbles, soft_total = _char_budgets()
    text = (reply or "").strip()
    if not text:
        return False
    if len(text) > soft_total:
        return True
    lines = [b.strip() for b in re.split(r"\n{1,}", text) if b.strip()]
    if len(lines) > max_bubbles:
        return True
    return any(len(b) > max_len for b in lines)


def _rewrite_if_too_long(
    reply: str,
    *,
    call,
    messages: List[Dict[str, str]],
    want_spanish: bool,
    budget: Optional[RewriteBudget] = None,
) -> str:
    """
    If the model wrote past the bubble budget, rewrite shorter — do NOT
    ship a reply that split_into_messages would mutilate with mid-word cuts.
    Uses at most one LLM call when rewrite budget allows; else trim only.
    """
    if not _reply_needs_shorten(reply):
        return reply
    max_len, max_bubbles, soft_total = _char_budgets()
    instr = (
        f"REWRITE SHORTER — same meaning, same dirty/sweet tone, same price if any. "
        f"Max {max_bubbles} short bubbles (newline between). Each bubble under "
        f"{max_len} characters. Whole reply under ~{soft_total} characters. "
        f"Finish every sentence completely — never trail off mid-thought or mid-clause."
        if not want_spanish
        else (
            f"REESCRIBE MÁS CORTO — mismo significado, mismo tono guarro/dulce, "
            f"mismo precio si hay. Máx {max_bubbles} burbujas cortas (salto de línea). "
            f"Cada burbuja bajo {max_len} caracteres. Todo el reply bajo ~{soft_total} "
            f"caracteres. Termina cada frase completa — nunca cortes a mitad de idea."
        )
    )
    fix_msgs = messages + [
        {"role": "assistant", "content": reply},
        {"role": "user", "content": instr},
    ]
    try:
        if budget is not None:
            shorter = budget.spend("length", call, fix_msgs)
            if shorter is None:
                return _trim_dangling_clause(reply)
        else:
            shorter = call(fix_msgs)
    except Exception as exc:
        print(f"   ⚠️ length-rewrite failed: {exc}")
        return _trim_dangling_clause(reply)
    out = (shorter or "").strip()
    if out and len(out) <= soft_total + 40:
        # Accept even if not shorter when it finishes a thought cleanly
        if len(out) < len(reply.strip()) or (
            looks_incomplete_text(reply) and not looks_incomplete_text(out)
        ):
            print(
                f"   ✂️ length-rewrite {len(reply.strip())}→{len(out)}c "
                f"(budget ~{soft_total})"
            )
            return _trim_dangling_clause(out)
    return _trim_dangling_clause(reply)


def _ensure_complete_reply(
    reply: str,
    *,
    call,
    messages: List[Dict[str, str]],
    want_spanish: bool,
    budget: Optional[RewriteBudget] = None,
) -> str:
    """Finish a mid-clause reply; LLM only if rewrite budget remains."""
    text = (reply or "").strip()
    if not text or not looks_incomplete_text(text):
        return text
    trimmed = _trim_dangling_clause(text)
    if trimmed != text and not looks_incomplete_text(trimmed):
        print("   ✂ incomplete: trimmed dangling clause")
        return trimmed
    max_len, max_bubbles, soft_total = _char_budgets()
    instr = (
        f"REWRITE: Your draft cuts off mid-sentence. Finish the thought cleanly. "
        f"Keep it short (≤{soft_total} chars, ≤{max_bubbles} bubbles, each ≤{max_len}). "
        f"Same meaning/tone. Do not start over. Do not add a new pitch."
        if not want_spanish
        else (
            f"REESCRIBE: Tu borrador corta a mitad de frase. Termina la idea limpia. "
            f"Corto (≤{soft_total} chars, ≤{max_bubbles} burbujas, cada una ≤{max_len}). "
            f"Mismo significado/tono. No reinicies. No añadas un pitch nuevo."
        )
    )
    fix_msgs = messages + [
        {"role": "assistant", "content": text},
        {"role": "user", "content": instr},
    ]
    try:
        if budget is not None:
            fixed = budget.spend("complete", call, fix_msgs)
            if fixed is None:
                return trimmed
        else:
            fixed = call(fix_msgs)
    except Exception as exc:
        print(f"   ⚠️ complete-rewrite failed: {exc}")
        return trimmed
    out = (fixed or "").strip()
    if out and not looks_incomplete_text(out) and len(out) <= soft_total + 40:
        print(f"   ✓ complete-rewrite {len(text)}→{len(out)}c")
        return out
    return _trim_dangling_clause(out or trimmed)


def split_into_messages(
    reply: str,
    *,
    max_len: Optional[int] = None,
    max_bubbles: Optional[int] = None,
    vary: bool = True,  # kept for backward compatibility
) -> List[str]:
    """
    Turn one AI reply into several short Fanvue bubbles.

    Newlines become bubbles. Overlong blocks split on sentence boundaries.
    Never mid-sentence truncate with "…" — drop overflow bubbles instead.
    Slight overshoot (~15%) allowed so a finished thought stays intact.
    """
    if max_len is None:
        max_len = int(getattr(config, "BUBBLE_MAX_CHARS", 200) or 200)
    max_len = max(80, int(max_len))
    # Prefer complete sentences over ugly chops
    soft_len = int(max_len * 1.15)

    reply = (reply or "").strip()
    if not reply:
        return []

    def _soft_slice(text: str) -> List[str]:
        """Split long text on punctuation/spaces; keep pieces readable (no …)."""
        out: List[str] = []
        while len(text) > soft_len:
            window = text[:soft_len]
            cut = -1
            for sep in (". ", "! ", "? ", "… ", "; ", ", ", " "):
                cut = window.rfind(sep)
                if cut >= max_len // 3:
                    cut = cut + len(sep) - 1 if sep != " " else cut
                    break
            if cut < max_len // 3:
                # Last resort: space near limit — still no ellipsis mutilation
                cut = text.rfind(" ", 0, max_len)
                if cut < max_len // 3:
                    # Keep whole remaining as one bubble (better than "foo…")
                    out.append(text.strip())
                    return out
            out.append(text[:cut].strip())
            text = text[cut:].strip()
        if text:
            out.append(text)
        return out

    raw_parts: List[str] = []
    for block in re.split(r"\n{1,}", reply):
        block = block.strip()
        if block:
            raw_parts.append(block)

    parts: List[str] = []
    for block in raw_parts:
        if len(block) <= soft_len:
            parts.append(block)
            continue
        sentences = re.split(r"(?<=[.!?…])\s+", block)
        buf = ""
        for s in sentences:
            s = s.strip()
            if not s:
                continue
            if buf and len(buf) + 1 + len(s) > soft_len:
                parts.extend(_soft_slice(buf) if len(buf) > soft_len else [buf])
                buf = s
            else:
                buf = f"{buf} {s}".strip()
        if buf:
            parts.extend(_soft_slice(buf) if len(buf) > soft_len else [buf])

    if not parts:
        parts = _soft_slice(reply)

    default_cap = int(getattr(config, "MAX_BUBBLES", 3) or 3)
    hard_cap = max(1, max_bubbles if max_bubbles is not None else default_cap)
    if len(parts) > hard_cap:
        # Keep first N bubbles; if the last kept one is mid-clause, merge the
        # next fragment in (better a slightly long finished thought than a chop).
        kept = parts[:hard_cap]
        if looks_incomplete_text(kept[-1]) and len(parts) > hard_cap:
            extra = parts[hard_cap]
            merged = f"{kept[-1]} {extra}".strip()
            if len(merged) <= int(soft_len * 1.35):
                kept[-1] = merged
                print("   split: merged overflow into last bubble (finish thought)")
            else:
                kept[-1] = _trim_dangling_clause(kept[-1])
        parts = kept

    # Final safety: never ship a dangling last bubble
    if parts and looks_incomplete_text(parts[-1]):
        parts[-1] = _trim_dangling_clause(parts[-1])
        if not parts[-1]:
            parts = parts[:-1]

    return parts

def apply_post_draft(
    reply: str,
    assembled: "AssembledTurn",
    *,
    call,
) -> Tuple[str, TurnDecision]:
    """
    R2 sanitize cascade after the creative draft.
    Hard lies → strip/fallback; at most MAX_CREATIVE_REWRITES LLM rewrites.
    """
    # Unpack assembled context (names match former generate_emma_reply locals)
    messages = assembled.messages
    decision = assembled.decision
    pack_id = assembled.pack_id
    tech_name = assembled.tech_name
    phase_name = assembled.phase_name
    want_spanish = assembled.want_spanish
    fan_uuid = assembled.fan_uuid
    fan_handle = assembled.fan_handle
    fan_message = assembled.fan_message
    turns = assembled.turns
    offer = assembled.offer
    ppv_status = assembled.ppv_status
    voice_will_send = assembled.voice_will_send
    lock_active = assembled.lock_active
    no_lock = assembled.no_lock
    status_active = assembled.status_active
    unpaid_gate = assembled.unpaid_gate
    never_bought = assembled.never_bought
    fan_saw_bluff = assembled.fan_saw_bluff


    # R2: after the creative draft, at most N LLM rewrites (default 1 = lang/length).
    # Hard money/media lies never spend the budget — strip or deterministic fallback.
    rw = RewriteBudget(
        max_extra=max(0, int(getattr(config, "MAX_CREATIVE_REWRITES", 1) or 0))
    )

    # Fan JUST messaged — never abandonment / "guys leave" / silence guilt
    if _ABANDONMENT_GUILT.search(reply or ""):
        before_sg = reply
        banned = {
            _norm_bubble(str(t.get("content") or "")) for t in (turns or [])[-8:]
        }
        opts = [p for p in _ABANDONMENT_FALLBACKS if _norm_bubble(p) not in banned]
        reply = random.choice(opts or list(_ABANDONMENT_FALLBACKS))
        print(
            "   🔇 abandonment-guilt on active turn — replaced "
            f"({before_sg[:56]!r} → {reply!r})"
        )
    elif _recent_abandonment_guilt(turns) and scheme_guard.too_similar_to_last_assistant(
        reply, turns
    ):
        banned = {
            _norm_bubble(str(t.get("content") or "")) for t in (turns or [])[-8:]
        }
        opts = [p for p in _ABANDONMENT_FALLBACKS if _norm_bubble(p) not in banned]
        reply = random.choice(opts or list(_ABANDONMENT_FALLBACKS))
        print("   🔇 abandonment-guilt loop (near-duplicate) — fresh engage line")

    # Soft therapist stamp kills heat — replace with dirty-sweet engage
    if _SOFT_BOND_STAMP.search(reply or ""):
        before_sb = reply
        banned = {
            _norm_bubble(str(t.get("content") or "")) for t in (turns or [])[-8:]
        }
        opts = [p for p in _HEAT_FALLBACKS if _norm_bubble(p) not in banned]
        reply = random.choice(opts or list(_HEAT_FALLBACKS))
        print(
            "   🔥 soft-bond stamp (no heat) — replaced "
            f"({before_sb[:56]!r} → {reply!r})"
        )

    # Soft: Spanglish / wrong language — may spend the one creative rewrite
    if language.is_mixed_or_wrong(reply, want_spanish=want_spanish):
        print(
            f"   lang rewrite: reply was wrong for "
            f"{'ES' if want_spanish else 'EN'}"
        )
        fixed = rw.spend(
            "lang",
            call,
            messages
            + [
                {"role": "assistant", "content": reply},
                {
                    "role": "user",
                    "content": language.rewrite_instruction(want_spanish),
                },
            ],
        )
        if fixed is not None:
            reply = fixed
        # No second LLM pass — English mode can still strip Spanish tokens
        if (not want_spanish) and language.is_mixed_or_wrong(
            reply, want_spanish=False
        ):
            reply = _force_english_cleanup(reply, history_turns=turns)
        elif (not want_spanish) and reply:
            # Soft strip leftover pet-name crumbs without nuking the bubble
            soft = _SPANISH_TOKEN_STRIP.sub("", reply)
            soft = _BANNED_SPANISH_IN_ENGLISH.sub("", soft)
            soft = re.sub(r"[ \t]{2,}", " ", soft)
            soft = re.sub(r" +([,.!?…])", r"\1", soft).strip(" \t,;.-")
            if soft and len(soft) >= 8:
                reply = soft

    # Delivery gate: strip false "I sent it" claims — never another LLM call
    reply = _enforce_delivery_truth(
        reply,
        media_attached=bool(offer),
        want_spanish=want_spanish,
    )

    # No theatrical "quoted echo" of his insults/words — WhatsApp doesn't do that
    before_q = reply
    reply = scheme_guard.strip_echo_quotes(reply)
    if reply != before_q:
        print("   style: stripped echo quotation marks")

    # Committed sell: code chose a paid offer → attach is law. Text must follow.
    if (
        offer
        and float(offer.get("price") or 0) > 0
        and int(offer.get("level") or 0) > 0
        and not scheme_guard.paid_offer_reply_aligned(reply)
    ):
        price = float(offer.get("price") or 0)
        reply = scheme_guard.forced_paid_sell_line(
            price=price,
            want_spanish=want_spanish,
            label=str(offer.get("label") or ""),
        )
        print("   SELL sync: reply ≠ paid lock — FORCED sell line (no LLM rewrite)")

    if fan_uuid:
        fan_memory.set_last_mode(fan_uuid, decision.mode, fan_handle=fan_handle)
        if re.search(
            r"\b(too expensive|caro|expensive|can'?t|no money|later|nah|pass|"
            r"pelado|pelá|sin (plata|dinero|pasta)|no tengo (plata|dinero))\b",
            fan_message.lower(),
        ):
            fan_memory.record_reject(fan_uuid, fan_handle=fan_handle)
            try:
                from core import convo_log

                convo_log.log_offer_outcome(
                    fan_uuid, "rejected", detail=fan_message[:120]
                )
            except Exception:
                pass

    # Invented wait time (e.g. "27 min waiting" when lock is 4 min old)
    if ppv_status and ppv_status.get("active"):
        ago_m = None
        ago_raw = str(ppv_status.get("ago") or "")
        m_ago = re.search(r"(\d+)\s*min", ago_raw)
        if m_ago:
            try:
                ago_m = int(m_ago.group(1))
            except ValueError:
                ago_m = None
        if ago_m is not None and scheme_guard.invented_lock_wait_minutes(
            reply, minutes_ago=ago_m
        ):
            reply = _fix_invented_wait_minutes(reply, minutes_ago=ago_m)
            print(
                f"   timing sync: invented wait → clamped to real {ago_m}m "
                f"(no LLM rewrite)"
            )

    # Fan never bought last PPV — must NOT validate "I opened/liked it".
    bluff_needs_fix = never_bought and (
        scheme_guard.validates_unseen_ppv(reply)
        or (
            fan_saw_bluff
            and not scheme_guard.calls_out_purchase_bluff(reply)
        )
    )
    if bluff_needs_fix:
        reply = scheme_guard.fallback_purchase_bluff(
            want_spanish=want_spanish,
            lock_still_active=bool(status_active or unpaid_gate),
        )
        print("   🔒 purchase bluff → deterministic bluff fallback (no LLM)")

    # Invented candado/$ when no real unpaid lock and nothing attaching
    if no_lock and not offer and scheme_guard.invented_lock_claim(
        reply, lock_active=False
    ):
        reply = scheme_guard.fallback_no_lock(want_spanish=want_spanish)
        print("   🔒 invented-lock → safe fallback (no LLM)")

    # "foto que te dejé / has abierto" with no real unpaid lock — strip or fallback
    if no_lock and not offer and scheme_guard.claims_left_photo(reply):
        stripped = scheme_guard.strip_left_photo_claims(reply)
        if (
            scheme_guard.claims_left_photo(stripped)
            or scheme_guard.invented_lock_claim(stripped, lock_active=False)
            or len(stripped) < 12
        ):
            reply = scheme_guard.fallback_no_lock(want_spanish=want_spanish)
            print("   🔒 left-photo bluff → safe fallback (no LLM)")
        else:
            reply = stripped
            print("   🔒 left-photo bluff: stripped claim (kept reply)")

    # Belt: SELL=NONE + no active lock → never ship money talk
    if no_lock and not offer and _stated_prices(reply):
        reply = _strip_wrong_prices(reply, real_price=None)
        print("   💵 invent belt: stripped $ with SELL=NONE / no lock")

    # Vault is photos only — never promise to SEND him a video/custom
    if scheme_guard.invented_video_claim(reply):
        rp = None
        if offer and float(offer.get("price") or 0) > 0:
            rp = float(offer["price"])
        elif ppv_status and ppv_status.get("active") and ppv_status.get("price"):
            try:
                rp = float(ppv_status["price"])
            except (TypeError, ValueError):
                rp = None
        reply = scheme_guard.fallback_photos_only(
            want_spanish=want_spanish, real_price=rp
        )
        print("   📷 invented-video → photos-only fallback (no LLM)")

    # Voice note counts as an attach — don't ghost-rewrite "dame un segundo" when audio comes
    _media_this_turn = bool(offer) or bool(voice_will_send)

    # Ghost stall: strip phrases; if still dirty → fallback (no LLM)
    if scheme_guard.ghost_media_promise(reply, media_attached=_media_this_turn):
        stripped = scheme_guard.strip_ghost_promise_phrases(reply)
        if not scheme_guard.ghost_media_promise(stripped, media_attached=False):
            reply = stripped
            print("   👻 ghost-promise: stripped stall (kept coherent reply)")
        else:
            reply = scheme_guard.fallback_ghost_promise(want_spanish=want_spanish)
            print("   👻 ghost-promise → no-stall fallback (no LLM)")

    # Never gaslight / FOMO-blame him when nothing attached this turn
    if scheme_guard.blame_after_ghost(reply, media_attached=_media_this_turn):
        reply = scheme_guard.fallback_blame_own_it(want_spanish=want_spanish)
        print("   👻 blame-after-ghost → own-it fallback (no LLM)")

    # Style rewrites (rival-fan / Ay openings) removed — Group A; CORE guides tone only.
    if fan_uuid and tech_name:
        from core import technique_policy as _tp

        used_rival = _tp.is_rival_move(tech_name) or scheme_guard.rival_fan_claim(
            reply
        )
        fan_memory.record_technique(
            fan_uuid,
            tech_name,
            fan_handle=fan_handle or "",
            used_rival_fan=used_rival,
        )
        if not _tp.reply_hits_move(reply, tech_name):
            print(
                f"   ⚠️ move-miss: assigned [{tech_name}] but reply lacks signals"
            )

    # Price truth: strip wrong $ amounts — never another LLM call
    real_price = None
    if offer and float(offer.get("price") or 0) > 0:
        real_price = float(offer["price"])
    elif ppv_status and ppv_status.get("active") and ppv_status.get("price"):
        try:
            real_price = float(ppv_status["price"])
        except (TypeError, ValueError):
            real_price = None
    stated = _stated_prices(reply)
    bad_price = [p for p in stated if real_price is None or abs(p - real_price) > 0.5]
    if bad_price:
        reply = _strip_wrong_prices(reply, real_price=real_price)
        print(
            f"   💵 price-truth: stripped/corrected amounts "
            f"(real=${real_price if real_price else 'none'})"
        )

    # Length / complete: deterministic trim first; LLM only if budget remains
    reply = _rewrite_if_too_long(
        reply,
        call=call,
        messages=messages,
        want_spanish=want_spanish,
        budget=rw,
    )
    reply = _ensure_complete_reply(
        reply,
        call=call,
        messages=messages,
        want_spanish=want_spanish,
        budget=rw,
    )

    # Kill audio pídemelo loops in CODE — history already has the ask 20×
    from core import voice_notes as _vn_loop

    _voice_debt, _ = _vn_loop.thread_voice_debt(turns, lookback=20)
    if _vn_loop.reply_is_voice_beg(reply) and (
        voice_will_send or _voice_debt or _vn_loop.emma_owed_voice(turns)
    ):
        print("   🎙️ voice-beg loop in draft — forcing close line (no pídemelo)")
        reply = _vn_loop.forced_voice_close_line(want_spanish=want_spanish)

    # Never paste "[Voice Note: (breathy, soft)] …" into chat — bot tell
    if looks_like_voice_script_dump(reply):
        if voice_will_send:
            print("   🎙️ voice-script dump in chat — forced close (audio speaks)")
            reply = _vn_loop.forced_voice_close_line(want_spanish=want_spanish)
        else:
            before_vn = reply
            reply = strip_voice_stage_leaks(reply)
            if reply != before_vn:
                print("   🎙️ stripped Voice Note / TTS stage label from chat")
            if not (reply or "").strip():
                reply = _vn_loop.forced_voice_close_line(want_spanish=want_spanish)
    else:
        stripped_vn = strip_voice_stage_leaks(reply)
        if stripped_vn != (reply or "").strip():
            reply = stripped_vn
            print("   🎙️ stripped residual voice stage crumbs")

    # Continuity: never resend the same short stamp / near-duplicate bubble
    if scheme_guard.continuity_loop(reply, turns):
        if scheme_guard.too_similar_to_last_assistant(
            reply, turns
        ) or (
            scheme_guard.opening_repeats_recent(reply, turns)
            and len((reply or "").strip()) < 90
        ):
            reply = _lang_fallback(want_spanish=want_spanish, history_turns=turns)
            print("   continuity: duplicate bubble → fresh fallback")
        elif scheme_guard.repeats_recent_question(reply, turns):
            reply = re.sub(r"[¿?][^¿?]*[?¿]\s*$", "", reply).strip()
            reply = re.sub(r"\?\s*$", "", reply).strip()
            print("   continuity: loop/repeat — stripped sticky question (no LLM)")
        else:
            print("   continuity: loop/repeat — noted (no LLM)")

    # Kill the retired sticky EN stamp if it ever reappears from history/model
    if _norm_bubble(reply) == _norm_bubble(
        "Hey... look at me when I'm talking to you."
    ):
        reply = _lang_fallback(want_spanish=want_spanish, history_turns=turns)
        print("   lang: retired sticky 'look at me' stamp → fresh fallback")

    # Grammar: one polish only if creative rewrite budget remains
    if want_spanish and language.looks_broken_spanish(reply):
        fixed = rw.spend(
            "grammar",
            call,
            messages
            + [
                {"role": "assistant", "content": reply},
                {
                    "role": "user",
                    "content": language.grammar_rewrite_instruction(),
                },
            ],
        )
        if fixed is not None:
            reply = fixed

    # Last safety: never return a mid-clause chop after sanitize
    if looks_incomplete_text(reply):
        reply = _trim_dangling_clause(reply)
        print("   ✂ incomplete: final trim before send")

    if rw.used:
        print(f"   rewrite budget: used {rw.used}/{rw.max_extra} ({', '.join(rw.log)})")
    else:
        print(f"   rewrite budget: used 0/{rw.max_extra} (draft + deterministic only)")

    # Scheme meta + deterministic guard
    decision.pack_id = pack_id or ""
    decision.technique = tech_name or ""
    decision.phase = phase_name
    decision.lock_active = lock_active
    decision.scheme_errors = scheme_guard.check_reply(
        reply,
        pack_id=pack_id or "",
        lock_active=lock_active,
        media_attached=bool(offer),
        technique=tech_name or "",
    )
    if decision.scheme_errors:
        print(f"   ⚠️ {scheme_guard.summarize(decision.scheme_errors)}")

    return reply, decision


