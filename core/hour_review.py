"""
Hourly quality review via Cursor CLOUD agent (not DeepSeek).

Flow:
  1. Collect last-hour turns from convo logs (Python, local to poller)
  2. Build a review brief + fix prompt
  3. Launch Cursor cloud agent on the GitHub repo (durable PR / branch)
  4. Agent fixes clear root causes in code; never auto-merges/deploys

DeepSeek critic was unreliable for this job — Cursor edits the real levers
(persona / WHEN tree / sanitize / router). Soft lessons are NOT the primary
output; code PRs are.

Env:
  HOUR_REVIEW_ENABLED=1
  CURSOR_API_KEY=...
  HOUR_REVIEW_REPO_URL=https://github.com/rubenastals/fanvue-emma-bot
  HOUR_REVIEW_REF=main
  HOUR_REVIEW_AUTO_PR=1
  HOUR_REVIEW_ASYNC=1   (default — do not block the poll loop)
"""
from __future__ import annotations

import json
import os
import re
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from core import daily_digest

_ROOT = Path(__file__).resolve().parent.parent
_LAST_JSON = _ROOT / ".hour_review_last.json"
_BRIEF_MD = _ROOT / "docs" / "briefs" / "hour_review_LATEST.md"
_LOCK = threading.Lock()
_ASYNC_THREAD: Optional[threading.Thread] = None

HOUR_REVIEW_ENABLED = os.getenv("HOUR_REVIEW_ENABLED", "1") == "1"
HOUR_REVIEW_MINUTES = int(os.getenv("HOUR_REVIEW_MINUTES", "60"))
HOUR_REVIEW_MAX_FANS = int(os.getenv("HOUR_REVIEW_MAX_FANS", "12"))
HOUR_REVIEW_MAX_TURNS = int(os.getenv("HOUR_REVIEW_MAX_TURNS", "80"))
HOUR_REVIEW_ASYNC = os.getenv("HOUR_REVIEW_ASYNC", "1") == "1"

HOUR_REVIEW_PROMPT = """You are the hourly quality auditor + fixer for Emma (Fanvue DM sales bot).

You ONLY see messages from the LAST HOUR (attached below). Find REAL failures and
fix the ROOT CAUSE in the bot's steering code with the SMALLEST effective diff.

## What "good" looks like
- Reply answers what the fan JUST asked (relevance).
- SIMPLE_PROMPT playbook moves: BOND / HEAT / ASK PIC / SELL LOCK / HOLD FRAME / SOFT EXIT / REWARD
- "How do you look in the photo?" with unpaid lock → filthy DESCRIBE (SELL LOCK), never discount/soft-exit.
- Filthy girlfriend PPV teases, not store captions. English only when ENGLISH_ONLY=1.
- No guilt / fake emergency / rival FOMO after purchase.

## Your task
1. List concrete failures from the hour frame (max 8). Skip inventing issues.
2. For clear structural bugs (wrong WHEN, bad regex, sanitize miss, relevance),
   edit code NOW on a feature branch.
3. If autoCreatePR is on, leave a clear PR description of root cause + files.
4. Do NOT auto-merge. Do NOT deploy Railway. Do NOT touch secrets/.env/tokens.
5. Prefer code/WHEN/sanitize over Soft lessons. Soft lessons do NOT hit live
   prompt when INJECT_LESSONS=0.

## Live levers (priority)
- core/technique_playbook.py / core/technique_policy.py  (WHEN tree)
- core/reply_assemble.py / core/reply_sanitize.py
- core/intent_router.py / core/offer_selector.py / core/turn_policy.py
- personas/emma.md  (short rules only — do not append forever)
- core/scheme_guard.py
- scripts/poll_inbox.py  (hard gates only when needed)

## Hard bans for this agent
- No refactor drive-bys. No new dependencies.
- Never edit: .env, tokens, vault prices, .fix_queue.json, fan memory dumps.
- Quarantined dead brains (do not edit for live): system_prompt.py, reply_v2.py,
  emma_prompt_v2.py, phase_analyst.py, fat manipulation banners.

## Hour frame
WINDOW: last {minutes} minutes | FANS: {fans} | TURNS: {turns}

{blob}

## Finish
End with a short summary:
- failures found (bullets)
- files changed (or "none — hour clean")
- PR link if created
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
    from core import convo_log

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
            # Skip offline-sim junk in the review feed
            if str(handle).lower().startswith("sim_"):
                continue
            turns.append(r)
        if turns:
            frames.append(
                {
                    "fan_uuid": fan_uuid,
                    "handle": handle or fan_uuid[:8],
                    "turns": turns,
                }
            )

    def _score(f: dict) -> tuple:
        errs = sum(1 for t in f["turns"] if t.get("scheme_errors"))
        return (errs, len(f["turns"]))

    frames.sort(key=_score, reverse=True)
    frames = frames[:max_fans]
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
            if t.get("technique"):
                meta.append(f"tech={t['technique']}")
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


def build_hour_prompt(frames: List[Dict[str, Any]]) -> str:
    blob = _format_frame(frames)
    turns = sum(len(f["turns"]) for f in frames)
    return HOUR_REVIEW_PROMPT.format(
        minutes=HOUR_REVIEW_MINUTES,
        fans=len(frames),
        turns=turns,
        blob=blob or "(empty)",
    )


def _write_brief(prompt: str, frames: List[Dict[str, Any]]) -> None:
    _BRIEF_MD.parent.mkdir(parents=True, exist_ok=True)
    body = (
        f"# Hour review brief (Cursor cloud)\n\n"
        f"Generated: {datetime.now(timezone.utc).isoformat()}\n"
        f"Fans: {len(frames)} | Turns: {sum(len(f['turns']) for f in frames)}\n\n"
        f"This file is the payload for the Cursor hour-review agent "
        f"(DeepSeek critic is NOT used).\n\n---\n\n{prompt}\n"
    )
    try:
        _BRIEF_MD.write_text(body, encoding="utf-8")
    except OSError:
        pass


def run_hourly_review() -> Dict[str, Any]:
    """
    Collect last-hour turns and launch a Cursor CLOUD agent.
    Synchronous — prefer run_hourly_review_async() from the poller.
    """
    if not HOUR_REVIEW_ENABLED:
        return {"skipped": True, "reason": "disabled"}

    from core import cursor_agent

    if not cursor_agent.cursor_api_key():
        print("   ⚠️ hour-review: CURSOR_API_KEY missing — write brief only")
        frames = _collect_hour_frame(
            minutes=HOUR_REVIEW_MINUTES,
            max_fans=HOUR_REVIEW_MAX_FANS,
            max_turns=HOUR_REVIEW_MAX_TURNS,
        )
        if frames:
            _write_brief(build_hour_prompt(frames), frames)
        return {"skipped": True, "reason": "no_cursor_api_key", "fans": len(frames) if frames else 0}

    frames = _collect_hour_frame(
        minutes=HOUR_REVIEW_MINUTES,
        max_fans=HOUR_REVIEW_MAX_FANS,
        max_turns=HOUR_REVIEW_MAX_TURNS,
    )
    if not frames:
        print("   hour-review: no turns in the last hour — skip")
        return {"skipped": True, "reason": "no_turns", "fans": 0}

    prompt = build_hour_prompt(frames)
    _write_brief(prompt, frames)
    turns_n = sum(len(f["turns"]) for f in frames)
    print(
        f"   ⏱ hour-review: launching Cursor CLOUD agent "
        f"(fans={len(frames)} turns={turns_n})…"
    )

    code, out = cursor_agent.launch_cloud_hour_review(prompt)
    agent_id = ""
    m = re.search(r"AGENT_ID:(\S+)", out or "")
    if m:
        agent_id = m.group(1)

    ok = code == 0
    out_summary = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "engine": "cursor_cloud",
        "fans": len(frames),
        "turns": turns_n,
        "ok": ok,
        "returncode": code,
        "agent_id": agent_id,
        "verdict": (out or "")[:400],
        "brief": str(_BRIEF_MD),
    }
    try:
        _LAST_JSON.write_text(
            json.dumps(out_summary, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except OSError:
        pass

    try:
        daily_digest.log_event(
            "hour_review_cursor",
            f"ok={ok} fans={len(frames)} agent={agent_id or '-'}",
            ok=ok,
            agent_id=agent_id,
        )
    except Exception:
        pass

    if ok:
        print(
            f"   ⏱ hour-review Cursor DONE agent={agent_id or '?'} "
            f"| {(out or '')[:120]}"
        )
    else:
        print(
            f"   ⚠️ hour-review Cursor failed rc={code}: {(out or '')[:240]}"
        )
    return out_summary


def run_hourly_review_async() -> Dict[str, Any]:
    """
    Non-blocking wrapper for the poll loop. Skips if a review is already running.
    """
    global _ASYNC_THREAD
    if not HOUR_REVIEW_ENABLED:
        return {"skipped": True, "reason": "disabled"}
    if not HOUR_REVIEW_ASYNC:
        return run_hourly_review()

    with _LOCK:
        if _ASYNC_THREAD is not None and _ASYNC_THREAD.is_alive():
            print("   hour-review: previous Cursor agent still running — skip")
            return {"skipped": True, "reason": "already_running"}

        def _job() -> None:
            try:
                run_hourly_review()
            except Exception as exc:
                print(f"   ⚠️ hour-review async crash: {type(exc).__name__}: {exc}")

        _ASYNC_THREAD = threading.Thread(
            target=_job, daemon=True, name="hour-review-cursor"
        )
        _ASYNC_THREAD.start()
    return {"started": True, "async": True}
