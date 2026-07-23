"""
Per-fan memory — durable client card + sales state.

Stored in Postgres JSONB (or .fan_memory.json fallback). Injected into the
reply prompt as a CLIENT CARD so Emma stays coherent without dumping the
entire chat history every turn.
"""
from __future__ import annotations

import os
import re
import threading
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Sequence

from db import fan_memory_store

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_FILE = os.path.join(_ROOT, ".fan_memory.json")
_LOCK = threading.Lock()

_MAX_FACTS = 20
_MAX_AVOID = 12

# Cheap kink/interest detection so Emma "remembers" what he's into.
_INTEREST_KEYWORDS = {
    "feet": ("feet", "pies", "foot"),
    "ass": ("ass", "culo", "booty", "fat ass"),
    "pussy": ("pussy", "coño", "cono"),
    "dirty talk": ("dirty", "nasty", "guarra", "talk dirty"),
    "domination": ("dominate", "domina", "boss", "obey", "sumiso", "submissive"),
    "roleplay": ("roleplay", "pretend", "fantasy", "fantasía"),
    # No videos/custom tags — vault is photos only; lorebook redirects those asks
    "photos": ("photo", "foto", "pic", "pics", "picture"),
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_all() -> Dict[str, dict]:
    """Bulk load (migrate / rare). Prefer get()/set_fan for per-fan updates."""
    return fan_memory_store.load_all()


def _save_all(data: Dict[str, dict]) -> None:
    fan_memory_store.save_all(data)


def _put(fan_uuid: str, mem: dict) -> None:
    fan_memory_store.set_fan(fan_uuid, mem)


def get(fan_uuid: str) -> dict:
    with _LOCK:
        mem = fan_memory_store.get_fan(fan_uuid)
        if mem:
            _ensure_card_fields(mem)
            before = (mem.get("name") or "").strip()
            _scrub_corrupt_name(mem)
            # Persist scrub so "Un" never comes back as confirmed name
            if before and not (mem.get("name") or "").strip():
                fan_memory_store.set_fan(fan_uuid, mem)
        return mem


def _scrub_corrupt_name(mem: dict) -> None:
    """Drop garbage names like 'Un' / 'De' that poison prompts and Spanish text."""
    raw = (mem.get("name") or "").strip()
    if not raw:
        return
    if _normalize_name(raw):
        return
    mem["name"] = ""
    mem["name_confirmed"] = False
    if isinstance(mem.get("profile"), dict):
        mem["profile"].pop("name", None)


def _guess_name_from_handle(handle: str) -> str:
    """Best-effort first name from @handle (not perfect, better than nothing)."""
    h = (handle or "").lstrip("@").strip()
    if not h:
        return ""
    for pref in ("im.", "its.", "the.", "real.", "official."):
        if h.lower().startswith(pref):
            h = h[len(pref) :]
    token = re.split(r"[._\-\d]+", h)[0] if h else ""
    if len(token) < 2 or len(token) > 16:
        return ""
    if not token.isalpha():
        return ""
    return token[:1].upper() + token[1:].lower()


def _blank(fan_handle: str) -> dict:
    return {
        "handle": fan_handle,
        "name": _guess_name_from_handle(fan_handle),
        "name_confirmed": False,
        "first_seen": _now(),
        "messages": 0,
        "interests": [],
        "total_spent": 0.0,
        "purchases": 0,
        "last_offer": None,
        "last_offer_at": None,
        "offers_today": 0,
        "offers_day": None,
        "last_reject_at": None,
        "chill_until": None,
        "last_mode": None,
        "last_offer_level": 0,
        "sent_media_uuids": [],
        "sent_content": [],  # [{uuid, label, level, kind, at}]
        "free_teases_sent": 0,
        "last_free_at": None,
        "prefer_spanish": False,
        "nudge_sent_episode": False,
        "nudge_episode_count": 0,
        "last_nudge_at": None,
        "last_nudge_style": None,
        "last_victim_nudge_at": None,
        "last_seen_by_fan_at": None,  # when we first saw isRead on Emma's last msg
        "last_fan_reaction_at": None,
        "last_fan_reaction_emoji": None,
        "last_fan_reaction_msg_uuid": None,
        "chat_heat_score": 0,
        "last_goodmorning_day": None,
        "welcome_sent_at": None,
        "welcome_kind": None,  # subscribe_delay | first_message | skipped_*
        "voice_notes_sent": 0,
        "voice_notes_today": 0,
        "voice_notes_day": None,
        "last_voice_at": None,
        # Protocol state (code-owned). Not Soft memory — hard turn commitments.
        # e.g. {"type": "voice", "since": iso, "source": "fan_ask", "hits": 2}
        "open_commitment": None,
        # Defend expensive unpaid lock → then concede cheaper (ppv_concede)
        "price_defend_hits": 0,
        "price_concede_done": False,
        "note": "",
        "status": "new",
        # Permanent client card (hybrid memory)
        "profile": {},
        "facts": [],
        "avoid": [],
        "summary": "",
        # Fanvue platform sync (insights API + session stats)
        "fanvue_status": None,
        "fanvue_spent_usd": 0.0,
        "fanvue_max_payment_usd": 0.0,
        "fanvue_spending_sources": {},
        "fanvue_last_purchase_at": None,
        "fanvue_sub_created_at": None,
        "fanvue_sub_renews_at": None,
        "fanvue_sub_auto_renew": False,
        "fanvue_insights_at": None,
        "session_stats": {},
        "key_fan_quotes": [],
        "interaction_digest": {},
        "interaction_digest_at": None,
        "digest_at_message_count": 0,
    }


def _ensure_card_fields(mem: dict) -> None:
    if not isinstance(mem.get("profile"), dict):
        mem["profile"] = {}
    if not isinstance(mem.get("facts"), list):
        mem["facts"] = []
    if not isinstance(mem.get("avoid"), list):
        mem["avoid"] = []
    if "summary" not in mem or mem.get("summary") is None:
        mem["summary"] = ""
    if "name_confirmed" not in mem:
        mem["name_confirmed"] = False
    if not isinstance(mem.get("sent_media_uuids"), list):
        mem["sent_media_uuids"] = []
    if not isinstance(mem.get("sent_content"), list):
        mem["sent_content"] = []
    if not isinstance(mem.get("failed_media_uuids"), list):
        mem["failed_media_uuids"] = []
    if not isinstance(mem.get("fanvue_spending_sources"), dict):
        mem["fanvue_spending_sources"] = {}
    if not isinstance(mem.get("session_stats"), dict):
        mem["session_stats"] = {}
    if not isinstance(mem.get("key_fan_quotes"), list):
        mem["key_fan_quotes"] = []
    if not isinstance(mem.get("interaction_digest"), dict):
        mem["interaction_digest"] = {}
    if "open_commitment" not in mem:
        mem["open_commitment"] = None
    if "price_defend_hits" not in mem:
        mem["price_defend_hits"] = 0
    if "price_concede_done" not in mem:
        mem["price_concede_done"] = False


_MAX_SENT_UUIDS = 200
_MAX_SENT_CONTENT = 60


def _catalog_lookup() -> Dict[str, Dict[str, Any]]:
    """media_uuid (+ previous aliases) → catalog item."""
    try:
        from core import vault_catalog

        items = vault_catalog.load_items()
    except Exception:
        return {}
    by: Dict[str, Dict[str, Any]] = {}
    for it in items:
        uid = it.get("media_uuid")
        if uid:
            by[uid] = it
        prev = it.get("media_uuid_previous")
        if prev:
            by.setdefault(prev, it)
    return by


def _append_sent(
    mem: dict,
    media_uuid: str,
    *,
    label: str = "",
    level: Optional[int] = None,
    kind: str = "ppv",
) -> None:
    """
    Idempotent: record UUID the fan has SEEN (free gift or purchased unlock).

    Unpaid PPV pitches must NOT call this — he never saw the photo.
    """
    if not media_uuid:
        return
    catalog = _catalog_lookup()
    item = catalog.get(media_uuid) or {}
    aliases = {media_uuid}
    if item.get("media_uuid"):
        aliases.add(item["media_uuid"])
    if item.get("media_uuid_previous"):
        aliases.add(item["media_uuid_previous"])

    sent = list(mem.get("sent_media_uuids") or [])
    for a in aliases:
        if a and a not in sent:
            sent.append(a)
    mem["sent_media_uuids"] = sent[-_MAX_SENT_UUIDS:]

    lab = (label or item.get("label") or "").strip() or media_uuid[:8]
    lvl = int(level if level is not None else item.get("level") or 0)
    content = list(mem.get("sent_content") or [])
    already = {str(c.get("uuid") or "") for c in content if isinstance(c, dict)}
    if media_uuid not in already and item.get("media_uuid") not in already:
        content.append(
            {
                "uuid": item.get("media_uuid") or media_uuid,
                "label": lab[:80],
                "level": lvl,
                "kind": kind,
                "at": _now(),
            }
        )
    mem["sent_content"] = content[-_MAX_SENT_CONTENT:]


def _msg_fan_saw_media(msg: dict) -> bool:
    """
    True if this creator message put media the fan can actually see.

    Free / unlocked → yes. Paid lock still unpaid → no (still sellable).
    """
    pricing = msg.get("pricing") or {}
    priced = bool(pricing) or msg.get("price") not in (None, 0, "0", 0.0)
    priced = priced or bool(
        msg.get("isPaid")
        or msg.get("isLocked")
        or msg.get("locked")
        or msg.get("ppv")
        or msg.get("isPpv")
        or msg.get("payToView")
    )
    if not priced:
        return True
    if msg.get("purchasedAt") or msg.get("unlockedAt"):
        return True
    if msg.get("purchased") is True or msg.get("isPurchased") is True:
        return True
    if msg.get("unlocked") is True or msg.get("isUnlocked") is True:
        return True
    status = str(
        msg.get("purchaseStatus") or msg.get("lockStatus") or ""
    ).lower()
    return status in ("purchased", "unlocked", "paid", "opened")


def merge_sent_from_chat(
    fan_uuid: str,
    messages: List[dict],
    creator_uuid: str,
    *,
    fan_handle: str = "",
) -> int:
    """
    Scan Fanvue history for media the fan has SEEN; merge into the client card.

    Unpaid PPV locks in chat are NOT marked sent — he never unlocked them.
    """
    if not messages or not creator_uuid:
        return 0

    def _sid(msg: dict) -> str:
        sender = msg.get("sender")
        if isinstance(sender, dict):
            return str(sender.get("uuid") or "")
        if isinstance(sender, str):
            return sender
        return str(msg.get("senderUuid") or msg.get("sender_uuid") or "")

    found: List[str] = []
    for msg in messages:
        if _sid(msg) != creator_uuid:
            continue
        if not _msg_fan_saw_media(msg):
            continue
        for uid in msg.get("mediaUuids") or []:
            if uid:
                found.append(str(uid))
    if not found:
        return 0
    return merge_sent_media(fan_uuid, found, fan_handle=fan_handle)


def merge_sent_media(
    fan_uuid: str,
    media_uuids: List[str],
    *,
    fan_handle: str = "",
) -> int:
    """Merge known-sent UUIDs into memory. Returns how many were newly added."""
    added = 0
    with _LOCK:
        mem = fan_memory_store.get_fan(fan_uuid) or _blank(fan_handle)
        _ensure_card_fields(mem)
        if fan_handle:
            mem["handle"] = fan_handle
        before = set(mem.get("sent_media_uuids") or [])
        catalog = _catalog_lookup()
        for uid in media_uuids:
            if not uid:
                continue
            item = catalog.get(uid) or {}
            kind = "free" if int(item.get("level") or -1) == 0 else "ppv"
            _append_sent(
                mem,
                uid,
                label=str(item.get("label") or ""),
                level=item.get("level"),
                kind=kind,
            )
        after = set(mem.get("sent_media_uuids") or [])
        added = len(after - before)
        # Keep free_teases_sent coherent with L0 UUIDs actually on the card
        l0 = sum(
            1
            for c in (mem.get("sent_content") or [])
            if isinstance(c, dict) and int(c.get("level") or -1) == 0
        )
        mem["free_teases_sent"] = max(int(mem.get("free_teases_sent") or 0), l0)
        _put(fan_uuid, mem)
    return added


def already_sent(fan_uuid: str, media_uuid: str) -> bool:
    mem = get(fan_uuid) or {}
    sent = set(mem.get("sent_media_uuids") or [])
    if media_uuid in sent:
        return True
    item = _catalog_lookup().get(media_uuid) or {}
    return bool(
        (item.get("media_uuid") and item["media_uuid"] in sent)
        or (item.get("media_uuid_previous") and item["media_uuid_previous"] in sent)
    )


def _dedupe_keep_order(items: List[str], *, limit: int) -> List[str]:
    seen = set()
    out: List[str] = []
    for raw in items:
        s = re.sub(r"\s+", " ", (raw or "").strip())
        if len(s) < 3:
            continue
        key = s.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(s[:180])
        if len(out) >= limit:
            break
    return out


def apply_card_update(
    fan_uuid: str,
    update: Dict[str, Any],
    *,
    fan_handle: str = "",
) -> dict:
    """
    Merge extractor output into the permanent client card.
    Only confirmed fan-stated facts should be passed here.
    """
    with _LOCK:
        mem = fan_memory_store.get_fan(fan_uuid) or _blank(fan_handle)
        _ensure_card_fields(mem)
        if fan_handle:
            mem["handle"] = fan_handle

        # Apply avoid / wrong-name clears BEFORE writing a new name
        avoid = list(mem.get("avoid") or [])
        for a in update.get("avoid") or []:
            if isinstance(a, str):
                avoid.append(a)
                m = re.search(
                    r"(?i)(?:name is not|not named|no (?:se )?llama|no es)\s+"
                    r"([A-Za-zÁÉÍÓÚÜÑáéíóúüñ]{2,16})",
                    a,
                )
                if m:
                    _clear_wrong_name(mem, m.group(1))
        mem["avoid"] = _dedupe_keep_order(avoid, limit=_MAX_AVOID)

        profile = update.get("profile") if isinstance(update.get("profile"), dict) else {}
        for k, v in profile.items():
            if v is None:
                continue
            s = str(v).strip()
            if not s or s.lower() in ("null", "none", "unknown", "n/a"):
                continue
            key = re.sub(r"[^a-z0-9_]", "", str(k).lower())[:32]
            if not key:
                continue
            if key == "name":
                _set_confirmed_name(mem, s)
                continue
            mem["profile"][key] = s[:80]

        facts = list(mem.get("facts") or [])
        for f in update.get("facts") or []:
            if isinstance(f, str):
                facts.append(f)
        mem["facts"] = _dedupe_keep_order(facts, limit=_MAX_FACTS)

        summary = (update.get("summary") or "").strip()
        if summary:
            mem["summary"] = summary[:500]

        _put(fan_uuid, mem)
        return mem


def patch_fanvue_platform(
    fan_uuid: str, patch: dict, *, fan_handle: str = ""
) -> dict:
    """Merge Fanvue insights / session stats / digest fields."""
    with _LOCK:
        mem = fan_memory_store.get_fan(fan_uuid) or _blank(fan_handle)
        _ensure_card_fields(mem)
        if fan_handle:
            mem["handle"] = fan_handle
        for k, v in (patch or {}).items():
            if v is None and k not in (
                "fanvue_last_purchase_at",
                "fanvue_sub_created_at",
                "fanvue_sub_renews_at",
            ):
                continue
            mem[k] = v
        _put(fan_uuid, mem)
        return mem


# Positive name statements only — NEVER bare "soy/i'm" (catches "soy un…", "no soy X").
_NAME_POSITIVE = re.compile(
    r"(?i)\b(?:"
    r"me\s+llamo|mi\s+nombre\s+es|my\s+name\s+is|call\s+me|"
    r"ll[aá]mame|puedes\s+llamarme|ll[aá]mamelo"
    r")\s+([A-Za-zÁÉÍÓÚÜÑáéíóúüñ]{2,16})\b"
)
# Negations / corrections — clear wrong name, never store it as his.
_NAME_NEGATE = re.compile(
    r"(?i)\b(?:"
    r"no\s+soy|no\s+me\s+llamo|no\s+es\s+mi\s+nombre|"
    r"my\s+name\s+is\s+not|i'?m\s+not(?:\s+called)?|"
    r"me\s+llamaste|me\s+dijiste|no\s+me\s+digas"
    r")\s+([A-Za-zÁÉÍÓÚÜÑáéíóúüñ]{2,16})\b"
)
_NAME_BLOCKLIST = frozenset(
    {
        "here", "just", "the", "not", "horny", "hard", "ready", "back",
        "good", "fine", "okay", "free", "down", "un", "una", "unos", "unas",
        "de", "del", "el", "la", "lo", "los", "las", "muy", "tan", "muy",
        "from", "your", "really", "still", "also", "only", "with",
    }
)


def _normalize_name(raw: str) -> str:
    s = (raw or "").strip()
    if len(s) < 2 or len(s) > 16:
        return ""
    if s.lower() in _NAME_BLOCKLIST:
        return ""
    return s[:1].upper() + s[1:].lower()


def _clear_wrong_name(mem: dict, wrong: str) -> None:
    wrong_n = _normalize_name(wrong)
    if not wrong_n:
        return
    cur = (mem.get("name") or "").strip()
    if cur.lower() == wrong_n.lower():
        mem["name"] = ""
        mem["name_confirmed"] = False
        if isinstance(mem.get("profile"), dict):
            mem["profile"].pop("name", None)


def _set_confirmed_name(mem: dict, name: str) -> None:
    name = _normalize_name(name)
    if not name:
        return
    mem["name"] = name
    mem["name_confirmed"] = True
    mem["profile"]["name"] = name


def observe_message(fan_uuid: str, fan_handle: str, text: str) -> dict:
    """Update memory from an incoming fan message (cheap heuristics)."""
    low = (text or "").lower()
    raw_text = text or ""
    with _LOCK:
        mem = fan_memory_store.get_fan(fan_uuid) or _blank(fan_handle)
        _ensure_card_fields(mem)
        mem["handle"] = fan_handle or mem.get("handle")
        if not mem.get("name"):
            mem["name"] = _guess_name_from_handle(mem.get("handle") or fan_handle)
            mem["name_confirmed"] = False
        mem["messages"] = int(mem.get("messages", 0)) + 1
        mem["last_seen"] = _now()
        # Fan spoke → new silence episode may start later
        mem["nudge_sent_episode"] = False
        mem["nudge_episode_count"] = 0
        mem["last_seen_by_fan_at"] = None

        # Corrections first — "no soy Carlos" / "me llamaste Carlos" must NEVER save Carlos
        for m in _NAME_NEGATE.finditer(raw_text):
            wrong = _normalize_name(m.group(1))
            if wrong:
                _clear_wrong_name(mem, wrong)
                avoid = list(mem.get("avoid") or [])
                avoid.append(f"his name is not {wrong}")
                mem["avoid"] = _dedupe_keep_order(avoid, limit=_MAX_AVOID)

        # Positive name wins (last match if several)
        positives = list(_NAME_POSITIVE.finditer(raw_text))
        if positives:
            _set_confirmed_name(mem, positives[-1].group(1))

        interests = set(mem.get("interests", []))
        for label, kws in _INTEREST_KEYWORDS.items():
            if any(k in low for k in kws):
                interests.add(label)
        mem["interests"] = sorted(interests)

        if mem.get("status") == "new" and mem["messages"] >= 3:
            mem["status"] = "warm"

        _put(fan_uuid, mem)
        return mem


def record_purchase(fan_uuid: str, amount: float, fan_handle: str = "") -> dict:
    with _LOCK:
        mem = fan_memory_store.get_fan(fan_uuid) or _blank(fan_handle)
        _ensure_card_fields(mem)
        mem["purchases"] = int(mem.get("purchases", 0)) + 1
        mem["total_spent"] = round(float(mem.get("total_spent", 0)) + float(amount), 2)
        mem["last_purchase_at"] = _now()
        mem["chill_until"] = None  # no post-purchase sell ban
        if mem["total_spent"] >= 200:
            mem["status"] = "whale"
        elif mem["total_spent"] > 0:
            mem["status"] = "spender"
        _put(fan_uuid, mem)
        return mem


def set_last_offer(
    fan_uuid: str,
    price: Optional[float] = None,
    fan_handle: str = "",
    *,
    level: Optional[int] = None,
    media_uuid: Optional[str] = None,
    label: Optional[str] = None,
    message_uuid: Optional[str] = None,
    expire_minutes: Optional[int] = None,
) -> None:
    """Record that Emma pitched (optionally with a price / media)."""
    with _LOCK:
        mem = fan_memory_store.get_fan(fan_uuid) or _blank(fan_handle)
        _ensure_card_fields(mem)
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if mem.get("offers_day") != today:
            mem["offers_today"] = 0
            mem["offers_day"] = today
        if price is not None:
            mem["last_offer"] = float(price)
        if level is not None:
            mem["last_offer_level"] = int(level)
        if media_uuid:
            # Pitch only — do NOT mark sent. Fan has not seen unpaid PPV.
            mem["last_ppv_media_uuid"] = media_uuid
            mem["last_ppv_at"] = _now()
            mem["last_ppv_price"] = float(price) if price is not None else None
            mem["last_ppv_label"] = label or ""
        if message_uuid:
            mem["last_ppv_message_uuid"] = message_uuid
        # Timed scarcity: unpaid lock expires unless purchased
        try:
            from config import config as _cfg

            mins = expire_minutes
            if mins is None:
                mins = int(getattr(_cfg, "PPV_EXPIRE_MINUTES", 30) or 30)
            if mins > 0 and media_uuid:
                mem["last_ppv_expires_at"] = (
                    datetime.now(timezone.utc).replace(microsecond=0)
                    + timedelta(minutes=int(mins))
                ).isoformat()
                mem["last_ppv_pending"] = True
        except Exception:
            pass
        mem["last_offer_at"] = _now()
        mem["offers_today"] = int(mem.get("offers_today", 0)) + 1
        # New lock episode — reset defend/concede FSM
        mem["price_defend_hits"] = 0
        mem["price_concede_done"] = False
        _put(fan_uuid, mem)


def mark_ppv_purchased(
    fan_uuid: str,
    media_uuid: str,
    *,
    fan_handle: str = "",
    label: str = "",
    level: Optional[int] = None,
    price: Optional[float] = None,
) -> None:
    """Fan unlocked a lock — NOW it counts as seen / not re-sellable."""
    if not media_uuid:
        return
    with _LOCK:
        mem = fan_memory_store.get_fan(fan_uuid) or _blank(fan_handle)
        _ensure_card_fields(mem)
        _append_sent(
            mem,
            media_uuid,
            label=label or str(mem.get("last_ppv_label") or ""),
            level=level
            if level is not None
            else mem.get("last_offer_level"),
            kind="ppv_purchased",
        )
        if price is not None and float(price) > 0:
            # Spend/purchase counters if caller didn't already bump
            pass
        _put(fan_uuid, mem)


def scrub_unseen_ppv_from_sent(
    fan_uuid: str,
    *,
    fan_handle: str = "",
) -> int:
    """
    Remove paid-catalog UUIDs from sent_* when the fan never bought.

    Legacy bug: pitches were marked sent on attach. Returns how many UUIDs removed.
    """
    with _LOCK:
        mem = fan_memory_store.get_fan(fan_uuid) or _blank(fan_handle)
        _ensure_card_fields(mem)
        purchases = int(mem.get("purchases") or 0)
        spent = float(mem.get("total_spent") or 0)
        if purchases > 0 or spent > 0:
            # Buyers: only drop pending open lock from sent if wrongly present
            pending = (mem.get("last_ppv_media_uuid") or "").strip()
            if not pending or not mem.get("last_ppv_pending"):
                return 0
            sent = list(mem.get("sent_media_uuids") or [])
            before = len(sent)
            catalog = _catalog_lookup()
            item = catalog.get(pending) or {}
            drop = {pending, item.get("media_uuid"), item.get("media_uuid_previous")}
            drop = {u for u in drop if u}
            sent = [u for u in sent if u not in drop]
            mem["sent_media_uuids"] = sent
            _put(fan_uuid, mem)
            return max(0, before - len(sent))

        catalog = _catalog_lookup()
        paid_uids = set()
        for it in catalog.values():
            if int(it.get("level") or 0) >= 1:
                if it.get("media_uuid"):
                    paid_uids.add(it["media_uuid"])
                if it.get("media_uuid_previous"):
                    paid_uids.add(it["media_uuid_previous"])

        sent = list(mem.get("sent_media_uuids") or [])
        before = len(sent)
        kept = [u for u in sent if u not in paid_uids]
        mem["sent_media_uuids"] = kept
        # Drop paid pitch rows from ficha; keep free gifts
        content = [
            c
            for c in (mem.get("sent_content") or [])
            if isinstance(c, dict)
            and (
                int(c.get("level") or 0) <= 0
                or str(c.get("kind") or "") == "free"
            )
        ]
        mem["sent_content"] = content[-_MAX_SENT_CONTENT:]
        _put(fan_uuid, mem)
        return max(0, before - len(kept))


def set_pending_ppv_from_chat(
    fan_uuid: str,
    *,
    media_uuid: str,
    message_uuid: str,
    price: Optional[float] = None,
    label: str = "",
    sent_at: Optional[str] = None,
    fan_handle: str = "",
    expire_minutes: Optional[int] = None,
) -> None:
    """Align pending lock clock with an unpaid message found in Fanvue chat."""
    with _LOCK:
        mem = fan_memory_store.get_fan(fan_uuid) or _blank(fan_handle)
        _ensure_card_fields(mem)
        prev_msg = (mem.get("last_ppv_message_uuid") or "").strip()
        prev_exp = None
        try:
            if mem.get("last_ppv_expires_at"):
                prev_exp = datetime.fromisoformat(
                    str(mem.get("last_ppv_expires_at")).replace("Z", "+00:00")
                )
        except ValueError:
            prev_exp = None

        if media_uuid:
            mem["last_ppv_media_uuid"] = media_uuid
        if message_uuid:
            mem["last_ppv_message_uuid"] = message_uuid
        if price is not None:
            mem["last_ppv_price"] = float(price)
        if label:
            mem["last_ppv_label"] = label
        if sent_at:
            mem["last_ppv_at"] = sent_at
        mem["last_ppv_pending"] = True
        try:
            from config import config as _cfg

            mins = expire_minutes
            if mins is None:
                mins = int(getattr(_cfg, "PPV_EXPIRE_MINUTES", 30) or 30)
            base = None
            if sent_at:
                try:
                    base = datetime.fromisoformat(
                        str(sent_at).replace("Z", "+00:00")
                    )
                except ValueError:
                    base = None
            if base is None:
                base = datetime.now(timezone.utc)
            now = datetime.now(timezone.utc)
            same_msg = prev_msg == (message_uuid or "").strip()
            if same_msg and prev_exp and prev_exp > now:
                mem["last_ppv_expires_at"] = prev_exp.isoformat()
            else:
                mem["last_ppv_expires_at"] = (
                    base.replace(microsecond=0) + timedelta(minutes=int(mins))
                ).isoformat()
        except Exception:
            pass
        _put(fan_uuid, mem)


def clear_pending_ppv(
    fan_uuid: str,
    *,
    fan_handle: str = "",
    reason: str = "expired",
) -> None:
    """Clear unpaid-lock tracking after unsend or purchase. Keeps sent_media history."""
    with _LOCK:
        mem = fan_memory_store.get_fan(fan_uuid) or _blank(fan_handle)
        _ensure_card_fields(mem)
        mem["last_ppv_message_uuid"] = None
        mem["last_ppv_expires_at"] = None
        mem["last_ppv_pending"] = False
        mem["last_ppv_expired_at"] = _now()
        mem["last_ppv_expire_reason"] = reason
        # Reset defend counter; concede_done stays if we just conceded
        # (new attach via set_last_offer clears it for the next lock).
        if reason != "price_concede":
            mem["price_defend_hits"] = 0
            mem["price_concede_done"] = False
        else:
            mem["price_defend_hits"] = 0
            mem["price_concede_done"] = True
        # Allow a fresh lock after expiry (cooloff uses last_ppv_at — keep it)
        _put(fan_uuid, mem)


def set_price_defend_hits(
    fan_uuid: str,
    *,
    hits: int,
    fan_handle: str = "",
) -> int:
    with _LOCK:
        mem = fan_memory_store.get_fan(fan_uuid) or _blank(fan_handle)
        _ensure_card_fields(mem)
        mem["price_defend_hits"] = max(0, int(hits))
        _put(fan_uuid, mem)
        return int(mem["price_defend_hits"])


def mark_price_conceded(fan_uuid: str, *, fan_handle: str = "") -> None:
    with _LOCK:
        mem = fan_memory_store.get_fan(fan_uuid) or _blank(fan_handle)
        _ensure_card_fields(mem)
        mem["price_concede_done"] = True
        mem["price_defend_hits"] = 0
        _put(fan_uuid, mem)


def bump_price_objection_step(fan_uuid: str, *, fan_handle: str = "") -> int:
    """Advance objection script step 0→1→2→3 across turns. Returns new step."""
    with _LOCK:
        mem = fan_memory_store.get_fan(fan_uuid) or _blank(fan_handle)
        _ensure_card_fields(mem)
        step = int(mem.get("price_objection_step") or 0)
        step = min(3, step + 1)
        mem["price_objection_step"] = step
        _put(fan_uuid, mem)
        return step


def reset_price_objection_step(fan_uuid: str, *, fan_handle: str = "") -> None:
    with _LOCK:
        mem = fan_memory_store.get_fan(fan_uuid) or _blank(fan_handle)
        _ensure_card_fields(mem)
        mem["price_objection_step"] = 0
        _put(fan_uuid, mem)


_REAL_FAN_UUID = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.I,
)


def is_real_fan_uuid(fan_uuid: str) -> bool:
    """Fanvue chat UUIDs only — skip test-fan-* junk that 400-loops expire."""
    u = (fan_uuid or "").strip()
    if not u or u.startswith("test-fan") or u.startswith("test_"):
        return False
    return bool(_REAL_FAN_UUID.match(u))


def is_junk_fan_handle(handle: str) -> bool:
    """Offline sim / test handles must never enter the live poll loop."""
    h = (handle or "").strip().lower().lstrip("@")
    if not h:
        return False
    return (
        h.startswith("sim_")
        or h.startswith("sim-")
        or h.startswith("test-fan")
        or h.startswith("test_")
        or h.startswith("sim_llm")
    )


def soft_delete_fan(fan_uuid: str, *, reason: str = "") -> None:
    """Drop a ghost fan from memory so poll stops scanning it."""
    if not fan_uuid:
        return
    try:
        fan_memory_store.set_fan(
            fan_uuid,
            {
                "_deleted": True,
                "handle": "",
                "messages": 0,
                "_delete_reason": (reason or "ghost")[:80],
            },
        )
    except Exception:
        pass


def pending_ppv_candidates() -> List[tuple]:
    """
    Fans with a timed unpaid lock still tracked.
    Returns list of (fan_uuid, mem).
    """
    out: List[tuple] = []
    try:
        all_mem = fan_memory_store.load_all()
    except Exception:
        return out
    for fid, mem in (all_mem or {}).items():
        if not isinstance(mem, dict):
            continue
        if mem.get("_deleted"):
            continue
        if not is_real_fan_uuid(str(fid)):
            continue
        # Explicit pending flag (preferred). Legacy: message uuid + expires still pending.
        pending = mem.get("last_ppv_pending")
        if pending is False:
            continue
        if mem.get("last_ppv_media_uuid") and (
            pending is True
            or mem.get("last_ppv_message_uuid")
            or mem.get("last_ppv_expires_at")
        ):
            out.append((fid, mem))
    return out


def record_free_tease(
    fan_uuid: str,
    media_uuid: str,
    *,
    fan_handle: str = "",
    label: str = "",
    level: int = 0,
) -> None:
    """Record an unlocked L0 tease — tracks UUID so it never repeats for this fan."""
    with _LOCK:
        mem = fan_memory_store.get_fan(fan_uuid) or _blank(fan_handle)
        _ensure_card_fields(mem)
        _append_sent(
            mem,
            media_uuid,
            label=label or "",
            level=level,
            kind="free",
        )
        mem["last_free_at"] = _now()
        mem["last_free_media_uuid"] = media_uuid
        mem["last_free_label"] = label or ""
        mem["free_teases_sent"] = int(mem.get("free_teases_sent") or 0) + 1
        if level is not None:
            # Don't overwrite a higher paid last_offer_level with 0
            if int(mem.get("last_offer_level") or 0) <= 0:
                mem["last_offer_level"] = int(level)
        _put(fan_uuid, mem)


def mark_media_attempt(
    fan_uuid: str,
    media_uuid: str,
    *,
    fan_handle: str = "",
) -> None:
    """UUID tried but not verified in chat — block repeats without claiming delivery."""
    if not media_uuid:
        return
    with _LOCK:
        mem = fan_memory_store.get_fan(fan_uuid) or _blank(fan_handle)
        _ensure_card_fields(mem)
        failed = list(mem.get("failed_media_uuids") or [])
        if media_uuid not in failed:
            failed.append(media_uuid)
        mem["failed_media_uuids"] = failed[-40:]
        _put(fan_uuid, mem)


def clear_ghost_free(
    fan_uuid: str,
    media_uuid: str,
    *,
    fan_handle: str = "",
) -> bool:
    """
    Memory said a free was sent but Fanvue chat does not have that media.
    Strip the ghost so Emma stops claiming a gift that never arrived.
    """
    if not media_uuid:
        return False
    with _LOCK:
        mem = fan_memory_store.get_fan(fan_uuid) or _blank(fan_handle)
        _ensure_card_fields(mem)
        changed = False
        sent = list(mem.get("sent_media_uuids") or [])
        if media_uuid in sent:
            sent = [u for u in sent if u != media_uuid]
            mem["sent_media_uuids"] = sent
            changed = True
        content = [
            c
            for c in (mem.get("sent_content") or [])
            if not (
                isinstance(c, dict)
                and c.get("uuid") == media_uuid
                and (c.get("kind") == "free" or int(c.get("level") or -1) == 0)
            )
        ]
        if len(content) != len(mem.get("sent_content") or []):
            mem["sent_content"] = content
            changed = True
        if mem.get("last_free_media_uuid") == media_uuid:
            mem["last_free_media_uuid"] = None
            mem["last_free_label"] = None
            mem["last_free_at"] = None
            changed = True
        l0 = sum(
            1
            for c in (mem.get("sent_content") or [])
            if isinstance(c, dict) and int(c.get("level") or -1) == 0
        )
        if int(mem.get("free_teases_sent") or 0) != l0:
            mem["free_teases_sent"] = l0
            changed = True
        failed = list(mem.get("failed_media_uuids") or [])
        if media_uuid not in failed:
            failed.append(media_uuid)
            mem["failed_media_uuids"] = failed[-40:]
            changed = True
        if changed:
            _put(fan_uuid, mem)
        return changed


def record_reject(fan_uuid: str, fan_handle: str = "", minutes: int = 120) -> dict:
    """Fan pushed back on price / said later — log + advance objection ladder."""
    del minutes  # legacy arg; cooloff window removed
    with _LOCK:
        mem = fan_memory_store.get_fan(fan_uuid) or _blank(fan_handle)
        _ensure_card_fields(mem)
        mem["last_reject_at"] = _now()
        mem["chill_until"] = None  # never block sell via chill
        step = int(mem.get("price_objection_step") or 0)
        mem["price_objection_step"] = min(3, step + 1)
        _put(fan_uuid, mem)
        return mem


def set_last_mode(fan_uuid: str, mode: str, fan_handle: str = "") -> None:
    with _LOCK:
        mem = fan_memory_store.get_fan(fan_uuid) or _blank(fan_handle)
        _ensure_card_fields(mem)
        mem["last_mode"] = mode
        _put(fan_uuid, mem)


def record_technique(
    fan_uuid: str,
    technique: str,
    *,
    fan_handle: str = "",
    used_rival_fan: bool = False,
) -> None:
    """Track recent manipulation techniques + rival-fan bit for anti-repeat."""
    if not fan_uuid or not technique:
        return
    with _LOCK:
        mem = fan_memory_store.get_fan(fan_uuid) or _blank(fan_handle)
        _ensure_card_fields(mem)
        recent = list(mem.get("recent_techniques") or [])
        recent.append(str(technique)[:80])
        mem["recent_techniques"] = recent[-8:]
        if used_rival_fan:
            mem["rival_fan_used"] = True
            mem["rival_fan_last_msgs"] = int(mem.get("messages") or 0)
        _put(fan_uuid, mem)


def recent_techniques(fan_uuid: str, *, n: int = 4) -> List[str]:
    if not fan_uuid:
        return []
    mem = get(fan_uuid) or {}
    recent = list(mem.get("recent_techniques") or [])
    return [str(x) for x in recent[-n:] if x]


def sell_pressure_paused(
    mem: Optional[dict],
    *,
    recent_techniques: Optional[Sequence[str]] = None,
    hours: float = 6.0,
) -> bool:
    """
    After soft decline / price push — no unlock nag for a few hours (zero spenders).
  """
    mem = mem or {}
    if float(mem.get("total_spent") or 0) > 0:
        return False
    recent = [str(t).upper() for t in (recent_techniques or mem.get("recent_techniques") or []) if t]
    if any("SOFT EXIT" in t for t in recent[-3:]):
        return True
    raw = mem.get("last_reject_at")
    if not raw:
        return False
    try:
        lr = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        if lr.tzinfo is None:
            lr = lr.replace(tzinfo=timezone.utc)
    except ValueError:
        return False
    return datetime.now(timezone.utc) - lr < timedelta(hours=hours)


def set_prefer_spanish(fan_uuid: str, prefer: bool, fan_handle: str = "") -> None:
    from config import config

    # ENGLISH_ONLY: never stick Spanish preference
    if getattr(config, "ENGLISH_ONLY", True):
        prefer = False
    with _LOCK:
        mem = fan_memory_store.get_fan(fan_uuid) or _blank(fan_handle)
        _ensure_card_fields(mem)
        mem["prefer_spanish"] = bool(prefer)
        _put(fan_uuid, mem)


def mark_pushback_active(
    fan_uuid: str,
    *,
    fan_handle: str = "",
    reason: str = "",
) -> None:
    """Fan called us out (bot/AI/script) — no heat until cleared."""
    with _LOCK:
        mem = fan_memory_store.get_fan(fan_uuid) or _blank(fan_handle)
        _ensure_card_fields(mem)
        mem["pushback_active"] = True
        mem["pushback_reason"] = (reason or "pushback")[:120]
        mem["pushback_at"] = _now()
        _put(fan_uuid, mem)


def clear_pushback_active(fan_uuid: str, *, fan_handle: str = "") -> None:
    with _LOCK:
        mem = fan_memory_store.get_fan(fan_uuid) or _blank(fan_handle)
        _ensure_card_fields(mem)
        mem["pushback_active"] = False
        mem["pushback_reason"] = ""
        mem["pushback_at"] = None
        _put(fan_uuid, mem)


def mark_photo_refusal_active(
    fan_uuid: str,
    *,
    fan_handle: str = "",
    reason: str = "",
) -> None:
    """Fan declined to send his pic — stop ASK PIC / pressure."""
    mark_fan_boundary_active(fan_uuid, fan_handle=fan_handle, reason=reason or "photo_refusal")


def mark_fan_boundary_active(
    fan_uuid: str,
    *,
    fan_handle: str = "",
    reason: str = "",
) -> None:
    """Fan upset / privacy boundary — no sell, no pic asks, no heat."""
    with _LOCK:
        mem = fan_memory_store.get_fan(fan_uuid) or _blank(fan_handle)
        _ensure_card_fields(mem)
        mem["fan_boundary_active"] = True
        mem["fan_boundary_reason"] = (reason or "boundary")[:120]
        mem["fan_boundary_at"] = _now()
        mem["photo_refusal_active"] = True
        mem["photo_refusal_reason"] = (reason or "boundary")[:120]
        mem["photo_refusal_at"] = _now()
        mem["boundary_warm_streak"] = 0
        _put(fan_uuid, mem)


def clear_photo_refusal_active(fan_uuid: str, *, fan_handle: str = "") -> None:
    clear_fan_boundary_active(fan_uuid, fan_handle=fan_handle)


def clear_fan_boundary_active(fan_uuid: str, *, fan_handle: str = "") -> None:
    with _LOCK:
        mem = fan_memory_store.get_fan(fan_uuid) or _blank(fan_handle)
        _ensure_card_fields(mem)
        mem["fan_boundary_active"] = False
        mem["fan_boundary_reason"] = ""
        mem["fan_boundary_at"] = None
        mem["photo_refusal_active"] = False
        mem["photo_refusal_reason"] = ""
        mem["photo_refusal_at"] = None
        mem["boundary_warm_streak"] = 0
        _put(fan_uuid, mem)


def record_boundary_warm_turn(
    fan_uuid: str,
    *,
    fan_handle: str = "",
) -> int:
    """Fan wrote warmly after boundary — count toward thaw."""
    with _LOCK:
        mem = fan_memory_store.get_fan(fan_uuid) or _blank(fan_handle)
        _ensure_card_fields(mem)
        streak = int(mem.get("boundary_warm_streak") or 0) + 1
        mem["boundary_warm_streak"] = streak
        _put(fan_uuid, mem)
        return streak


def reset_boundary_warm_streak(fan_uuid: str, *, fan_handle: str = "") -> None:
    with _LOCK:
        mem = fan_memory_store.get_fan(fan_uuid) or _blank(fan_handle)
        if not mem:
            return
        mem["boundary_warm_streak"] = 0
        _put(fan_uuid, mem)


def thaw_boundary_after_warmth(
    fan_uuid: str,
    *,
    fan_handle: str = "",
    min_streak: int = 3,
) -> bool:
    """
    After enough warm fan messages, clear upset boundary but keep photo_refusal
    so we never ask for his pic again.
    """
    with _LOCK:
        mem = fan_memory_store.get_fan(fan_uuid) or _blank(fan_handle)
        if int(mem.get("boundary_warm_streak") or 0) < min_streak:
            return False
        mem["fan_boundary_active"] = False
        mem["fan_boundary_reason"] = ""
        mem["reengage_paused_until_fan_writes"] = False
        mem["reengage_pause_reason"] = ""
        # photo_refusal_active stays True — no ask-pic pressure later
        _put(fan_uuid, mem)
        return True


def mark_nudge(
    fan_uuid: str,
    kind: str,
    fan_handle: str = "",
    *,
    style: str = "",
) -> None:
    """kind: 'nudge' (hot/cold ladder) or 'goodmorning' (next-day)."""
    with _LOCK:
        mem = fan_memory_store.get_fan(fan_uuid) or _blank(fan_handle)
        _ensure_card_fields(mem)
        if kind == "nudge":
            count = int(mem.get("nudge_episode_count") or 0) + 1
            mem["nudge_episode_count"] = count
            mem["last_nudge_at"] = _now()
            if style:
                mem["last_nudge_style"] = style
            if style == "victim_soft":
                mem["last_victim_nudge_at"] = _now()
            # Cap episode after one nudge per silence window
            if count >= 1:
                mem["nudge_sent_episode"] = True
        elif kind == "goodmorning":
            from core import persona_time

            mem["last_goodmorning_day"] = persona_time.la_today()
            mem["nudge_sent_episode"] = True
            mem["nudge_episode_count"] = int(mem.get("nudge_episode_count") or 0) + 1
            if style:
                mem["last_nudge_style"] = style
        _put(fan_uuid, mem)


def get_commitment(fan_uuid: str) -> Optional[dict]:
    mem = get(fan_uuid)
    c = mem.get("open_commitment") if mem else None
    return c if isinstance(c, dict) and c.get("type") else None


def set_commitment(
    fan_uuid: str,
    *,
    ctype: str,
    source: str = "",
    fan_handle: str = "",
    bump: bool = True,
) -> dict:
    """
    Persist a hard turn commitment (voice, etc.). Code owns this — not the LLM.
    """
    with _LOCK:
        mem = fan_memory_store.get_fan(fan_uuid) or _blank(fan_handle)
        _ensure_card_fields(mem)
        prev = mem.get("open_commitment") if isinstance(mem.get("open_commitment"), dict) else None
        if prev and prev.get("type") == ctype:
            hits = int(prev.get("hits") or 1) + (1 if bump else 0)
            since = prev.get("since") or _now()
            src = (source or prev.get("source") or "")[:80]
        else:
            hits = 1
            since = _now()
            src = (source or "")[:80]
        mem["open_commitment"] = {
            "type": ctype,
            "since": since,
            "source": src,
            "hits": hits,
            "updated_at": _now(),
        }
        _put(fan_uuid, mem)
        return dict(mem["open_commitment"])


def clear_commitment(
    fan_uuid: str,
    *,
    ctype: Optional[str] = None,
    fan_handle: str = "",
) -> None:
    with _LOCK:
        mem = fan_memory_store.get_fan(fan_uuid) or _blank(fan_handle)
        _ensure_card_fields(mem)
        cur = mem.get("open_commitment")
        if not isinstance(cur, dict):
            mem["open_commitment"] = None
            _put(fan_uuid, mem)
            return
        if ctype is None or cur.get("type") == ctype:
            mem["open_commitment"] = None
        _put(fan_uuid, mem)


def record_voice_note(
    fan_uuid: str,
    fan_handle: str = "",
    *,
    script: str = "",
) -> None:
    with _LOCK:
        mem = fan_memory_store.get_fan(fan_uuid) or _blank(fan_handle)
        _ensure_card_fields(mem)
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if mem.get("voice_notes_day") != today:
            mem["voice_notes_day"] = today
            mem["voice_notes_today"] = 0
        mem["voice_notes_today"] = int(mem.get("voice_notes_today") or 0) + 1
        mem["voice_notes_sent"] = int(mem.get("voice_notes_sent") or 0) + 1
        mem["last_voice_at"] = _now()
        if script:
            mem["last_voice_script"] = script[:200]
        # Delivered → clear protocol debt
        cur = mem.get("open_commitment")
        if isinstance(cur, dict) and cur.get("type") == "voice":
            mem["open_commitment"] = None
        _put(fan_uuid, mem)


def mark_seen_by_fan(fan_uuid: str, fan_handle: str = "") -> Optional[str]:
    """
    First time Fanvue shows Emma's last message as isRead — stamp visto clock.
    Returns ISO timestamp (existing or new). None if fan_uuid missing.
    """
    if not fan_uuid:
        return None
    with _LOCK:
        mem = fan_memory_store.get_fan(fan_uuid) or _blank(fan_handle)
        _ensure_card_fields(mem)
        if mem.get("last_seen_by_fan_at"):
            return str(mem["last_seen_by_fan_at"])
        stamp = _now()
        mem["last_seen_by_fan_at"] = stamp
        _put(fan_uuid, mem)
        return stamp


def record_fan_reaction(
    fan_uuid: str,
    *,
    emoji: str,
    message_uuid: str = "",
    fan_handle: str = "",
    actor_uuid: str = "",
) -> None:
    """Fan reacted to a creator message (webhook creator.message.reaction)."""
    if not fan_uuid:
        return
    with _LOCK:
        mem = fan_memory_store.get_fan(fan_uuid) or _blank(fan_handle)
        _ensure_card_fields(mem)
        if fan_handle:
            mem["handle"] = fan_handle
        mem["last_fan_reaction_at"] = _now()
        mem["last_fan_reaction_emoji"] = (emoji or "")[:16]
        if message_uuid:
            mem["last_fan_reaction_msg_uuid"] = message_uuid
        if actor_uuid:
            mem["last_fan_reaction_actor"] = actor_uuid
        _put(fan_uuid, mem)


def set_chat_heat_score(fan_uuid: str, score: int, fan_handle: str = "") -> None:
    if not fan_uuid:
        return
    with _LOCK:
        mem = fan_memory_store.get_fan(fan_uuid) or _blank(fan_handle)
        _ensure_card_fields(mem)
        mem["chat_heat_score"] = max(0, min(100, int(score)))
        _put(fan_uuid, mem)


def mark_welcome_sent(
    fan_uuid: str, fan_handle: str = "", *, kind: str = "first_message"
) -> None:
    """Record that we already welcomed this fan (subscribe DM or first reply)."""
    if not fan_uuid:
        return
    with _LOCK:
        mem = fan_memory_store.get_fan(fan_uuid) or _blank(fan_handle)
        _ensure_card_fields(mem)
        if fan_handle:
            mem["handle"] = fan_handle
        if not mem.get("welcome_sent_at"):
            mem["welcome_sent_at"] = _now()
        mem["welcome_kind"] = kind or mem.get("welcome_kind") or "first_message"
        _put(fan_uuid, mem)


def set_note(fan_uuid: str, note: str, fan_handle: str = "") -> None:
    with _LOCK:
        mem = fan_memory_store.get_fan(fan_uuid) or _blank(fan_handle)
        _ensure_card_fields(mem)
        mem["note"] = note
        _put(fan_uuid, mem)


def set_last_fan_image(
    fan_uuid: str,
    description: str,
    *,
    media_uuid: Optional[str] = None,
    fan_handle: str = "",
) -> None:
    """Remember what Grok saw in the fan's last photo (for 'qué es?' follow-ups)."""
    with _LOCK:
        mem = fan_memory_store.get_fan(fan_uuid) or _blank(fan_handle)
        _ensure_card_fields(mem)
        mem["last_fan_image_desc"] = (description or "").strip()[:800]
        mem["last_fan_image_at"] = _now()
        if media_uuid:
            mem["last_fan_image_uuid"] = media_uuid
        _put(fan_uuid, mem)


def render_block(fan_uuid: str) -> str:
    """CLIENT CARD + sales state for the reply prompt."""
    mem = get(fan_uuid)
    if not mem:
        return ""
    _ensure_card_fields(mem)

    lines: List[str] = [
        "CLIENT CARD (confirmed facts only — do NOT invent beyond this + recent chat):",
        "SYSTEM TRUTH: spending data below comes from Fanvue API — it is always correct. "
        "If the fan CLAIMS he spent money, bought PPV, or unlocked content but this card shows otherwise — "
        "do NOT agree or validate. React to his mood without confirming false claims.",
    ]
    try:
        from core.fanvue_insights import render_platform_block

        platform = render_platform_block(mem)
        if platform:
            lines.append(platform)
    except Exception:
        pass
    if mem.get("handle"):
        lines.append(f"- Handle: @{mem['handle']}")
    name = (mem.get("name") or "").strip()
    if name:
        conf = (
            "confirmed"
            if mem.get("name_confirmed")
            else "guessed from handle — verify before relying"
        )
        lines.append(
            f"- Name: {name} ({conf}). Use OCCASIONALLY (every few replies) for intimacy; "
            f"mix with pet names (babe/baby/handsome/cielo/guapo). "
            f"Never stamp \"Ay {name}\" every message."
        )

    profile = mem.get("profile") or {}
    for key in ("age", "city", "job", "relationship", "kids", "hobbies"):
        if profile.get(key):
            lines.append(f"- {key.capitalize()}: {profile[key]}")
    for key, val in profile.items():
        if key in ("name", "age", "city", "job", "relationship", "kids", "hobbies"):
            continue
        if val:
            lines.append(f"- {key}: {val}")

    facts = mem.get("facts") or []
    if facts:
        lines.append("- Durable facts:")
        for f in facts[-12:]:
            lines.append(f"  • {f}")

    avoid = mem.get("avoid") or []
    if avoid:
        lines.append("- Avoid / never invent:")
        for a in avoid[-8:]:
            lines.append(f"  • {a}")

    if mem.get("summary"):
        lines.append(f"- Rolling summary: {mem['summary']}")

    lines.append(
        "- Language: ENGLISH ONLY forever — even if he writes Spanish; never mix"
    )

    lines.append(
        f"- Status: {mem.get('status') or 'new'} | msgs: {mem.get('messages') or 0} | "
        f"spent: ${mem.get('total_spent') or 0} | purchases: {mem.get('purchases') or 0}"
    )
    if mem.get("interests"):
        # Never surface video/custom as sellable — vault is photos only
        _skip = {"videos", "video", "custom", "customs", "clips", "clip", "4k"}
        into = [
            i for i in mem["interests"]
            if str(i).strip().lower() not in _skip
        ]
        if into:
            lines.append(f"- Into: {', '.join(into)}")
        lines.append("- Vault: PHOTOS only (never promise video/custom)")
    if mem.get("last_offer"):
        lines.append(f"- Last offer: ${mem['last_offer']}")

    # Content already delivered — never re-gift / re-lock the same shot
    sent_content = [c for c in (mem.get("sent_content") or []) if isinstance(c, dict)]
    if sent_content:
        lines.append(
            "- ALREADY SENT to him (NEVER re-send the same photo / same media):"
        )
        for c in sent_content[-4:]:
            kind = "FREE" if (c.get("kind") == "free" or int(c.get("level") or -1) == 0) else "PPV"
            lines.append(
                f"  • {kind} L{c.get('level', '?')}: {c.get('label') or c.get('uuid', '')[:8]}"
            )
    elif mem.get("sent_media_uuids"):
        n = len(mem["sent_media_uuids"])
        lines.append(f"- Already sent media: {n} item(s) on file — never repeat those UUIDs")

    if mem.get("note"):
        lines.append(f"- Operator note: {mem['note']}")
    if mem.get("last_fan_image_desc"):
        lines.append(
            f"- Last photo HE sent (vision): {mem['last_fan_image_desc'][:180]}"
        )

    # Chat coach notes — what Emma is doing wrong with this specific fan
    coach_notes = mem.get("coach_notes") or []
    if coach_notes:
        lines.append("CHAT COACH (what Emma must improve with this fan — act on these):")
        for note in coach_notes[:5]:
            lines.append(f"  ! {note}")

    return "\n".join(lines)
