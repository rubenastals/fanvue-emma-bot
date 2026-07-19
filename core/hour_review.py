"""
Hourly DeepSeek review — ONLY turns from the last HOUR_REVIEW_MINUTES.

Analyzes failures (scheme, invent-lock, tone, selling) and queues Soft/Hard
improvements. Does NOT inject Soft lessons into the live chat prompt
(INJECT_LESSONS stays off). Soft proposals stay pending unless
AUTO_APPROVE_SOFT_LESSONS=1.
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from openai import OpenAI

from config import config
from core import convo_log, daily_digest, lessons

_ROOT = Path(__file__).resolve().parent.parent
_LAST_JSON = _ROOT / ".hour_review_last.json"

HOUR_REVIEW_ENABLED = os.getenv("HOUR_REVIEW_ENABLED", "1") == "1"
HOUR_REVIEW_MINUTES = int(os.getenv("HOUR_REVIEW_MINUTES", "60"))
HOUR_REVIEW_MAX_FANS = int(os.getenv("HOUR_REVIEW_MAX_FANS", "12"))
HOUR_REVIEW_MAX_TURNS = int(os.getenv("HOUR_REVIEW_MAX_TURNS", "80"))

_PROMPT = """You are the hourly quality auditor for Emma (Fanvue DM sales bot).
You ONLY see messages from the LAST HOUR. Find real failures and propose fixes.

Return ONLY JSON:
{
  "failures": [
    {"severity": 1-3, "rule": "SCHEME|SELLING|HUMANITY|RHYTHM|DELIVERY|OTHER",
     "what": "concrete failure", "evidence": "short quote"}
  ],
  "soft": [
    {"title": "short", "detail": "one behavioral rule max 40 words", "priority": 1}
  ],
  "hard": [
    {"title": "short", "problem": "...", "files": ["path.py"], "priority": 1}
  ],
  "verdict": "one sentence"
}

Rules:
- Max 6 failures, 4 soft, 2 hard. Empty arrays OK if hour looked clean.
- Soft = pending lesson for human/auto-approve later — NEVER assume it hits live chat.
- Prefer Hard/code when delivery, lock invent, attach, or memory broke.
- Do not invent failures not supported by the hour frame.
"""


def _parse_ts(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except ValueError:
        return None


def _collect_hour_frame(
    *,
    minutes: int,
    max_fans: int,
    max_turns: int,
) -> List[Dict[str, Any]]:
    """Turns (+ scheme hits) from the last `minutes`, newest fans first."""
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=minutes)
    frames: List[Dict[str, Any]] = []
    for fan_uuid in convo_log.all_fan_uuids():
        recs = convo_log.read_recent(fan_uuid, max_records=40)
        turns = []
        handle = ""
        for r in recs:
            if r.get("type") != "turn":
                continue
            ts = _parse_ts(r.get("ts") or r.get("at"))
            if not ts or ts < cutoff:
                continue
            handle = r.get("handle") or handle
            turns.append(r)
        if turns:
            frames.append(
                {
                    "fan_uuid": fan_uuid,
                    "handle": handle or fan_uuid[:8],
                    "turns": turns,
                }
            )
    # Prefer fans with more activity / scheme errors
    def _score(f: dict) -> tuple:
        errs = sum(1 for t in f["turns"] if t.get("scheme_errors"))
        return (errs, len(f["turns"]))

    frames.sort(key=_score, reverse=True)
    frames = frames[:max_fans]
    # Cap total turns in the blob
    total = 0
    trimmed: List[Dict[str, Any]] = []
    for f in frames:
        keep = []
        for t in f["turns"]:
            if total >= max_turns:
                break
            keep.append(t)
            total += 1
        if keep:
            trimmed.append({**f, "turns": keep})
        if total >= max_turns:
            break
    return trimmed


def _format_frame(frames: List[Dict[str, Any]]) -> str:
    lines: List[str] = []
    for f in frames:
        lines.append(f"=== @{f['handle']} ({len(f['turns'])} turns) ===")
        for t in f["turns"]:
            meta = []
            if t.get("pack_id"):
                meta.append(f"pack={t['pack_id']}")
            if t.get("lock_active") is True:
                meta.append("lock=ACTIVE")
            elif t.get("lock_active") is False:
                meta.append("lock=NONE")
            if t.get("offer"):
                meta.append("OFFER")
            if t.get("scheme_errors"):
                meta.append(f"GUARD={t['scheme_errors']}")
            lines.append(f"FAN: {(t.get('fan_message') or '')[:220]}")
            lines.append(
                f"EMMA ({', '.join(meta) or '-'}): {(t.get('reply') or '')[:280]}"
            )
        lines.append("")
    return "\n".join(lines).strip()


def _parse_json(raw: str) -> Optional[dict]:
    if not raw:
        return None
    m = re.search(r"\{[\s\S]*\}", raw.strip())
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def run_hourly_review() -> Dict[str, Any]:
    """
    One DeepSeek pass over last-hour turns. Returns summary dict.
    Soft lessons = pending only (no live inject).
    """
    if not HOUR_REVIEW_ENABLED:
        return {"skipped": True, "reason": "disabled"}
    if not config.DEEPSEEK_API_KEY:
        return {"skipped": True, "reason": "no_api_key"}

    frames = _collect_hour_frame(
        minutes=HOUR_REVIEW_MINUTES,
        max_fans=HOUR_REVIEW_MAX_FANS,
        max_turns=HOUR_REVIEW_MAX_TURNS,
    )
    if not frames:
        print("   hour-review: no turns in the last hour — skip")
        return {"skipped": True, "reason": "no_turns", "fans": 0}

    blob = _format_frame(frames)
    client = OpenAI(
        api_key=config.DEEPSEEK_API_KEY,
        base_url=config.DEEPSEEK_BASE_URL,
    )
    kwargs: Dict[str, Any] = dict(
        model=config.DEEPSEEK_MODEL,
        messages=[
            {"role": "system", "content": _PROMPT},
            {
                "role": "user",
                "content": (
                    f"WINDOW: last {HOUR_REVIEW_MINUTES} minutes only.\n"
                    f"FANS: {len(frames)}\n\n{blob}"
                ),
            },
        ],
        temperature=0.2,
        max_tokens=900,
    )
    if getattr(config, "DEEPSEEK_DISABLE_THINKING", False):
        kwargs["extra_body"] = {"thinking": {"type": "disabled"}}

    try:
        resp = client.chat.completions.create(**kwargs)
        raw = (resp.choices[0].message.content or "").strip()
    except Exception as e:
        print(f"   ⚠️ hour-review DeepSeek failed: {type(e).__name__}: {e}")
        return {"skipped": True, "reason": f"api:{type(e).__name__}"}

    data = _parse_json(raw) or {}
    soft_n = 0
    for p in data.get("soft") or []:
        if not isinstance(p, dict):
            continue
        detail = (p.get("detail") or p.get("title") or "").strip()
        if not detail:
            continue
        if lessons.propose_global_lesson(detail, source_fan="hour_review"):
            soft_n += 1
            daily_digest.log_event(
                "hour_soft",
                detail,
                title=p.get("title"),
            )

    for p in data.get("hard") or []:
        if isinstance(p, dict) and (p.get("title") or p.get("problem")):
            daily_digest.log_event(
                "hour_hard",
                str(p.get("title") or p.get("problem")),
            )

    fail_n = len(data.get("failures") or [])
    out = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "fans": len(frames),
        "turns": sum(len(f["turns"]) for f in frames),
        "failures": fail_n,
        "soft_proposed": soft_n,
        "hard": len(data.get("hard") or []),
        "verdict": (data.get("verdict") or "")[:200],
        "raw": data,
    }
    try:
        _LAST_JSON.write_text(
            json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except OSError:
        pass

    print(
        f"   ⏱ hour-review: fans={out['fans']} turns={out['turns']} "
        f"fails={fail_n} soft_pending+={soft_n} | {out['verdict'][:80]}"
    )
    return out
