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
_BUYING = (
    r"\b(unlock|buy|pay|price|how much|cu[aá]nto|precio|quiero ver|"
    r"show me|vid|video|content|custom|locked|ppv|"
    r"env[ií]a(me|la|lo)?|m[aá]nda(me|la|mela)?|"
    r"(p[aá]sa(me|la|mela)?|quiero|m[aá]ndame).{0,12}(foto|pic|pics|photo)|"
    r"(foto|pic|pics|photo).{0,12}(por ?favor|ya|ahora))\b|"
    r"s[ií]+\s*quiero|lo quiero|dale\b"
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
    r"duro|caliente|mojada|polla|follar|correr)\b"
)
_REJECT = (
    r"\b(too expensive|caro|expensive|can'?t|no money|later|maybe later|"
    r"not now|nah|pass|otro d[ií]a|despu[eé]s)\b"
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
    r"lo quiero|vale|dale|te (pago|compro)|deal)\b|"
    r"s[ií]+\s*(quiero|dale|p[aá]galo)"
)
# Fan says the promised photo never arrived — must actually send, not invent glitches
_MISSING_DELIVERY = (
    r"(no me (ha |hayan )?llegado|no (me )?lleg[oó]|no (me )?aparece|"
    r"no (hay|tengo) nada|nothing (arrived|came|showed)|didn'?t (get|receive|see)|"
    r"where(?:'?s| is) (it|the|my)|d[oó]nde (est[aá]|qued[oó]|la)|"
    r"la misma de antes|no (me )?ha llegado|"
    r"no me has (mandado|enviado|pasado)|no me (mandaste|enviaste|pasaste)|"
    r"no (me )?has (mandado|enviado)|ninguna foto|no (me )?mandaste|"
    r"you (didn'?t|never) send|haven'?t (sent|gotten)|no photo)"
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
    Occasional L0 free hook while warming — NEVER spam on every 'gratis' ask.
    Soft lingerie for heat; paid L1+ after. Max 2 L0/fan, spaced out.
    """
    from core import vault_catalog

    if vault_catalog.l0_remaining(mem) <= 0:
        return False
    frees = int(mem.get("free_teases_sent") or 0)
    if frees >= 2:
        return False

    last_free = _parse_iso(mem.get("last_free_at"))

    # He says free never arrived AND Fanvue history does NOT show it → one recovery
    if missing_unverified:
        return msgs >= 2

    # Explicit "foto gratis" is NOT automatic — only the FIRST unused L0 once,
    # after some rapport, and not right after the last free.
    if force_ask:
        if frees >= 1:
            return False
        if last_free and now - last_free < timedelta(hours=2):
            return False
        return msgs >= 5

    if last_free and now - last_free < timedelta(minutes=45):
        return False
    if msgs < 6:
        return False
    last_ppv = _parse_iso(mem.get("last_ppv_at"))
    if last_ppv and now - last_ppv < timedelta(minutes=12):
        return False
    # First free after rapport; second only later when heat is high
    if frees <= 0:
        return msgs >= 6 and (status_warm(mem) or msgs >= 8)
    if frees == 1:
        return msgs >= 14
    return False


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

    chill_until = _parse_iso(mem.get("chill_until"))
    if chill_until and chill_until > now:
        return TurnDecision(
            mode=MODE_CHILL,
            reason="inside chill window",
            max_bubbles=3,
            allow_ppv_talk=False,
            allow_price=False,
        )

    last_purchase = _parse_iso(mem.get("last_purchase_at"))
    if last_purchase and now - last_purchase < timedelta(minutes=45):
        return TurnDecision(
            mode=MODE_CHILL,
            reason="recent purchase — reward, don't upsell yet",
            max_bubbles=2,
            allow_ppv_talk=False,
            allow_price=False,
        )

    last_reject = _parse_iso(mem.get("last_reject_at"))
    if last_reject and now - last_reject < timedelta(hours=2):
        return TurnDecision(
            mode=MODE_CHILL,
            reason="recent price reject — cool off",
            max_bubbles=2,
            allow_ppv_talk=False,
            allow_price=False,
        )

    offers_today = int(mem.get("offers_today") or 0)
    offers_day = mem.get("offers_day")  # YYYY-MM-DD UTC
    today = now.strftime("%Y-%m-%d")
    if offers_day != today:
        offers_today = 0

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

    # One unpaid lock at a time (early gate — before free-escalation soft sells)
    if pending_unpaid and not want_another and not buying:
        return TurnDecision(
            mode=MODE_TEASE,
            reason="unpaid PPV still open — push unlock, don't stack another",
            max_bubbles=2,
            allow_ppv_talk=True,
            allow_price=False,
            allow_free_tease=False,
        )

    # API says free photo IS already in this chat — guide him, don't re-gift
    if (missing_free or ask_free) and free_in_chat is True:
        return TurnDecision(
            mode=MODE_TEASE,
            reason="API: free already in chat — tell him to scroll up",
            max_bubbles=2,
            allow_ppv_talk=True,
            allow_price=False,
            allow_free_tease=False,
        )

    # Missing free + API says NOT in chat → recovery gift (unused L0 only)
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

    # Asks for free again after already gifted → warm tease + soft paid ladder
    if ask_free and frees_done >= 1:
        return TurnDecision(
            mode=MODE_SOFT_SELL,
            reason="already gifted free — escalate to paid, don't spam L0",
            max_bubbles=2,
            allow_ppv_talk=True,
            allow_price=True,
            allow_free_tease=False,
        )

    # First free ask only — smart warm gift, not on demand forever
    if ask_free and _free_tease_ok(mem, msgs=msgs, now=now, force_ask=True):
        return TurnDecision(
            mode=MODE_TEASE,
            reason="first free ask — one L0 warm gift",
            max_bubbles=2,
            allow_ppv_talk=False,
            allow_price=False,
            allow_free_tease=True,
        )

    # Ask free but not eligible (too soon / no rapport) — flirt, don't gift
    if ask_free:
        return TurnDecision(
            mode=MODE_TEASE,
            reason="free ask but not eligible yet — tease, don't spam gift",
            max_bubbles=2,
            allow_ppv_talk=True,
            allow_price=False,
            allow_free_tease=False,
        )

    # Cooling / confusion — answer plainly before delivery or buy paths mis-fire
    if re.search(_FAN_PUSHBACK, low) or (
        re.search(_PRICE_ISSUE, low) and not re.search(_ACCEPT, low)
    ):
        return TurnDecision(
            mode=MODE_CHILL,
            reason="fan pushback or billing confusion — clarify, don't sell",
            max_bubbles=2,
            allow_ppv_talk=False,
            allow_price=False,
        )

    # He sent US a photo — react like a person, never auto-pitch PPV
    if fan_sent_media and not want_another:
        return TurnDecision(
            mode=MODE_TEASE,
            reason="fan sent media — react to HIS photo, don't pitch",
            max_bubbles=2,
            allow_ppv_talk=False,
            allow_price=False,
            allow_free_tease=False,
        )

    # Hard stop: never stack two locked PPVs within 12 min unless he asks for another
    last_ppv_at = _parse_iso(mem.get("last_ppv_at")) or _parse_iso(mem.get("last_offer_at"))
    if last_ppv_at and now - last_ppv_at < timedelta(minutes=12) and not want_another:
        free_ok = _free_tease_ok(mem, msgs=msgs, now=now)
        return TurnDecision(
            mode=MODE_TEASE,
            reason="PPV cooloff — no second lock yet",
            max_bubbles=2,
            allow_ppv_talk=True,
            allow_price=False,
            allow_free_tease=free_ok,
        )

    # He says nothing arrived / asks where content is → send a REAL locked photo now
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

    last_offer_at = _parse_iso(mem.get("last_offer_at"))
    if last_offer_at and now - last_offer_at < timedelta(minutes=25):
        # Only a clear "another / sí quiero" during cooloff re-opens sell
        clear_ask = want_another or bool(
            re.search(r"s[ií]+\s*(quiero|dale|p[aá]galo)|lo quiero|te (pago|compro)", low)
        )
        if clear_ask:
            return TurnDecision(
                mode=MODE_SOFT_SELL,
                reason="accepted during cooloff — send real PPV",
                max_bubbles=2,
                allow_ppv_talk=True,
                allow_price=True,
            )
        # Flirt only — but FREE L0 can still land (not a paid re-pitch)
        free_ok = _free_tease_ok(mem, msgs=msgs, now=now)
        return TurnDecision(
            mode=MODE_TEASE,
            reason="offered recently — flirt, don't re-pitch yet",
            max_bubbles=2,
            allow_ppv_talk=True,
            allow_price=False,
            allow_free_tease=free_ok,
        )

    if re.search(_REJECT, low):
        return TurnDecision(
            mode=MODE_CHILL,
            reason="price/delay objection in this message",
            max_bubbles=2,
            allow_ppv_talk=False,
            allow_price=False,
        )

    # Brand-new fans: bond first
    if status == "new" or msgs < 4:
        if re.search(_BUYING, low) or re.search(_HORNY, low):
            return TurnDecision(
                mode=MODE_TEASE,
                reason="new fan but already horny/asking — tease only",
                max_bubbles=2,
                allow_ppv_talk=True,
                allow_price=False,
                allow_free_tease=False,
            )
        return TurnDecision(
            mode=MODE_RAPPORT,
            reason="new/early conversation — be a person first",
            max_bubbles=2,
            allow_ppv_talk=False,
            allow_price=False,
        )

    if re.search(_CHILL_ASK, low) and not re.search(_BUYING, low):
        return TurnDecision(
            mode=MODE_RAPPORT,
            reason="small-talk message — match his energy",
            max_bubbles=2,
            allow_ppv_talk=False,
            allow_price=False,
        )

    horny = bool(re.search(_HORNY, low))
    heated = status in ("warm", "spender", "whale") or msgs >= 6

    # Cap soft pitches per day — but after a free gift / heat, keep locking PPV
    if offers_today >= 5 and not buying and not (frees_done >= 1 and heated):
        return TurnDecision(
            mode=MODE_TEASE,
            reason="daily offer cap — keep heat without pitching",
            max_bubbles=2,
            allow_ppv_talk=True,
            allow_price=False,
            allow_free_tease=_free_tease_ok(mem, msgs=msgs, now=now),
        )

    # After free warm-up: escalate to paid lock without waiting for him to beg
    if frees_done >= 1 and heated and msgs >= 6:
        last_ppv = _parse_iso(mem.get("last_ppv_at")) or _parse_iso(mem.get("last_offer_at"))
        if not (last_ppv and now - last_ppv < timedelta(minutes=12)):
            return TurnDecision(
                mode=MODE_SOFT_SELL,
                reason="post-free heat — lock PPV without asking",
                max_bubbles=2,
                allow_ppv_talk=True,
                allow_price=True,
                allow_free_tease=False,
            )

    if buying and (status in ("spender", "whale") or spent > 0):
        return TurnDecision(
            mode=MODE_HARD_SELL,
            reason="buyer + clear ask",
            max_bubbles=2,
            allow_ppv_talk=True,
            allow_price=True,
        )

    if buying:
        return TurnDecision(
            mode=MODE_SOFT_SELL,
            reason="clear content/price ask",
            max_bubbles=2,
            allow_ppv_talk=True,
            allow_price=True,
        )

    # Free L0 hooks BEFORE soft-close — warm with lingerie 1→2, then sell L1+
    free_ok = _free_tease_ok(mem, msgs=msgs, now=now)
    if free_ok and (horny or heated or msgs >= 5):
        return TurnDecision(
            mode=MODE_TEASE,
            reason="warming — free L0 tease before paid ladder",
            max_bubbles=2,
            allow_ppv_talk=True,
            allow_price=False,
            allow_free_tease=True,
        )

    # Soft close after heat — don't stall in endless flirt
    # (cooloffs / reject windows / daily cap already handled above)
    if horny and msgs >= 4:
        return TurnDecision(
            mode=MODE_SOFT_SELL,
            reason="horny + enough rapport — soft close with one real lock",
            max_bubbles=2,
            allow_ppv_talk=True,
            allow_price=True,
        )

    if heated and msgs >= 7:
        return TurnDecision(
            mode=MODE_SOFT_SELL,
            reason="long warm chat — soft close so it doesn't stall forever",
            max_bubbles=2,
            allow_ppv_talk=True,
            allow_price=True,
        )

    if horny or msgs >= 5:
        return TurnDecision(
            mode=MODE_TEASE,
            reason="warming up — build heat before the close",
            max_bubbles=2,
            allow_ppv_talk=True,
            allow_price=False,
            allow_free_tease=False,
        )

    return TurnDecision(
        mode=MODE_RAPPORT,
        reason="default — connect first",
        max_bubbles=2,
        allow_ppv_talk=False,
        allow_price=False,
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
        lang = (
            "Full correct Spanish only."
            if want_spanish
            else "Full correct English only. Zero Spanish."
        )
        mode_hint = {
            MODE_CHILL: "Warm, human, no sell.",
            MODE_RAPPORT: "Light flirt, no PPV price.",
            MODE_TEASE: "Build heat. Only gift free if system attaches L0. Do not stamp his real name.",
            MODE_SOFT_SELL: (
                "LOCK one paid photo NOW — system attaches it after your text. "
                "Do NOT ask permission / 'quieres?' / offer gratis. Short tease then lock."
            ),
            MODE_HARD_SELL: (
                "LOCK one paid photo NOW with confidence. No asking. No free. One clear close."
            ),
        }.get(decision.mode, "Stay in character.")
        return (
            f"[Emma texting. {lang} Natural clear grammar — no word-salad. "
            f"1–3 short lines. Almost NEVER his real name (no 'Ay Ruben' stamp) — pet name or none. "
            f"{mode_hint}]"
        )

    if want_spanish:
        lang = (
            "LANGUAGE: He wrote in Spanish → reply in FULL correct Spanish this turn. "
            "Zero English. No Spanglish. Clean grammar in YOUR words only — never pedantically "
            "correct or re-spell HIS typos. Never 'caro/papi/nena' as nicknames."
        )
    else:
        lang = (
            "LANGUAGE: FULL correct English only this turn. Zero Spanish words. "
            "No Spanglish. No 'mira/bebé/ábrelo/caro/papi'. Native LA English, clean grammar "
            "in YOUR words only — never pedantically correct HIS typos."
        )
    base = (
        "[Stay in character as Emma. Reply like real texting — natural, not scripted. "
        "STRUCTURE: randomly prefer 1 line OR 2 lines OR (rarely) 3 — uneven lengths are good. "
        "Do NOT always send two similar-length lines. "
        "EMOJIS: natural middle — ~half of replies get 1 emoji, some get 0, rarely 2; "
        "never stamp 2–3 every line, but don't go bone-dry / zero forever. "
        "Warm short lines > cold clipped ones. "
        "Don't repeat your previous openings. React to what he MEANT in his LAST message — "
        "never quote him back with 'corrected' spelling or play grammar police. "
        "If you slip (wrong name, awkward phrase): blush and apologize simply in character — "
        "never blame the app, chat, translator, or glitches. "
        "Never promise vague bonus perks (extra attention, protection). "
        "Only gift a free photo when the system attaches a real L0 tease this turn. "
        f"{lang} "
        "ADDRESSING: usually a light pet name (babe/baby/handsome/trouble) or none. "
        "Almost NEVER his real name — never 'Ay Ruben' every bubble. "
        "Never invent a first name (no Jamie/Carlos/Alex/Simón). "
        "Spanish pet names only in full-Spanish replies.]"
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
