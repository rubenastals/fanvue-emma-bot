"""
Fanvue platform insights + session stats → CLIENT CARD.

Syncs real spend/subscription from GET /insights/fans/{uuid}.
Builds 24h session counts from chat messages.
Optional DeepSeek digest (Fanvue-style recap) for Emma's prompt context.
"""
from __future__ import annotations

import json
import re
import threading
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from config import config

try:
    from core.ppv_expiry import _msg_price_dollars
except ImportError:
    _msg_price_dollars = None  # type: ignore

_AUTOMATED = re.compile(r"^AUTOMATED_", re.I)
_KEY_QUOTE = re.compile(
    r"(?i)\b("
    r"destrozad|sosa|aburr|gord|gay|marido|infiel|engañ|"
    r"paja|duro|mojad|gratis|no (?:compro|pago|quiero pagar)|"
    r"lástima|caro|pelad|broke|horny|hard|wet|"
    r"te quiero|te extra|thinking about"
    r")"
)

_digest_lock = threading.Lock()
_digest_inflight: set[str] = set()


def _parse_ts(raw: Optional[str]) -> Optional[datetime]:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _insights_stale(mem: dict) -> bool:
    hours = float(getattr(config, "FANVUE_INSIGHTS_SYNC_HOURS", 6) or 6)
    last = _parse_ts(mem.get("fanvue_insights_at"))
    if not last:
        return True
    return datetime.now(timezone.utc) - last >= timedelta(hours=hours)


def _digest_stale(mem: dict) -> bool:
    every = int(getattr(config, "FANVUE_DIGEST_EVERY_MESSAGES", 25) or 25)
    msgs = int(mem.get("messages") or 0)
    last_at = int(mem.get("digest_at_message_count") or 0)
    if msgs - last_at >= every:
        return True
    hours = float(getattr(config, "FANVUE_DIGEST_MAX_AGE_HOURS", 12) or 12)
    last = _parse_ts(mem.get("interaction_digest_at"))
    if not last:
        return msgs >= 8
    return datetime.now(timezone.utc) - last >= timedelta(hours=hours)


def _cents_to_usd(cents: Any) -> float:
    try:
        return round(float(cents or 0) / 100.0, 2)
    except (TypeError, ValueError):
        return 0.0


def sync_fan_insights(fv, fan_uuid: str, *, fan_handle: str = "") -> Optional[dict]:
    """Fetch Fanvue insights and persist to fan memory. Returns raw API payload."""
    from core import fan_memory

    mem = fan_memory.get(fan_uuid) or {}
    try:
        data = fv.get_fan_insights(fan_uuid)
    except Exception as e:
        print(f"   ⚠️ fanvue insights sync failed: {type(e).__name__}: {e}")
        return None
    if not isinstance(data, dict):
        return None

    spending = data.get("spending") or {}
    total = spending.get("total") or {}
    max_pay = spending.get("maxSinglePayment") or {}
    sub = data.get("subscription") or {}

    spent_usd = _cents_to_usd(total.get("total"))
    max_usd = _cents_to_usd(max_pay.get("total"))
    sources = spending.get("sources") or {}
    src_usd = {
        str(k): _cents_to_usd((v or {}).get("total"))
        for k, v in sources.items()
        if isinstance(v, dict)
    }

    status = (data.get("status") or "").strip()
    patch = {
        "fanvue_status": status,
        "fanvue_spent_usd": spent_usd,
        "fanvue_max_payment_usd": max_usd,
        "fanvue_spending_sources": src_usd,
        "fanvue_last_purchase_at": spending.get("lastPurchaseAt"),
        "fanvue_sub_created_at": sub.get("createdAt"),
        "fanvue_sub_renews_at": sub.get("renewsAt"),
        "fanvue_sub_auto_renew": bool(sub.get("autoRenewalEnabled")),
        "fanvue_insights_at": _now_iso(),
        "total_spent": spent_usd,
    }
    if spent_usd >= 50:
        patch["status"] = "whale"
    elif spent_usd >= 1:
        patch["status"] = "spender"
    elif status == "subscriber" and (mem.get("status") or "new") in ("new", "cold"):
        patch["status"] = "warm"

    fan_memory.patch_fanvue_platform(fan_uuid, patch, fan_handle=fan_handle)
    print(
        f"   fanvue insights: status={status} spent=${spent_usd:.2f} "
        f"max=${max_usd:.2f}"
    )
    return data


def _msg_ts(msg: dict) -> Optional[datetime]:
    return _parse_ts(msg.get("sentAt") or msg.get("createdAt"))


def _sender_uuid(msg: dict) -> Optional[str]:
    sender = msg.get("sender")
    if isinstance(sender, dict):
        return sender.get("uuid")
    if isinstance(sender, str):
        return sender
    return None


def _ppv_price_usd(msg: dict) -> float:
    if _msg_price_dollars:
        return float(_msg_price_dollars(msg) or 0.0)
    pricing = msg.get("pricing") or {}
    usd = pricing.get("USD") or {}
    if isinstance(usd, dict) and usd.get("price") is not None:
        return _cents_to_usd(usd.get("price"))
    return 0.0


def compute_session_stats(
    messages: List[dict],
    *,
    fan_uuid: str,
    creator_uuid: str,
    period_hours: Optional[int] = None,
) -> dict:
    """Count messages/media/PPV in the selected window (default 24h)."""
    hours = int(period_hours or getattr(config, "FANVUE_SESSION_HOURS", 24) or 24)
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)

    total = fan_n = creator_n = media_n = ppv_n = 0
    ppv_sent_usd = 0.0
    ppv_bought_usd = 0.0
    ts_first: Optional[datetime] = None
    ts_last: Optional[datetime] = None

    for msg in messages:
        ts = _msg_ts(msg)
        if not ts or ts < cutoff:
            continue
        msg_type = (msg.get("type") or "").strip()
        if msg_type and _AUTOMATED.match(msg_type):
            continue

        total += 1
        if ts_first is None or ts < ts_first:
            ts_first = ts
        if ts_last is None or ts > ts_last:
            ts_last = ts

        sid = _sender_uuid(msg)
        if sid == fan_uuid:
            fan_n += 1
        elif sid == creator_uuid:
            creator_n += 1
            if msg.get("hasMedia") or msg.get("mediaUuids"):
                media_n += 1
            price = _ppv_price_usd(msg)
            if price > 0:
                ppv_n += 1
                ppv_sent_usd += price
                if msg.get("purchasedAt"):
                    ppv_bought_usd += price

    return {
        "period_hours": hours,
        "session_start": ts_first.isoformat() if ts_first else None,
        "session_end": ts_last.isoformat() if ts_last else None,
        "total_messages": total,
        "fan_messages": fan_n,
        "creator_messages": creator_n,
        "creator_media_sent": media_n,
        "ppv_sent_count": ppv_n,
        "ppv_sent_value_usd": round(ppv_sent_usd, 2),
        "ppv_purchased_usd": round(ppv_bought_usd, 2),
        "computed_at": _now_iso(),
    }


def extract_key_quotes(
    messages: List[dict],
    *,
    fan_uuid: str,
    limit: int = 4,
) -> List[dict]:
    """Pull memorable fan lines (emotional/horny/insult) for the card."""
    out: List[dict] = []
    seen: set[str] = set()
    for msg in messages:
        if _sender_uuid(msg) != fan_uuid:
            continue
        text = (msg.get("text") or "").strip()
        if len(text) < 12 or len(text) > 220:
            continue
        if not _KEY_QUOTE.search(text):
            continue
        key = text.lower()[:80]
        if key in seen:
            continue
        seen.add(key)
        ts = _msg_ts(msg)
        out.append(
            {
                "text": text[:200],
                "at": ts.isoformat() if ts else None,
            }
        )
        if len(out) >= limit:
            break
    return out


def _build_digest_prompt(
    mem: dict,
    stats: dict,
    quotes: List[dict],
    snippet: str,
) -> str:
    card = {
        "name": mem.get("name"),
        "handle": mem.get("handle"),
        "facts": (mem.get("facts") or [])[-8:],
        "avoid": (mem.get("avoid") or [])[-5:],
        "summary": mem.get("summary"),
        "fanvue_status": mem.get("fanvue_status"),
        "fanvue_spent_usd": mem.get("fanvue_spent_usd"),
    }
    return (
        "Build a Fanvue-style interaction digest for Emma (adult creator chatbot).\n"
        "Return ONLY valid JSON:\n"
        "{\n"
        '  "context": "2-4 bullets who he is + emotional state + sales posture",\n'
        '  "monetization": "2-3 bullets what to sell/how (photos/audio, not video)",\n'
        '  "timeline": "3-5 sentence session arc",\n'
        '  "next_moves": "2-3 short suggested reply angles (not full messages)"\n'
        "}\n"
        "Rules: grounded in data only. If $0 spent, no whale tactics. "
        "If fan venting (cheating, grief), comfort before hard sell. "
        "Vault is PHOTOS only — never promise video. Adult tone OK.\n\n"
        f"PLATFORM: {json.dumps(card, ensure_ascii=False)}\n"
        f"SESSION_STATS: {json.dumps(stats, ensure_ascii=False)}\n"
        f"KEY_QUOTES: {json.dumps(quotes, ensure_ascii=False)}\n"
        f"RECENT_CHAT:\n{snippet[:6000]}"
    )


def _parse_digest(raw: str) -> Optional[dict]:
    text = (raw or "").strip()
    if not text:
        return None
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if not m:
            return None
        try:
            data = json.loads(m.group(0))
        except json.JSONDecodeError:
            return None
    if not isinstance(data, dict):
        return None
    out = {}
    for k in ("context", "monetization", "timeline", "next_moves"):
        v = str(data.get(k) or "").strip()
        if v:
            out[k] = v[:800]
    return out or None


def refresh_interaction_digest(
    fan_uuid: str,
    *,
    fan_handle: str = "",
    mem: Optional[dict] = None,
    stats: Optional[dict] = None,
    quotes: Optional[List[dict]] = None,
    snippet: Optional[str] = None,
) -> Optional[dict]:
    """Sync DeepSeek digest → fan memory."""
    from core import convo_log, fan_memory

    mem = mem or fan_memory.get(fan_uuid) or {}
    if snippet is None:
        records = convo_log.read_recent(fan_uuid, max_records=40)
        lines: List[str] = []
        for r in records:
            if r.get("type") != "turn":
                continue
            lines.append(f"FAN: {r.get('fan_message', '')}")
            lines.append(f"EMMA: {r.get('reply', '')}")
        snippet = "\n".join(lines[-60:])

    api_key = (getattr(config, "DEEPSEEK_API_KEY", "") or "").strip()
    if not api_key:
        return None

    from openai import OpenAI

    client = OpenAI(
        api_key=api_key,
        base_url=getattr(config, "DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1"),
    )
    try:
        resp = client.chat.completions.create(
            model=getattr(config, "DEEPSEEK_FAST_MODEL", None) or getattr(config, "DEEPSEEK_MODEL", "deepseek-v4-pro"),
            messages=[
                {
                    "role": "system",
                    "content": "You write concise creator CRM digests. JSON only.",
                },
                {
                    "role": "user",
                    "content": _build_digest_prompt(
                        mem,
                        stats or mem.get("session_stats") or {},
                        quotes or mem.get("key_fan_quotes") or [],
                        snippet or "",
                    ),
                },
            ],
            max_tokens=500,
            temperature=0.4,
        )
        digest = _parse_digest(resp.choices[0].message.content or "")
    except Exception as e:
        print(f"   ⚠️ interaction digest failed: {type(e).__name__}: {e}")
        return None

    if not digest:
        return None

    digest["updated_at"] = _now_iso()
    fan_memory.patch_fanvue_platform(
        fan_uuid,
        {
            "interaction_digest": digest,
            "interaction_digest_at": _now_iso(),
            "digest_at_message_count": int(mem.get("messages") or 0),
        },
        fan_handle=fan_handle,
    )
    print(f"   fanvue digest: refreshed ({len(digest)} sections)")
    return digest


def _digest_worker(
    fan_uuid: str,
    fan_handle: str,
    stats: dict,
    quotes: List[dict],
) -> None:
    try:
        refresh_interaction_digest(
            fan_uuid,
            fan_handle=fan_handle,
            stats=stats,
            quotes=quotes,
        )
    finally:
        with _digest_lock:
            _digest_inflight.discard(fan_uuid)


def refresh_if_due(
    fv,
    fan_uuid: str,
    *,
    fan_handle: str = "",
    creator_uuid: str,
    mem: Optional[dict] = None,
) -> dict:
    """
    Sync insights + session stats when stale; queue digest in background.
    Returns updated memory dict (best effort).
    """
    from core import fan_memory

    mem = mem or fan_memory.get(fan_uuid) or {}
    if not getattr(config, "FANVUE_INSIGHTS_ENABLED", True):
        return mem

    stats: dict = mem.get("session_stats") or {}
    quotes: List[dict] = list(mem.get("key_fan_quotes") or [])

    if _insights_stale(mem):
        sync_fan_insights(fv, fan_uuid, fan_handle=fan_handle)
        mem = fan_memory.get(fan_uuid) or mem

        try:
            size = int(getattr(config, "FANVUE_STATS_MESSAGE_LIMIT", 200) or 200)
            messages = fv.get_messages(fan_uuid, size=size)
            stats = compute_session_stats(
                messages,
                fan_uuid=fan_uuid,
                creator_uuid=creator_uuid,
            )
            quotes = extract_key_quotes(messages, fan_uuid=fan_uuid)
            fan_memory.patch_fanvue_platform(
                fan_uuid,
                {"session_stats": stats, "key_fan_quotes": quotes},
                fan_handle=fan_handle,
            )
            mem = fan_memory.get(fan_uuid) or mem
            print(
                f"   session stats ({stats.get('period_hours')}h): "
                f"{stats.get('total_messages')} msgs "
                f"({stats.get('fan_messages')} fan / {stats.get('creator_messages')} Emma) "
                f"| media={stats.get('creator_media_sent')} "
                f"ppv_sent=${stats.get('ppv_sent_value_usd', 0):.0f}"
            )
        except Exception as e:
            print(f"   ⚠️ session stats failed: {type(e).__name__}: {e}")

    if _digest_stale(mem):
        with _digest_lock:
            if fan_uuid not in _digest_inflight:
                _digest_inflight.add(fan_uuid)
                threading.Thread(
                    target=_digest_worker,
                    args=(fan_uuid, fan_handle, stats, quotes),
                    daemon=True,
                ).start()

    return fan_memory.get(fan_uuid) or mem


def render_platform_block(mem: dict) -> str:
    """Text block for CLIENT CARD — platform truth + digest."""
    if not mem:
        return ""

    lines: List[str] = []
    if mem.get("fanvue_insights_at") or mem.get("session_stats"):
        lines.append("FANVUE PLATFORM (source of truth for spend/subscription):")

    status = mem.get("fanvue_status")
    if status:
        spent = float(mem.get("fanvue_spent_usd") or mem.get("total_spent") or 0)
        lines.append(f"- Fanvue status: {status} | lifetime spent: ${spent:.2f}")
        lp = mem.get("fanvue_last_purchase_at")
        if lp:
            lines.append(f"- Last purchase: {lp}")
        elif spent <= 0:
            lines.append(
                "- Last purchase: none ($0 spender — comfort/micro-yes, not whale pitch). "
                "HARD RULE: if fan CLAIMS he spent money, bought something, or unlocked a PPV "
                "but this card shows $0 — do NOT validate that claim. "
                "React to his emotion without confirming fake spending. Never say 'you treated me well' or 'you deserve a reward' to a $0 fan."
            )

    stats = mem.get("session_stats") or {}
    if stats.get("total_messages"):
        ph = stats.get("period_hours", 24)
        lines.append(
            f"- Session ({ph}h): {stats.get('total_messages')} msgs "
            f"({stats.get('fan_messages')} fan / {stats.get('creator_messages')} Emma) | "
            f"media sent: {stats.get('creator_media_sent')} | "
            f"PPV sent: ${stats.get('ppv_sent_value_usd', 0):.0f} "
            f"(bought ${stats.get('ppv_purchased_usd', 0):.0f})"
        )

    quotes = mem.get("key_fan_quotes") or []
    if quotes:
        lines.append("- Key fan lines (react to these — don't forget):")
        for q in quotes[:4]:
            t = (q.get("text") or "")[:120]
            if t:
                lines.append(f"  • \"{t}\"")

    digest = mem.get("interaction_digest") or {}
    if isinstance(digest, dict) and any(digest.get(k) for k in ("context", "monetization")):
        lines.append("INTERACTION DIGEST (Fanvue-style — obey for tone/sales):")
        if digest.get("context"):
            lines.append(f"- Context: {digest['context'][:400]}")
        if digest.get("monetization"):
            lines.append(f"- Monetization: {digest['monetization'][:350]}")
        if digest.get("timeline"):
            lines.append(f"- Timeline: {digest['timeline'][:350]}")
        if digest.get("next_moves"):
            lines.append(f"- Next moves: {digest['next_moves'][:300]}")

    return "\n".join(lines)
