"""
Turn policy — decide WHETHER Emma should sell this turn.

Does not rewrite the persona. Only picks a mode so the reply engine
can soften/harden the author's note.

Balance: bond and heat first, then soft-close so chats don't stall forever.
Never spam locks — cooloffs and daily caps still win.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

# Modes (least → most sales pressure)
MODE_CHILL = "chill"
MODE_RAPPORT = "rapport"
MODE_TEASE = "tease"
MODE_SOFT_SELL = "soft_sell"
MODE_HARD_SELL = "hard_sell"

# Intent to BUY / receive Emma's content — not "I sent YOU a photo"
# Buy / receive content — vault is PHOTOS only. "video/custom" still counts as
# buying intent (he wants media) but creative must redirect to a PHOTO offer.
_BUYING = (
    r"\b(unlock|buy|pay|price|how much|cu[aá]nto|precio|quiero ver|"
    r"show me|let me see|locked|ppv|"
    # intent only → close a PHOTO, never promise film. No bare "content"
    # (was matching loose chat and forcing closes).
    r"v[ií]deo|video|clip|custom|"
    r"env[ií]a(me|la|lo|mela)?|m[aá]nda(me|la|mela)?|"
    r"ense[nñ]?[aá](me|mela|rmela)?|muestr[aá](me|mela)|"  # eseñame typo
    r"por\s*favor|please|no\s+me\s+dejes(\s+con)?|"
    r"(p[aá]sa(me|la|mela)?|quiero|m[aá]ndame|env[ií]ame).{0,20}"
    r"(foto|pic|pics|photo|teta|tetas|tetitas|culo|ass|boob|v[ií]deo|video|clip)|"
    r"(foto|pic|pics|photo).{0,12}(por ?favor|ya|ahora)|"
    r"tic\s*tac|ya\s*est[aá]|d[oó]nde\s+est[aá]\s+(la\s+)?foto)\b|"
    r"s[ií]+\s*quiero|lo quiero|dale\b|"
    r"venga\s*va|vamos\s*ya|te lo demuestro|hazlo|m[aá]ndala|env[ií]ala"
)
# Fan is talking about media HE sent (react, don't pitch)
_FAN_SENT_MEDIA = (
    r"(te (he )?pas(ado|é)|te (he )?enviado|te mand[eé]|te envi[eé]|"
    r"mira (esta|la) foto|te (he )?mandado|"
    r"pas(é|e) una foto|envi(é|e) una foto|"
    r"\[fan sent a (photo|image|video)\])"
)
# Explicit ask for a FREE photo (typos included) — bypass paid-offer cooloff
_ASK_FREE = (
    r"\b("
    r"gratis|grastis|gratiz|free\s*(?:photo|pic|pics|foto)?|"
    r"foto\s*(?:gratis|grastis|gratiz)|"
    r"(?:una\s+)?(?:foto|pic|photo)\s*(?:gratis|grastis|free)|"
    r"regalo|gift\s*(?:me|a)?\s*(?:photo|pic|foto)?"
    r")\b"
)
# Explicit ask for ANOTHER locked item (overrides PPV cooloff)
_WANT_ANOTHER = (
    r"\b(otra|another|one more|una m[aá]s|m[aá]s foto|siguiente|"
    r"otra foto|next one|m[aá]s cara|something else)\b"
)
_HORNY = (
    r"\b(hard|horny|wet|cock|dick|pussy|fuck|cum|stroke|jerk|"
    r"duro|caliente|mojada|polla|follar|correr|"
    r"tetitas?|tetas?|tetasa|boobs?|culo|ass|senos?|pechos?|lamerlas)\b"
)
_REJECT = (
    r"\b(too expensive|caro|expensive|can'?t|no money|later|maybe later|"
    r"not now|nah|pass|otro d[ií]a|despu[eé]s|pelado|pelá|"
    r"sin (plata|dinero|pasta)|no tengo (plata|dinero|pasta))\b"
)
# Broke / heavy emotional vent — pause hard sell (not the guilt objection script)
_BROKE_SOFT = (
    r"\b(pelado|pelá|broke|can'?t afford|no money|"
    r"sin (plata|dinero|pasta|un duro)|"
    r"no tengo (plata|dinero|pasta|nada)|"
    r"estoy (sin plata|pelado|pelao))\b"
)
_HEAVY_VENT = (
    r"\b(me quit[oó] todo|me dej[oó]|"
    r"quiero morir|suicid|deprimid|ansiedad|"
    r"ataque de p[aá]nico|estoy (muy )?mal|"
    r"quiero llorar|me duele (mucho )?el coraz|"
    # Pet / grief — comfort first, no sell
    r"se me (ha |ha )?muerto|se me muri[oó]|ha muerto (mi |el )|"
    r"mi perro|mi gato|my dog|my cat|"
    r"necesito .{0,20}mimos|estoy de luto|grief|funeral"
    r")\b"
)
# Billing confusion / checkout friction — empathize, don't re-pitch
_PRICE_ISSUE = (
    r"\b(?:impuestos?|tax(?:es)?|iva|checkout|billing|cobr|factur|"
    r"tarjeta|card.*pay|pay.*card|"
    r"€\s*\d|\$\s*\d|"
    r"por qu[eé].*pag|why.*pay|why.*charge|"
    r"cu[aá]nto.*pag|how much.*pay|pag[aá]r)\b|"
    r"\d+[.,]\d{1,2}.{0,40}(?:dijiste|said|vs|versus|pero tu|but you)|"
    r"(?:dijiste|you said|tu dijiste).{0,25}\d+[.,]\d{1,2}|"
    r"(?:sale|cobr|charge).{0,30}\d+[.,]\d{1,2}"
)
# Fan cooling — calls out a mistake or asks a direct logistical question
_FAN_PUSHBACK = (
    r"\b(?:quien es|qui[eé]n es|who is|who'?s that|wrong name|"
    r"donde (?:has )?visto|where did you (?:see|get)|"
    r"no me llamo|that'?s not my name|"
    r"por qu[eé] (?:dices|dijiste|llamas|me llamas)|"
    r"why (?:did you|do you) (?:call|say))\b"
)
# ...but an ACCEPTANCE mentioning the price is a buy signal, not friction
_ACCEPT = (
    r"\b(i'?ll (pay|take|buy)|take it|unlock(ing)? it|"
    r"lo quiero|vale|dale|te (pago|compro)|deal|"
    r"venga\s*va|vamos\s*ya|te lo demuestro|hazlo)\b|"
    r"s[ií]+\s*(quiero|dale|p[aá]galo)"
)
# Fan says the promised photo never arrived — must actually send, not invent glitches
_MISSING_DELIVERY = (
    r"(no me (ha |hayan )?llegado|no (me )?lleg[oó]|no (me )?aparece|"
    r"no (hay|tengo) nada|nada de nada|no has puesto|"
    r"no (me )?has (puesto|mandado|enviado|pasado)|"
    r"nothing (arrived|came|showed)|didn'?t (get|receive|see)|"
    r"where(?:'?s| is) (it|the|my)|d[oó]nde (est[aá]|qued[oó]|la)|"
    r"la misma de antes|no (me )?ha llegado|"
    r"no me has (mandado|enviado|pasado)|no me (mandaste|enviaste|pasaste)|"
    r"ninguna foto|no (me )?mandaste|"
    r"you (didn'?t|never) send|haven'?t (sent|gotten)|no photo|"
    r"prueba de nuevo|try again|m[aá]ndalo otra|env[ií]alo otra)"
)
_CHILL_ASK = (
    r"\b(how (are|r) you|how'?s your day|what (are|r) you (up to|doing)|"
    r"good morning|good night|hola|qué tal|que tal|c[oó]mo est[aá]s)\b"
)


@dataclass
class TurnDecision:
    mode: str
    reason: str
    max_bubbles: int
    allow_ppv_talk: bool
    allow_price: bool
    allow_free_tease: bool = False
    # Scheme meta (filled by reply_engine for logs / critic / guard)
    pack_id: str = ""
    technique: str = ""
    phase: str = ""
    lock_active: Optional[bool] = None
    scheme_errors: List[Dict[str, Any]] = field(default_factory=list)


def _parse_iso(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _free_tease_ok(
    mem: dict,
    *,
    msgs: int,
    now: datetime,
    force_ask: bool = False,
    missing_unverified: bool = False,
) -> bool:
    """
    Rare L0 free hook while warming — NEVER spam.

    Max ONE free tease per fan, ever (then paid only). Same media UUID never
    repeats (vault_catalog / sent_media_uuids). Missing-delivery recovery is
    the only path that can re-attempt if Fanvue never showed the gift.
    """
    from core import vault_catalog

    if vault_catalog.l0_remaining(mem) <= 0:
        return False
    frees = int(mem.get("free_teases_sent") or 0)
    last_free = _parse_iso(mem.get("last_free_at"))

    # He says free never arrived AND Fanvue history does NOT show it → recovery
    # (ghost clear may already have dropped free_teases_sent; still allow one retry)
    if missing_unverified:
        return msgs >= 2

    # One verified free gift max — we don't hand out content liberally
    if frees >= 1:
        return False

    # Explicit "free photo" ask — only if he never got one, after some rapport
    if force_ask:
        if last_free and now - last_free < timedelta(hours=2):
            return False
        return msgs >= 5

    if last_free and now - last_free < timedelta(hours=6):
        return False
    if msgs < 8:
        return False
    # Single opportunistic free after real rapport — not early spam
    return status_warm(mem) or msgs >= 10


def status_warm(mem: dict) -> bool:
    return (mem.get("status") or "new") in ("warm", "spender", "whale")


def decide_turn(
    mem: dict,
    fan_message: str,
    *,
    delivery_truth: Optional[dict] = None,
) -> TurnDecision:
    """
    Pick mode from memory + current message.

    Conservative defaults so we don't scare cold/new fans.
    delivery_truth: optional API checks, e.g. {"free_in_chat": True/False/None}
    """
    text = (fan_message or "").strip()
    low = text.lower()
    msgs = int(mem.get("messages") or 0)
    status = mem.get("status") or "new"
    spent = float(mem.get("total_spent") or 0)
    now = _now()
    truth = delivery_truth or {}
    free_in_chat = truth.get("free_in_chat")  # True / False / None

    # Group A sell bans removed. Truth gates + creative sell default.

    fan_sent_media = bool(re.search(_FAN_SENT_MEDIA, low))
    ask_free = bool(re.search(_ASK_FREE, low)) and not fan_sent_media
    missing = bool(re.search(_MISSING_DELIVERY, low)) and not fan_sent_media
    missing_free = missing and bool(
        re.search(r"\b(gratis|grastis|gratiz|free)\b", low)
    )
    frees_done = int(mem.get("free_teases_sent") or 0)
    buying = (
        bool(re.search(_BUYING, low) or re.search(_ACCEPT, low))
        and not fan_sent_media
        and not ask_free
        and not missing_free
    )
    want_another = bool(re.search(_WANT_ANOTHER, low))
    pending_unpaid = bool(truth.get("ppv_unpaid"))
    heated = status in ("warm", "spender", "whale") or msgs >= 6
    free_ok = _free_tease_ok(mem, msgs=msgs, now=now)

    if pending_unpaid and not want_another and not buying:
        return TurnDecision(
            mode=MODE_TEASE,
            reason="unpaid PPV still open — push unlock, don't stack another",
            max_bubbles=2,
            allow_ppv_talk=True,
            allow_price=False,
            allow_free_tease=False,
        )

    if (missing_free or ask_free) and free_in_chat is True:
        return TurnDecision(
            mode=MODE_TEASE,
            reason="API: free already in chat — tell him to scroll up",
            max_bubbles=2,
            allow_ppv_talk=True,
            allow_price=False,
            allow_free_tease=False,
        )

    if missing_free and free_in_chat is False:
        if _free_tease_ok(mem, msgs=msgs, now=now, missing_unverified=True):
            return TurnDecision(
                mode=MODE_TEASE,
                reason="missing free + API not in chat — recover L0",
                max_bubbles=2,
                allow_ppv_talk=False,
                allow_price=False,
                allow_free_tease=True,
            )

    if ask_free and frees_done >= 1:
        return TurnDecision(
            mode=MODE_SOFT_SELL,
            reason="already gifted free — escalate to paid",
            max_bubbles=2,
            allow_ppv_talk=True,
            allow_price=True,
            allow_free_tease=False,
        )

    if ask_free and _free_tease_ok(mem, msgs=msgs, now=now, force_ask=True):
        return TurnDecision(
            mode=MODE_TEASE,
            reason="first free ask — one L0 warm gift",
            max_bubbles=2,
            allow_ppv_talk=False,
            allow_price=False,
            allow_free_tease=True,
        )

    if missing or re.search(
        r"\b(d[oó]nde|where).{0,30}\b(foto|photo|pic|inbox|bandeja|unlock|ppv|media|it)\b|"
        r"\b(bandeja|inbox)\b",
        low,
    ):
        return TurnDecision(
            mode=MODE_SOFT_SELL,
            reason="fan expects a delivery — attach real PPV",
            max_bubbles=2,
            allow_ppv_talk=True,
            allow_price=True,
        )

    if buying or want_another or re.search(_HORNY, low) or heated:
        mode = (
            MODE_HARD_SELL
            if buying and (status in ("spender", "whale") or spent > 0)
            else MODE_SOFT_SELL
        )
        return TurnDecision(
            mode=mode,
            reason="creative sell path (no Group-A bans)",
            max_bubbles=2,
            allow_ppv_talk=True,
            allow_price=True,
            allow_free_tease=free_ok and not buying and frees_done <= 0,
        )

    if msgs < 4:
        return TurnDecision(
            mode=MODE_TEASE,
            reason="early chat — heat / optional L0",
            max_bubbles=2,
            allow_ppv_talk=True,
            allow_price=False,
            allow_free_tease=free_ok,
        )

    return TurnDecision(
        mode=MODE_SOFT_SELL,
        reason="default sell-capable",
        max_bubbles=2,
        allow_ppv_talk=True,
        allow_price=True,
        allow_free_tease=free_ok,
    )



def author_note_for(
    decision: TurnDecision,
    *,
    want_spanish: bool = False,
    lean: bool = True,
) -> str:
    """
    Soft author's note. Lean mode keeps DeepSeek creative (short steer only).
    """
    if lean:
        lang = "ENGLISH ONLY. Zero Spanish — even if he writes Spanish."
        mode_hint = {
            MODE_CHILL: "Warm, human, no sell.",
            MODE_RAPPORT: "Light flirt, no PPV price.",
            MODE_TEASE: "Build heat. Only gift free if system attaches L0. Name/pets per ADDRESSING.",
            MODE_SOFT_SELL: (
                "LOCK one paid photo NOW — system attaches it after your text. "
                "Do NOT ask permission / 'want it?' / offer free. Short tease then lock."
            ),
            MODE_HARD_SELL: (
                "LOCK one paid photo NOW with confidence. No asking. No free. One clear close."
            ),
        }.get(decision.mode, "Stay in character.")
        return (
            f"[Emma WhatsApp texting. {lang} Informal chat voice — slang/abbreviations OK, "
            f"not essay grammar, no word-salad. "
            f"1–3 short lines. Pet names welcome; real name sometimes OK (see ADDRESSING) — "
            f"never 'Ay Name' every bubble. {mode_hint}]"
        )

    lang = (
        "LANGUAGE: FULL correct English only this turn. Zero Spanish words. "
        "No Spanglish. No 'mira/bebé/ábrelo/caro/papi'. Native LA English, clean grammar "
        "in YOUR words only — never pedantically correct HIS typos. "
        "Even if he writes Spanish — reply in English."
    )
    base = (
        "[Stay in character as Emma. Reply like real texting — natural, not scripted. "
        "STRUCTURE: randomly prefer 1 line OR 2 lines OR (rarely) 3 — uneven lengths are good. "
        "Do NOT always send two similar-length lines. "
        "EMOJIS: warm & expressive — usually 2–4 in the whole reply; most lines can have one. "
        "Rotate 😏🥵💕😈🔥🥺👀💋 — not the same stamp every bubble, never bone-dry. "
        "Warm short lines > cold clipped ones. "
        "Don't repeat your previous openings. React to what he MEANT in his LAST message — "
        "never quote him back with 'corrected' spelling or play grammar police. "
        "If you slip (wrong name, awkward phrase): blush and apologize simply in character — "
        "never blame the app, chat, translator, or glitches. "
        "Never promise vague bonus perks (extra attention, protection). "
        "Only gift a free photo when the system attaches a real L0 tease this turn. "
        f"{lang} "
        "ADDRESSING: light pet names (babe/baby/handsome/trouble/honey/gorgeous) often OK — vary them. "
        "His confirmed real name: sometimes for intimacy, not every bubble — never 'Ay Name' spam. "
        "Never invent a first name (no Jamie/Carlos/Alex/Simon). "
        "Never Spanish pet names (bebé/cielo/guapo).]"
    )

    mode_lines = {
        MODE_CHILL: (
            "MODE=chill: Be warm and human. NO locked content, NO prices, NO 'unlock' talk. "
            "Answer his direct question FIRST — billing/taxes, price mismatch, or a slip like "
            "a wrong name. Empathize, then ONE plain sentence (Fanvue adds tax/VAT at checkout; "
            "you don't control fees). Skip jokes, guilt/FOMO, and price-objection scripts — "
            "clarity beats selling. Then gently reconnect."
        ),
        MODE_RAPPORT: (
            "MODE=rapport: Flirt lightly if it fits, but do NOT pitch PPV or prices this turn. "
            "Be a person he enjoys chatting with."
        ),
        MODE_TEASE: (
            "MODE=tease: Build heat and curiosity. Stay in his fantasy. "
            "If a FREE L0 tease is attached this turn, gift that soft lingerie taste — "
            "do NOT say it is locked or ask him to unlock. "
            "If NO media is attached: hint you have something naughty, but do NOT drop a price "
            "or claim you already sent / left anything in his inbox."
        ),
        MODE_SOFT_SELL: (
            "MODE=soft_sell: LOCK one paid photo NOW — system attaches after your text. "
            "Do NOT ask 'quieres?' / permission. Do NOT offer gratis/free. "
            "Short tease, then lock with confidence. Never stack two locks."
        ),
        MODE_HARD_SELL: (
            "MODE=hard_sell: LOCK one paid photo NOW with confidence. No asking. No free. "
            "Still sound like Emma. One clear close, not a lecture."
        ),
    }
    return f"{base} {mode_lines.get(decision.mode, mode_lines[MODE_RAPPORT])}"
