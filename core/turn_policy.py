"""
Turn policy — decide WHETHER Emma should sell this turn.

Does not rewrite the persona. Only picks a mode so the reply engine
can soften/harden the author's note.

Balance: bond and heat first, then soft-close so chats don't stall forever.
Never spam locks — cooloffs and daily caps still win.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

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
    r"(foto|pic|pics|photo).{0,12}(por ?favor|ya|ahora)|"
    r"d[oó]nde|where(?:'?s| is)|bandeja)\b|"
    r"s[ií]+\s*quiero|lo quiero|dale\b"
)
# Fan is talking about media HE sent (react, don't pitch)
_FAN_SENT_MEDIA = (
    r"(te (he )?pas(ado|é)|te (he )?enviado|te mand[eé]|te envi[eé]|"
    r"mira (esta|la) foto|te (he )?mandado|"
    r"pas(é|e) una foto|envi(é|e) una foto|"
    r"\[fan sent a (photo|image|video)\])"
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
    r"\b(impuesto|tax|iva|checkout|billing|cobr|factur|"
    r"tarjeta|card.*pay|pay.*card|"
    r"€\s*\d|\$\s*\d|"
    r"por qu[eé].*pag|why.*pay|why.*charge|"
    r"cu[aá]nto.*pag|how much.*pay)\b|pag[aá]r"
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
    r"la misma de antes|no (me )?ha llegado)"
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


def _parse_iso(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _free_tease_ok(mem: dict, *, msgs: int, now: datetime) -> bool:
    """
    Occasional L0 free hook while warming — never spam, never repeat.
    Soft lingerie 1→2; paid L1+ comes later via soft_sell.
    """
    from core import vault_catalog

    if msgs < 5:
        return False
    if vault_catalog.l0_remaining(mem) <= 0:
        return False
    last_free = _parse_iso(mem.get("last_free_at"))
    if last_free and now - last_free < timedelta(minutes=25):
        return False
    last_ppv = _parse_iso(mem.get("last_ppv_at")) or _parse_iso(mem.get("last_offer_at"))
    if last_ppv and now - last_ppv < timedelta(minutes=12):
        return False
    frees = int(mem.get("free_teases_sent") or 0)
    # First free after some rapport; second only after more heat
    if frees <= 0:
        return msgs >= 5
    if frees == 1:
        return msgs >= 9
    return False


def decide_turn(mem: dict, fan_message: str) -> TurnDecision:
    """
    Pick mode from memory + current message.

    Conservative defaults so we don't scare cold/new fans.
    """
    text = (fan_message or "").strip()
    low = text.lower()
    msgs = int(mem.get("messages") or 0)
    status = mem.get("status") or "new"
    spent = float(mem.get("total_spent") or 0)
    now = _now()

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
    buying = bool(re.search(_BUYING, low) or re.search(_ACCEPT, low)) and not fan_sent_media
    missing = bool(re.search(_MISSING_DELIVERY, low)) and not fan_sent_media
    want_another = bool(re.search(_WANT_ANOTHER, low))

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
        return TurnDecision(
            mode=MODE_TEASE,
            reason="PPV cooloff — no second lock yet",
            max_bubbles=2,
            allow_ppv_talk=True,
            allow_price=False,
            allow_free_tease=False,
        )

    # He says nothing arrived / asks where it is → send a REAL locked photo now
    if missing or (buying and re.search(r"\b(d[oó]nde|where|bandeja)\b", low)):
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
        return TurnDecision(
            mode=MODE_TEASE,
            reason="offered recently — flirt, don't re-pitch yet",
            max_bubbles=2,
            allow_ppv_talk=True,
            allow_price=False,
            allow_free_tease=False,
        )

    if re.search(_REJECT, low):
        return TurnDecision(
            mode=MODE_CHILL,
            reason="price/delay objection in this message",
            max_bubbles=2,
            allow_ppv_talk=False,
            allow_price=False,
        )

    if re.search(_PRICE_ISSUE, low) and not re.search(_ACCEPT, low):
        return TurnDecision(
            mode=MODE_CHILL,
            reason="billing/price confusion — explain, don't push unlock",
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

    # Cap soft pitches per day
    if offers_today >= 3 and not buying:
        return TurnDecision(
            mode=MODE_TEASE,
            reason="daily offer cap — keep heat without pitching",
            max_bubbles=2,
            allow_ppv_talk=True,
            allow_price=False,
            allow_free_tease=_free_tease_ok(mem, msgs=msgs, now=now),
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


def author_note_for(decision: TurnDecision, *, want_spanish: bool = False) -> str:
    """
    Soft author's note. Keeps the good base; only changes sell pressure.
    """
    if want_spanish:
        lang = (
            "LANGUAGE: He wrote in Spanish → reply in FULL correct Spanish this turn. "
            "Zero English. No Spanglish. No typos. Never 'caro/papi/nena' as nicknames."
        )
    else:
        lang = (
            "LANGUAGE: FULL correct English only this turn. Zero Spanish words. "
            "No Spanglish. No 'mira/bebé/ábrelo/caro/papi'. Native LA English, clean grammar."
        )
    base = (
        "[Stay in character as Emma. Reply like real texting — natural, not scripted. "
        "STRUCTURE: randomly prefer 1 line OR 2 lines OR (rarely) 3 — uneven lengths are good. "
        "Do NOT always send two similar-length lines. "
        "EMOJIS: natural middle — ~half of replies get 1 emoji, some get 0, rarely 2; "
        "never stamp 2–3 every line, but don't go bone-dry / zero forever. "
        "Warm short lines > cold clipped ones. "
        "Don't repeat your previous openings. React to his LAST message. "
        "Never promise vague bonus perks (extra attention, protection). "
        "Only gift a free photo when the system attaches a real L0 tease this turn. "
        f"{lang} "
        "ADDRESSING: usually a light pet name (babe/baby/handsome/trouble) or none. "
        "His real name at most once every few turns — never every message. "
        "Spanish pet names only in full-Spanish replies.]"
    )

    mode_lines = {
        MODE_CHILL: (
            "MODE=chill: Be warm and human. NO locked content, NO prices, NO 'unlock' talk. "
            "If he's confused about billing/taxes/fees, explain simply in character — "
            "do NOT push him to buy or unlock. Just connect."
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
            "MODE=soft_sell: Keep the chemistry — then naturally lock ONE real photo. "
            "Don't sound like a store. Tease the shot, own the premium price, one clear close. "
            "Never stack two locks. Never beg. If he hesitates, flirt — don't dump a cheaper second photo."
        ),
        MODE_HARD_SELL: (
            "MODE=hard_sell: He's ready — push ONE clear locked offer with confidence. "
            "Still sound like Emma, not a store clerk. Anchor the value; one offer, not a lecture."
        ),
    }
    return f"{base} {mode_lines.get(decision.mode, mode_lines[MODE_RAPPORT])}"
