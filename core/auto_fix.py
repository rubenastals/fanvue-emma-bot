"""
Auto-fix pipeline — closes the learning loop at the CODE level.

Flow:
  1. critic.py stores per-turn error verdicts in the conversation logs
  2. scan_and_queue() aggregates them; a rule failing repeatedly becomes a
     fix proposal in .fix_queue.json
  3. scripts/auto_fix.py launches a Cursor agent (cursor-sdk) that edits
     THIS repo to fix the root cause, with tight constraints

The queue is deduped and rate-limited so the bot never thrashes its own code.
"""
from __future__ import annotations

import json
import os
import threading
import uuid as uuidlib
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List

from core import convo_log

_ROOT = Path(__file__).resolve().parent.parent
_QUEUE = _ROOT / ".fix_queue.json"
_LOCK = threading.Lock()

RULE_THRESHOLD = int(os.getenv("AUTOFIX_RULE_THRESHOLD", "3"))
SCAN_RECORDS_PER_FAN = 30
COOLDOWN_HOURS = int(os.getenv("AUTOFIX_COOLDOWN_HOURS", "24"))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load() -> dict:
    if not _QUEUE.exists():
        return {"items": []}
    try:
        return json.loads(_QUEUE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"items": []}


def _save(data: dict) -> None:
    tmp = str(_QUEUE) + ".tmp"
    Path(tmp).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, _QUEUE)


def _recent_rule_stats() -> Dict[str, List[str]]:
    """rule -> list of example descriptions from recent critic verdicts."""
    stats: Dict[str, List[str]] = {}
    for fan_uuid in convo_log.all_fan_uuids():
        for rec in convo_log.read_recent(fan_uuid, max_records=SCAN_RECORDS_PER_FAN):
            if rec.get("type") != "critic":
                continue
            for err in rec.get("errors") or []:
                rule = (err.get("rule") or "OTHER").upper()
                what = (err.get("what") or "").strip()
                if int(err.get("severity") or 1) < 2:
                    continue  # only notable+ errors drive code changes
                stats.setdefault(rule, [])
                if what and what not in stats[rule]:
                    stats[rule].append(what)
    return stats


def scan_and_queue() -> List[dict]:
    """Aggregate critic errors; queue new fix proposals. Returns new items."""
    stats = _recent_rule_stats()
    new_items: List[dict] = []
    with _LOCK:
        data = _load()
        items = data["items"]
        now = datetime.now(timezone.utc)
        for rule, examples in stats.items():
            if len(examples) < RULE_THRESHOLD:
                continue
            # cooldown: skip if this rule was queued/fixed recently
            recent = [
                i
                for i in items
                if i["rule"] == rule
                and now - datetime.fromisoformat(i["created"])
                < timedelta(hours=COOLDOWN_HOURS)
            ]
            if recent:
                continue
            item = {
                "id": uuidlib.uuid4().hex[:10],
                "rule": rule,
                "count": len(examples),
                "examples": examples[:6],
                "created": _now(),
                "status": "pending",  # pending | running | done | failed | dismissed
                "agent_id": None,
                "result": None,
            }
            items.append(item)
            new_items.append(item)
        data["items"] = items[-50:]
        _save(data)
    return new_items


def pending() -> List[dict]:
    return [i for i in _load()["items"] if i["status"] == "pending"]


def all_items() -> List[dict]:
    return _load()["items"]


def update_item(item_id: str, **fields: Any) -> None:
    with _LOCK:
        data = _load()
        for i in data["items"]:
            if i["id"] == item_id:
                i.update(fields)
                break
        _save(data)


# Prompt for the Cursor fixer agent — tightly scoped.
FIX_PROMPT_TEMPLATE = """You are maintaining the production Fanvue chatbot at:
{repo}

The bot's self-critic (DeepSeek reviews every conversation) detected a REPEATED quality failure.

RULE VIOLATED: {rule}
OCCURRENCES (distinct): {count}
EXAMPLES FROM REAL CONVERSATIONS:
{examples}

Rule meanings:
- LANGUAGE: replies mixed languages / wrong language vs the fan's / typos
- NICKNAMES: pet-name spam or banned words (caro/papi/nena)
- RHYTHM: repetitive structure (same bubble count/length, emoji spam every line) OR bone-dry zero-emoji cold replies
- SELLING: pitching too early, stacking pressure, inventing content, ignoring rejections
- HUMANITY: sounds like a sales agent, ignores what the fan actually said
- ENGAGEMENT: fan cooling down and the bot doesn't adapt

YOUR TASK: find the ROOT CAUSE in the bot's steering code and make the SMALLEST effective fix.
Likely levers (in priority order):
- core/turn_policy.py       (author_note_for — per-turn behavioral note, decide_turn thresholds)
- core/language.py          (language detection / lock / rewrite instruction)
- core/reply_engine.py      (_sanitize_reply filters, prompt assembly order)
- core/system_prompt.py     (persona rules — edit surgically, do NOT rewrite wholesale)
- core/lorebook.py          (keyword-triggered guidance)
- core/reengagement.py      (nudge/goodmorning triggers)

HARD CONSTRAINTS:
- Minimal diff. No refactors. No new dependencies. Comments in English.
- NEVER touch: .env, .fanvue_tokens.json, logs/, exports/, .fan_memory.json, .lessons.json, .fix_queue.json
- Do not change PPV prices or the vault catalog.
- Preserve existing public function signatures.
- After editing, verify imports still work by running from the repo root:
  python -c "import scripts.poll_inbox"
- Finish with a 3-line summary: root cause, file(s) changed, expected effect.
"""


def build_fix_prompt(item: dict) -> str:
    examples = "\n".join(f"- {e}" for e in item.get("examples") or [])
    return FIX_PROMPT_TEMPLATE.format(
        repo=str(_ROOT),
        rule=item["rule"],
        count=item["count"],
        examples=examples or "- (no verbatim examples captured)",
    )
