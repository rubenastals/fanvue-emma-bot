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

# Fake countdown / price urgency as if a lock already exists
_CLAIM_FAKE_LOCK_URGENCY = re.compile(
    r"(?i)("
    r"vence(?:n)?\s+en\s+\d+|"
    r"quedan?\s+\d+\s*min|"
    r"\d+\s*minutitos|"
    r"(?:in|within)\s+\d+\s*min|"
    r"son\s+\$\s*\d+|"
    r"\$\s*\d+\s+y\s+qued|"
    r"only\s+\$\s*\d+.{0,40}(?:min|left|left)"
    r")"
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

# Promising video/custom we do not have in the photo vault
_CLAIM_FAKE_VIDEO = re.compile(
    r"(?i)\b("
    r"v[ií]deo|video|clip|4k|"
    r"te grabo|grabarte|grabarme|"
    r"empiezo a grabar|voy a grabar|grabe (algo|un|una)|"
    r"grabo (algo|un|una)|recording (a |you )|"
    r"custom (video|clip|vid)"
    r")\b"
)

# Sticky "another fan is messaging me" jealousy bit — overused by creative
_CLAIM_RIVAL_FAN = re.compile(
    r"(?i)("
    r"otro\s+fan|"
    r"otra\s+fan|"
    r"another\s+fan|"
    r"other\s+fan|"
    r"me\s+est[aá]\s+entrando\s+un\s+mensaje|"
    r"entrando\s+un\s+mensaje\s+de\s+otro|"
    r"antes\s+de\s+que\s+le\s+responda|"
    r"before\s+i\s+(answer|reply)\s+(him|them|her)|"
    r"pidi[eé]ndome\s+cositas|"
    r"asking\s+me\s+for\s+(stuff|things|pics|nudes)"
    r")"
)

# Stall / fake prep when nothing attaches this turn
_GHOST_PROMISE = re.compile(
    r"(?i)\b("
    r"dame\s+un\s+(segundo|momento|rato)|"
    r"te\s+preparo|"
    r"estoy\s+preparando|"
    r"voy\s+a\s+(mandar|enviar|pasar|prepar)|"
    r"te\s+(mando|env[ií]o|paso)\s+(algo|una\s+foto|una)|"
    r"ya\s+te\s+(la\s+)?(mando|env[ií]o)|"
    r"wait\s+(a\s+)?(sec|second|moment)|"
    r"i('?m| am)\s+(preparing|about\s+to\s+send)|"
    r"let\s+me\s+(send|prep|prepare|grab)"
    r")\b"
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

    # LOCK STATUS obedience — inventing candado OR fake countdown/price is severity 3
    if lock_active is False and (
        _CLAIM_LOCK_WAITING.search(text) or _CLAIM_FAKE_LOCK_URGENCY.search(text)
    ):
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
    if _CLAIM_FAKE_VIDEO.search(text):
        errs.append(
            {
                "rule": "SCHEME",
                "severity": 3,
                "what": "promised video/custom — vault is photos only",
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


def invented_lock_claim(reply: str, *, lock_active: Optional[bool]) -> bool:
    """True when reply pretends a waiting lock exists but LOCK STATUS=none."""
    if lock_active is not False:
        return False
    text = (reply or "").strip()
    if not text:
        return False
    return bool(
        _CLAIM_LOCK_WAITING.search(text) or _CLAIM_FAKE_LOCK_URGENCY.search(text)
    )


def invented_video_claim(reply: str) -> bool:
    """True when reply promises a video/custom we cannot attach."""
    text = (reply or "").strip()
    if not text:
        return False
    return bool(_CLAIM_FAKE_VIDEO.search(text))


def rival_fan_claim(reply: str) -> bool:
    """True when reply uses the sticky 'otro fan me escribe' jealousy bit."""
    text = (reply or "").strip()
    if not text:
        return False
    return bool(_CLAIM_RIVAL_FAN.search(text))


def ghost_media_promise(reply: str, *, media_attached: bool) -> bool:
    """True when she stalls/'prepares' a photo but nothing attaches this turn."""
    if media_attached:
        return False
    text = (reply or "").strip()
    if not text:
        return False
    return bool(_GHOST_PROMISE.search(text))


# Reply asks HIM to send his face/body pic (wrong direction for a PPV attach turn)
_ASK_HIS_MEDIA = re.compile(
    r"(?i)\b("
    r"(m[aá]nda|env[ií]a|pasa|show|send)\w*\s+"
    r"(me\s+)?(una\s+|tu\s+|your\s+)?"
    r"(foto|pic|photo|selfie|carita|cara|face|cuerpo|body)\s*"
    r"(tuya|tuyo|your|de\s+ti|of\s+you)?|"
    r"quiero\s+ver(te)?\s+(la\s+)?(carita|cara|face|tu\s+foto)|"
    r"foto\s+tuya|your\s+(pic|photo|face|selfie)|"
    r"m[aá]ndame\s+una\s+foto\s+tuya|"
    r"send\s+me\s+(a\s+)?(pic|photo|selfie)"
    r")\b"
)

# Reply actually sells / locks HER paid photo this turn
_SELLS_HER_LOCK = re.compile(
    r"(?i)\b("
    r"candado|unlock|desbloque|lock(ing|ed)?|"
    r"bloque(o|ando|ada)|te\s+(lo|la)\s+bloqueo|"
    r"\$\s*\d+|€\s*\d+|precio|"
    r"abre(lo|la)?|"
    r"(esta|esta)\s+foto|"
    r"mir(a|alo|ala)\s+(esto|esta)|"
    r"te\s+(la|lo)\s+(dejo|mando|env[ií]o)\s+(aqu[ií]|locked|bloquead)|"
    r"verme\s+as[ií]|en\s+cuatro|hilito|thong|tetas?|culo|pussy|"
    r"esta\s+foto\s+m[ií]a|foto\s+m[ií]a|m[aá]s\s+guarra"
    r")\b"
)


_CLAIM_WAIT_MINUTES = re.compile(
    r"(?i)(?:"
    r"(?:llevo|lleva|llevas|esperando)\s+(\d{1,3})\s*minut|"
    r"(\d{1,3})\s*minut|"
    r"(?:hace|for|waiting)\s+(\d{1,3})\s*min|"
    # "6 minutos, 27…" — second number is also a wait claim
    r"minut\w*[\s,…]+(\d{1,3})"
    r")"
)


def invented_lock_wait_minutes(
    reply: str, *, minutes_ago: Optional[int] = None
) -> bool:
    """
    True if reply claims the lock has been waiting much longer than reality.
    minutes_ago = how long the CURRENT lock has actually been in chat.
    """
    if minutes_ago is None:
        return False
    text = (reply or "").strip()
    if not text:
        return False
    claimed_vals = []
    for m in _CLAIM_WAIT_MINUTES.finditer(text):
        for g in m.groups():
            if g is None:
                continue
            try:
                claimed_vals.append(int(g))
            except ValueError:
                pass
    # Allow ±2 min slack; flag wild inventions (e.g. 27 vs 4)
    return any(c > minutes_ago + 2 for c in claimed_vals)


def paid_offer_reply_aligned(reply: str) -> bool:
    """
    True if the creative reply matches attaching Emma's paid lock this turn.

    False when DeepSeek went another direction (e.g. asked for HIS face) —
    code must not attach a PPV that contradicts the text.
    """
    text = (reply or "").strip()
    if not text:
        return False
    if _ASK_HIS_MEDIA.search(text):
        return False
    return bool(_SELLS_HER_LOCK.search(text))


def history_has_rival_fan(history_turns: Optional[List[Dict[str, Any]]]) -> bool:
    """True if any recent Emma (assistant) turn already used the rival-fan bit."""
    if not history_turns:
        return False
    for turn in history_turns[-16:]:
        if (turn.get("role") or "") != "assistant":
            continue
        if rival_fan_claim(str(turn.get("content") or "")):
            return True
    return False


# Sticky Spanish openings DeepSeek loves to stamp every turn
_STICKY_OPEN = re.compile(
    r"(?i)^\s*("
    r"ay+\s*,?\s*"
    r"(?:qu[eé]\s+)?"
    r"(?:rico|rica|pill[ií]n|pillina|loco|loca|guapo|guapa|cielo|mi\s+vida|"
    r"beb[eé]|bebe|amor|cari[nñ]o|travieso|malo|malito|"
    r"lindo|linda|hermoso|hermosa)"
    r")"
)

_OPEN_AY = re.compile(r"(?i)^\s*ay+\s*[,.…!]*\s*")


def opening_fingerprint(text: str) -> str:
    """Normalize the first ~6 words for anti-repeat (lowercase, no emoji/punct)."""
    first = (text or "").strip().split("\n", 1)[0]
    first = re.sub(r"[^\w\sÁÉÍÓÚÜÑáéíóúüñ]", " ", first, flags=re.UNICODE)
    words = first.lower().split()[:6]
    return " ".join(words)


def recent_openings(
    history_turns: Optional[List[Dict[str, Any]]], *, n: int = 6
) -> List[str]:
    """Fingerprints of Emma's last n openings."""
    out: List[str] = []
    if not history_turns:
        return out
    for turn in history_turns:
        if (turn.get("role") or "") != "assistant":
            continue
        fp = opening_fingerprint(str(turn.get("content") or ""))
        if fp:
            out.append(fp)
    return out[-n:]


_EMOJI_RE = re.compile(
    r"[\U0001F300-\U0001FAFF\U00002700-\U000027BF"
    r"\U0001F600-\U0001F64F\U0001F900-\U0001F9FF"
    r"\u2600-\u26FF\u2700-\u27BF]+",
    flags=re.UNICODE,
)


def recent_emojis(
    history_turns: Optional[List[Dict[str, Any]]], *, n: int = 6
) -> List[str]:
    """Emoji combos used in Emma's last n turns — used to ban repeats."""
    seen: List[str] = []
    if not history_turns:
        return seen
    for turn in history_turns:
        if (turn.get("role") or "") != "assistant":
            continue
        hits = _EMOJI_RE.findall(str(turn.get("content") or ""))
        if hits:
            seen.append(" ".join(hits))
    return seen[-n:]


def sticky_ay_open(text: str) -> bool:
    """True when reply opens with the overused 'Ay, qué rico/pillín…' stamp."""
    first = (text or "").strip().split("\n", 1)[0]
    return bool(_STICKY_OPEN.search(first) or _OPEN_AY.match(first))


def opening_repeats_recent(
    reply: str, history_turns: Optional[List[Dict[str, Any]]], *, n: int = 5
) -> bool:
    """True if this reply's opening matches one of Emma's last n openings."""
    fp = opening_fingerprint(reply)
    if not fp or len(fp) < 4:
        return False
    recent = recent_openings(history_turns, n=n)
    if fp in recent:
        return True
    # Soft match: same first 3 tokens (Ay qué rico ≈ Ay qué rico eres)
    head = " ".join(fp.split()[:3])
    if len(head) >= 6 and any(" ".join(r.split()[:3]) == head for r in recent):
        return True
    return False


def summarize(errors: List[Dict[str, Any]]) -> str:
    if not errors:
        return "scheme_ok"
    bits = [f"{e.get('rule')}:{e.get('what', '')[:40]}" for e in errors[:3]]
    return "scheme_fail " + " | ".join(bits)
