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
    r"te\s+la\s+estoy\s+dejando|"
    r"mira\s+lo\s+que\s+te\s+tengo|"
    r"te\s+tengo\s+preparado|"
    r"wait\s+(a\s+)?(sec|second|moment)|"
    r"i('?m| am)\s+(preparing|about\s+to\s+send)|"
    r"let\s+me\s+(send|prep|prepare|grab)"
    r")\b"
)

# Blames the fan / FOMO after a ghost send (nothing attached)
_BLAME_AFTER_GHOST = re.compile(
    r"(?i)\b("
    r"se\s+te\s+fue\s+la\s+oportunidad|"
    r"you\s+missed\s+(your\s+)?chance|"
    r"ya\s+deber[ií]a\s+estar\s+ah[ií]|"
    r"de\s+verdad\s+que\s+te\s+la\s+mand[eé]|"
    r"algo\s+fall[oó]|se\s+supone\s+que\s+ya|"
    r"i\s+(already\s+)?sent\s+it|"
    r"should\s+(already\s+)?be\s+(there|in\s+your)"
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


def strip_ghost_promise_phrases(reply: str) -> str:
    """
    Remove stall/prep clauses without replacing the whole coherent reply.
    Prefer this over fallback_ghost_promise when the rest of the draft is fine.
    """
    text = (reply or "").strip()
    if not text:
        return text
    cleaned = _GHOST_PROMISE.sub("", text)
    cleaned = re.sub(r"\s{2,}", " ", cleaned)
    cleaned = re.sub(r"\s+([,.!?…])", r"\1", cleaned)
    cleaned = re.sub(r"^[.…,\s]+", "", cleaned)
    return cleaned.strip() or text


def blame_after_ghost(reply: str, *, media_attached: bool) -> bool:
    """True when she gaslights / FOMO-blames him after nothing attached."""
    if media_attached:
        return False
    text = (reply or "").strip()
    if not text:
        return False
    return bool(_BLAME_AFTER_GHOST.search(text))


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
# NOTE: $ / € must stay OUTSIDE \b…\b — "$4" has no word boundary before $.
_SELLS_HER_LOCK = re.compile(
    r"(?i)("
    r"\b("
    r"candado|unlock|desbloque|lock(ing|ed)?|"
    r"bloque(o|ando|ada)|te\s+(lo|la)\s+bloqueo|"
    r"precio|"
    r"abre(lo|la)?|"
    r"(esta|esta)\s+foto|"
    r"mir(a|alo|ala)\s+(esto|esta)|"
    r"te\s+(la|lo)\s+(dejo|mando|env[ií]o)\s+(aqu[ií]|locked|bloquead)|"
    r"verme\s+as[ií]|en\s+cuatro|hilito|thong|tetas?|culo|pussy|"
    r"esta\s+foto\s+m[ií]a|foto\s+m[ií]a|m[aá]s\s+guarra|"
    r"solo\s+para\s+ti|just\s+for\s+you|only\s+for\s+you|"
    r"no\s+creas\s+que\s+me\s+regalo|not\s+giv(ing|e)\s+myself\s+away"
    r")\b|"
    r"(?:\$|€)\s*\d{1,4}|"
    r"\d{1,4}\s*(?:\$|€|eur|euros?|d[oó]lares?|dollars?|bucks?)"
    r")"
)


# Fan pretends he saw / liked / opened a lock he never paid for
_FAN_CLAIMS_SAW_PPV = re.compile(
    r"(?i)\b("
    r"ya\s+la\s+(vi|abr[ií]|desbloque\w*|compr[eé]|pagu[eé])|"
    r"la\s+(vi|abr[ií]|desbloque[eé]|compr[eé])|"
    # "ahora si que la veo" / "ya la veo" (common bluff after lock appears)
    r"(ahora\s+)?(s[ií]\s+)?que\s+la\s+veo|"
    r"ya\s+la\s+veo|ahora\s+la\s+veo|"
    r"se\s+te\s+ve|"
    r"te\s+veo\s+(muy\s+)?(buena|buenorra|rica|guarra|hot)|"
    r"buenorra|buenísima|buenisima|"
    r"(i\s+)?(already\s+)?(opened|unlocked|bought|paid\s+for)\s+(it|the\s+photo)|"
    r"(i\s+)?(saw|seen)\s+(it|the\s+photo|that\s+photo)|"
    r"i\s+can\s+see\s+(it|you|her)|"
    r"qu[eé]\s+rica\s+(la|esa|esta)\s+foto|"
    r"(la|esa|esta)\s+(última|ultima)?\s*foto\s+"
    r"(está|esta|estaba|era|fue)\s+(muy\s+)?"
    r"(buena|guarra|rica|hot)"
    r")\b"
)

# "me ha gustado mucho la ultima foto" / "liked the last photo"
_FAN_LIKED_LAST_PHOTO = re.compile(
    r"(?i)\b("
    r"(me\s+ha\s+gustado|me\s+gust[oó]|me\s+encant[oó]|liked|loved).{0,40}"
    r"(última|ultima|last|esa|esta|la)\s+(foto|photo|pic|imagen)|"
    r"(última|ultima|last)\s+(foto|photo|pic).{0,20}"
    r"(gust|like|encant|buena|guarra|hot|rica)|"
    # Body-part praise as if viewing the unpaid lock
    r"(me\s+)?(gustan|encantan)\s+(tus\s+)?(tetas|culo|piernas|pechos)|"
    r"qu[eé]\s+ricas?\s+(tetas|piernas|culo|pechos)|"
    r"^las\s+tetas\b|^el\s+culo\b|^tus\s+tetas\b"
    r")\b"
)

# Emma validates that he saw / liked content he never unlocked
# (no trailing \b — accents like gustó break word-boundary ends)
_VALIDATES_UNSEEN_PPV = re.compile(
    r"(?i)("
    r"\bme\s+alegro\s+que\s+te\s+gust|"
    r"\bqu[eé]\s+bien\s+que\s+te\s+gust|"
    r"\bglad\s+you\s+(liked|enjoyed)|"
    r"\bhappy\s+you\s+(liked|enjoyed)|"
    r"\bsince\s+you\s+(liked|enjoyed)|"
    r"\bya\s+que\s+te\s+gust|"
    r"\besa\s+era\s+solo|"
    r"\besa\s+era\s+un\s+poquit|"
    r"\bthat\s+was\s+just\s+a\s+(little|taste|tease)|"
    r"\bthat\s+was\s+only\s+a\s+(little|taste|tease)|"
    r"\bqu[eé]\s+te\s+pareci[oó]|"
    r"\bhow\s+did\s+you\s+like|"
    r"\bya\s+la\s+viste|"
    r"\byou\s+(already\s+)?(saw|opened|unlocked)\s+it|"
    r"\bsab[ií]a\s+que\s+te\s+(iba\s+a\s+)?gust|"
    r"\bval[ií]a\s+la\s+pena|"
    r"\bworth\s+it\b|"
    r"\bqu[eé]\s+parte.{0,40}gust|"
    r"\bwhat\s+part.{0,40}(like|love)|"
    r"\bte\s+fijes\s+en\s+mis|"
    r"\bme\s+encanta\s+que\s+te\s+fij|"
    r"\bves\??\s*te\s+dije|"
    r"\bte\s+dije\s+que\s+val[ií]a"
    r")"
)

# Emma actually calling the bluff (required when fan_saw_bluff)
_CALLS_OUT_BLUFF = re.compile(
    r"(?i)("
    r"\bmentiros|"
    r"\bfarol\b|"
    r"\bliar\b|"
    r"\bnunca\s+(la\s+|lo\s+)?(abr|desbloque|viste)|"
    r"\bno\s+(la\s+|lo\s+)?abriste|"
    r"\bno\s+has\s+(abierto|desbloqueado|pagado)|"
    r"\bsin\s+que\s+la\s+abrier|"
    r"\bcan'?t\s+(have\s+)?(seen|know)|"
    r"\bnever\s+(opened|unlocked|paid)|"
    r"\bstill\s+locked\b|"
    r"\bsigue\s+(cerrad|bloquead|sin\s+abrir)|"
    r"\bno\s+puedes\s+saber"
    r")"
)

_PURCHASE_CLEAR_REASONS = frozenset(
    {"purchased", "purchased_or_forbidden", "bought"}
)


def fan_claims_saw_ppv(fan_message: str) -> bool:
    """True if fan implies he saw/liked/opened a photo lock."""
    text = (fan_message or "").strip()
    if not text:
        return False
    return bool(
        _FAN_CLAIMS_SAW_PPV.search(text) or _FAN_LIKED_LAST_PHOTO.search(text)
    )


def validates_unseen_ppv(reply: str) -> bool:
    """True if Emma treats unpaid/expired lock as already seen and liked."""
    text = (reply or "").strip()
    if not text:
        return False
    return bool(_VALIDATES_UNSEEN_PPV.search(text))


def calls_out_purchase_bluff(reply: str) -> bool:
    """True if Emma playfully calls the unpaid-open bluff."""
    text = (reply or "").strip()
    if not text:
        return False
    return bool(_CALLS_OUT_BLUFF.search(text))


def last_ppv_never_bought(
    mem: Optional[dict],
    ppv_status: Optional[dict] = None,
    *,
    within_hours: float = 3.0,
) -> bool:
    """
    True when the latest timed PPV was never purchased — still unpaid,
    or recently expired/unsent without payment.
    """
    if ppv_status and ppv_status.get("purchased"):
        return False
    if ppv_status and ppv_status.get("active"):
        return True

    mem = mem or {}
    reason = str(mem.get("last_ppv_expire_reason") or "").strip().lower()
    if reason in _PURCHASE_CLEAR_REASONS:
        return False

    from datetime import datetime, timedelta, timezone

    def _within(raw: Any) -> bool:
        if not raw:
            return False
        try:
            ts = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            return datetime.now(timezone.utc) - ts <= timedelta(hours=within_hours)
        except (TypeError, ValueError):
            return False

    # Recently expired/unsent without purchase
    if _within(mem.get("last_ppv_expired_at")):
        return True

    # Recent paid offer, zero spender, never cleared as purchased
    purchases = int(mem.get("purchases") or 0)
    spent = float(mem.get("total_spent") or 0)
    if (
        purchases <= 0
        and spent <= 0
        and _within(mem.get("last_ppv_at"))
        and (mem.get("last_ppv_media_uuid") or mem.get("last_ppv_label"))
    ):
        return True
    return False


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
    claimed_vals = [
        int(x) for x in re.findall(r"(?i)(\d{1,3})\s*minut", text)
    ]
    # "6 minutos, 27…" — she keeps citing the fake number next to a real one
    claimed_vals += [
        int(x)
        for x in re.findall(r"(?i)minut\w*\s*[,.…]+\s*(\d{1,3})", text)
    ]
    claimed_vals += [
        int(x)
        for x in re.findall(r"(?i)(?:waiting|for)\s+(\d{1,3})\s*min\b", text)
    ]
    # Allow ±2 min slack; flag wild inventions (e.g. 27 vs 4)
    return any(c > minutes_ago + 2 for c in claimed_vals)


def paid_offer_reply_aligned(reply: str) -> bool:
    """
    True if the creative reply matches attaching Emma's paid lock this turn.

    False when DeepSeek went another direction (e.g. asked for HIS face) —
    text must be rewritten / forced; the attach itself is still committed.
    """
    text = (reply or "").strip()
    if not text:
        return False
    if _ASK_HIS_MEDIA.search(text):
        return False
    return bool(_SELLS_HER_LOCK.search(text))


def forced_paid_sell_line(
    *,
    price: float,
    want_spanish: bool,
    label: str = "",
) -> str:
    """
    Deterministic sell bubble when creative text won't line up with a committed attach.
    Code already chose the offer — never cancel the PPV over a soft phrase mismatch.
    """
    p = max(1, int(round(float(price or 0))))
    hint = (label or "").strip().lower()
    spicy = bool(
        re.search(
            r"(?i)\b(ass|culo|tits?|tetas?|pussy|thong|hilito|nude|desnud|four|cuatro)\b",
            hint,
        )
    )
    if want_spanish:
        if spicy:
            return (
                f"Solo para ti… esta foto mía, ${p} — "
                f"ábrela si de verdad quieres verme así"
            )
        return (
            f"Solo para ti, por ${p} — "
            f"esta foto queda bloqueada; no creas que me regalo a cualquiera"
        )
    if spicy:
        return (
            f"Just for you… this pic of me, ${p} — "
            f"unlock it if you really want to see me like this"
        )
    return (
        f"Just for you, ${p} — "
        f"this photo stays locked; I don't give myself away to just anyone"
    )


# Deterministic post-rewrite fallbacks. Must obey persona hard bans:
# no "Mmm…" / "Ay…" openers; no caro/papi/nena/nene.
_BANNED_FALLBACK_OPEN = re.compile(r"(?i)^(mmm|ay)[\s.…,]")


def fallback_purchase_bluff(*, want_spanish: bool, lock_still_active: bool) -> str:
    if want_spanish:
        if lock_still_active:
            return (
                "Mentiroso 😏 esa foto sigue cerrada — no la has abierto. "
                "No puedes saber lo guarra que es… todavía. Ábrela."
            )
        return (
            "Mentiroso 😏 esa foto se fue sin que la abrieras. "
            "No puedes saber lo guarra que era… todavía."
        )
    if lock_still_active:
        return (
            "Liar 😏 that photo is still locked — you haven't opened it. "
            "You can't know how filthy it is… yet. Unlock it."
        )
    return (
        "Liar 😏 that photo left without you unlocking it. "
        "You can't know how filthy it was… yet."
    )


def fallback_no_lock(*, want_spanish: bool) -> str:
    if want_spanish:
        return (
            "Ahora mismo no tengo un candado esperándote. "
            "Cuéntame qué te pasa, estoy aquí 🥺"
        )
    return (
        "I don't have a lock waiting for you right now. "
        "Tell me what's going on — I'm here 🥺"
    )


def fallback_photos_only(
    *, want_spanish: bool, real_price: Optional[float] = None
) -> str:
    if real_price is not None:
        rp = float(real_price)
        if want_spanish:
            return (
                f"De vídeo no… solo fotos 😏 Tienes UNA candada esperando — "
                f"${rp:.0f} y la abres, bebé."
            )
        return (
            f"No video… photos only 😏 You have ONE lock waiting — "
            f"${rp:.0f} and unlock it, babe."
        )
    if want_spanish:
        return (
            "Vídeo no tengo 😏 Solo fotos en el vault — "
            "dime qué te pone y te cierro una de verdad."
        )
    return (
        "No video 😏 Photos only in the vault — "
        "tell me what you want and I'll lock a real one."
    )


def fallback_ghost_promise(*, want_spanish: bool) -> str:
    if want_spanish:
        return (
            "Ahora mismo no te puedo soltar esa foto así, pillín 🔥 "
            "Pero dime qué te vuelve loco de mis tetas… ¿así te caliento más?"
        )
    return (
        "I can't drop that photo like that right now, baby 🔥 "
        "Tell me what drives you crazy about my tits… want me hotter?"
    )


def fallback_blame_own_it(*, want_spanish: bool) -> str:
    if want_spanish:
        return (
            "Perdona, bebé… se me trabó yo, no tú. "
            "Quédate conmigo un ratito y te lo dejo bien 🥺"
        )
    return (
        "Sorry baby… that was on me, not you. "
        "Stay with me a minute and I'll drop it properly 🥺"
    )


def fallback_obeys_style_bans(text: str) -> bool:
    """True if deterministic fallback text respects opener / hard pet bans."""
    t = (text or "").strip()
    if not t:
        return False
    if _BANNED_FALLBACK_OPEN.search(t):
        return False
    if re.search(r"(?i)\b(caro|papi|nena|nene)\b", t):
        return False
    return True


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


_QUESTION_CHUNK = re.compile(r"[^?\n]+[?¿]")


def _norm_q(text: str) -> str:
    t = (text or "").lower()
    t = re.sub(r"[^\w\sÁÉÍÓÚÜÑáéíóúüñ]", " ", t, flags=re.UNICODE)
    return re.sub(r"\s+", " ", t).strip()


def recent_emma_questions(
    history_turns: Optional[List[Dict[str, Any]]], *, n_turns: int = 3
) -> List[str]:
    """Questions Emma already asked in her last few turns."""
    if not history_turns:
        return []
    out: List[str] = []
    seen = 0
    for turn in reversed(history_turns):
        if (turn.get("role") or "") != "assistant":
            continue
        seen += 1
        body = str(turn.get("content") or "")
        for m in _QUESTION_CHUNK.findall(body):
            q = _norm_q(m)
            if len(q) >= 12:
                out.append(q)
        if seen >= n_turns:
            break
    return out


def repeats_recent_question(
    reply: str, history_turns: Optional[List[Dict[str, Any]]], *, n_turns: int = 3
) -> bool:
    """True if this reply re-asks a question Emma already asked recently."""
    qs = recent_emma_questions(history_turns, n_turns=n_turns)
    if not qs:
        return False
    for m in _QUESTION_CHUNK.findall(reply or ""):
        q = _norm_q(m)
        if len(q) < 12:
            continue
        q_toks = set(q.split())
        for prev in qs:
            p_toks = set(prev.split())
            if not q_toks or not p_toks:
                continue
            overlap = len(q_toks & p_toks) / max(1, min(len(q_toks), len(p_toks)))
            # 0.6 catches paraphrases ("sin palabras… qué me harías" loops)
            if overlap >= 0.6 or q in prev or prev in q:
                return True
    return False


def too_similar_to_last_assistant(
    reply: str, history_turns: Optional[List[Dict[str, Any]]]
) -> bool:
    """True if reply is nearly the same beat as Emma's previous message."""
    if not history_turns:
        return False
    last = ""
    for turn in reversed(history_turns):
        if (turn.get("role") or "") == "assistant":
            last = str(turn.get("content") or "")
            break
    if not last.strip() or not (reply or "").strip():
        return False
    a = set(_norm_q(reply).split())
    b = set(_norm_q(last).split())
    if len(a) < 4 or len(b) < 4:
        return False
    return len(a & b) / max(len(a), len(b)) >= 0.65


def continuity_loop(reply: str, history_turns: Optional[List[Dict[str, Any]]]) -> bool:
    """Any hard continuity failure worth a rewrite."""
    return (
        opening_repeats_recent(reply, history_turns, n=4)
        or repeats_recent_question(reply, history_turns, n_turns=3)
        or too_similar_to_last_assistant(reply, history_turns)
    )


def thread_beat_block(
    history_turns: Optional[List[Dict[str, Any]]],
    mem: Optional[dict] = None,
) -> str:
    """
    Compact continuity cue (not a second persona wall).

    Prefer the last few REAL turns over a stale card summary — same-day
    "forgot what he said 3 minutes ago" was often summary fighting the chat.
    """
    mem = mem or {}
    lines = [
        "THREAD BEAT — continue THIS chat (do not restart / do not invent):",
    ]

    # Last 4 turns of real chat (ground truth for the last few minutes)
    recent = []
    for turn in (history_turns or [])[-4:]:
        role = (turn.get("role") or "").strip()
        body = str(turn.get("content") or "").strip().replace("\n", " / ")
        if not body:
            continue
        who = "HIM" if role == "user" else "YOU"
        recent.append(f"{who}: {body[:160]}")
    if recent:
        lines.append("- Recent thread:")
        lines.extend(f"  · {r}" for r in recent)

    facts = [str(f).strip() for f in (mem.get("facts") or []) if str(f).strip()]
    if facts:
        lines.append("- Card facts (only if still true): " + "; ".join(facts[-3:])[:180])

    asked = recent_emma_questions(history_turns, n_turns=3)[:3]
    if asked:
        lines.append(
            "- You ALREADY asked (banned to repeat): "
            + " | ".join(f'"{q[:70]}"' for q in asked)
        )

    # Detect pídemelo / voice-stall loop across a wider window (20-msg beg loops)
    you_blob = " ".join(
        str(t.get("content") or "")
        for t in (history_turns or [])[-12:]
        if (t.get("role") or "") == "assistant"
    )
    him_blob = " ".join(
        str(t.get("content") or "")
        for t in (history_turns or [])[-12:]
        if (t.get("role") or "") == "user"
    )
    if re.search(
        r"(?i)\b(p[ií]demel[oa]|ask\s+me\s+nicely|grab(o|arte)|voice\s+note|audio|voz)\b",
        you_blob + " " + him_blob,
    ):
        lines.append(
            "- VOICE DEBT OPEN: this thread already covered audio / pídemelo. "
            "HARD BAN: ask him to beg again, 'pídemelo', 'quieres un audio?'. "
            "If audio attaches this turn, just talk normally. If not, flirt without "
            "promising or re-asking — never restart the audio beg loop."
        )

    lines.append(
        "- Answer what he just said using the recent thread above. "
        "One new beat — never the same question again. Never contradict the thread."
    )
    return "\n".join(lines)


def summarize(errors: List[Dict[str, Any]]) -> str:
    if not errors:
        return "scheme_ok"
    bits = [f"{e.get('rule')}:{e.get('what', '')[:40]}" for e in errors[:3]]
    return "scheme_fail " + " | ".join(bits)
