"""
Improve board — automatic learning digest from live chats.

Aggregates DeepSeek critic verdicts + pending lessons + autofix queue into a
ranked Soft/Hard board so the operator does NOT read conversations one by one.

Soft  → lessons / lorebook / tiny autofix (can apply with one command)
Hard  → filled redesign briefs for the specialized agent (human OK before merge)
"""
from __future__ import annotations

import json
import os
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from openai import OpenAI

from config import config
from core import auto_fix, convo_log, lessons

_ROOT = Path(__file__).resolve().parent.parent
_BOARD_JSON = _ROOT / ".improve_board.json"
_BOARD_MD = _ROOT / "docs" / "IMPROVE_BOARD.md"
_BRIEFS_DIR = _ROOT / "docs" / "briefs"
_LOCK = threading.Lock()

_CLIENT: Optional[OpenAI] = None

CLASSIFY_PROMPT = """You triage quality failures for Emma, a Fanvue DM sales chatbot.

From REPEATED critic errors + pending lessons + OPERATOR NOTES (live chats), propose improvements.
Be a tough critic: prioritize honesty (names, delivery), free L0 gifts that actually attach,
no re-sending the same photo, warm-not-dry tone, and no fake bracket "Transmite/You can send" lines.

Return ONLY valid JSON:
{
  "soft": [
    {
      "title": "short",
      "action": "lesson|lorebook|autofix",
      "detail": "concrete change (max 40 words)",
      "priority": 1
    }
  ],
  "hard": [
    {
      "title": "short",
      "problem": "measurable failure from evidence",
      "why_autofix_not_enough": "needs structure/multi-file",
      "design": "what to change",
      "files": ["path.py"],
      "priority": 1
    }
  ]
}

Rules:
- priority 1 = most urgent. Max 5 soft, max 3 hard.
- Soft = proposal for HUMAN review only (lesson/lorebook/tiny policy). Soft NEVER enters the live chat prompt automatically.
- Hard = code/architecture change with file list. Prefer Hard code fixes over Soft prompt rules.
- Prefer Soft ONLY when a one-line behavioral reminder is enough AND it will stay off live until approved.
- Prefer Hard / code when the bug is delivery, memory, name extraction, or API — do NOT add more prompt norms.
- Only propose what the EVIDENCE + OPERATOR NOTES support. No speculative rewrites.
- Empty arrays are fine.
"""


OPERATOR_NOTES = """
OPERATOR NOTES (this week — treat as high-priority critique targets):
1. NAME: Emma invented "Carlos" for a fan named Ruben. Client card must store confirmed names
   (me llamo / mi nombre es). Never save "no soy X" as the name. Never invent first names.
2. TONE: swung from emoji-spam to bone-dry; want warm middle (~half replies with 1 emoji).
3. FREE L0: soft lingerie teases are FREE warm-up gifts. Must actually attach the image with the
   first bubble — never text-only promises, never "[You can send him the free tease…]" / "[Transmite…]".
   PPV cooloff must NOT block an explicit "foto gratis" / "no ha llegado mi foto gratis".
4. NO REPEAT: once a media_uuid is sent to a fan (synced from Fanvue history + ficha sent_content),
   never send that same photo again. Next free = next unused L0 only.
5. CONTEXT: chat window widened to ~100 msgs / 72h so she stops contradicting recent history.
6. Already shipped fixes: name regex, force free on ask/missing, attach-with-bubble, strip stage dirs,
   sent_content on client card, history sync. Critique what STILL fails in evidence, not what is fixed.
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _client() -> OpenAI:
    global _CLIENT
    if _CLIENT is None:
        _CLIENT = OpenAI(
            api_key=config.DEEPSEEK_API_KEY,
            base_url=config.DEEPSEEK_BASE_URL,
        )
    return _CLIENT


def _critic_stats() -> Dict[str, List[str]]:
    """rule -> distinct error descriptions (severity >= 2)."""
    stats: Dict[str, List[str]] = {}
    for fan_uuid in convo_log.all_fan_uuids():
        for rec in convo_log.read_recent(fan_uuid, max_records=40):
            if rec.get("type") != "critic":
                continue
            for err in rec.get("errors") or []:
                if int(err.get("severity") or 1) < 2:
                    continue
                rule = (err.get("rule") or "OTHER").upper()
                what = (err.get("what") or "").strip()
                stats.setdefault(rule, [])
                if what and what not in stats[rule]:
                    stats[rule].append(what)
    return stats


def _evidence_blob(stats: Dict[str, List[str]], pending_lessons: List[dict], fix_items: List[dict]) -> str:
    lines = [OPERATOR_NOTES.strip(), "", "CRITIC ERRORS (repeated across live chats):"]
    if not stats:
        lines.append("- (none notable yet)")
    for rule, examples in sorted(stats.items(), key=lambda kv: -len(kv[1])):
        lines.append(f"- {rule} x{len(examples)}")
        for e in examples[:4]:
            lines.append(f"  · {e}")
    lines.append("\nPENDING GLOBAL LESSONS:")
    if not pending_lessons:
        lines.append("- (none)")
    for i, l in enumerate(pending_lessons[:15]):
        src = l.get("source_fan") or "?"
        lines.append(f"- [{i}] @{src}: {l.get('text')}")
    lines.append("\nAUTOFIX QUEUE (pending):")
    pend = [i for i in fix_items if i.get("status") == "pending"]
    if not pend:
        lines.append("- (none)")
    for i in pend[:10]:
        lines.append(f"- [{i.get('id')}] {i.get('rule')} x{i.get('count')}")
        for e in (i.get("examples") or [])[:2]:
            lines.append(f"  · {e}")
    return "\n".join(lines)


def _parse_json(raw: str) -> Optional[dict]:
    text = (raw or "").strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if not m:
            return None
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            return None


def classify_with_deepseek(evidence: str) -> Dict[str, List[dict]]:
    """Ask DeepSeek to turn evidence into Soft/Hard proposals."""
    empty: Dict[str, List[dict]] = {"soft": [], "hard": []}
    if not (config.DEEPSEEK_API_KEY or "").strip():
        return empty
    kwargs = dict(
        model=config.DEEPSEEK_MODEL,
        messages=[
            {"role": "system", "content": CLASSIFY_PROMPT},
            {"role": "user", "content": evidence[:12000]},
        ],
        temperature=0.2,
        max_tokens=900,
    )
    if getattr(config, "DEEPSEEK_DISABLE_THINKING", False):
        kwargs["extra_body"] = {"thinking": {"type": "disabled"}}
    try:
        resp = _client().chat.completions.create(**kwargs)
        raw = (resp.choices[0].message.content or "").strip()
    except Exception:
        return empty
    data = _parse_json(raw)
    if not isinstance(data, dict):
        return empty
    soft = data.get("soft") if isinstance(data.get("soft"), list) else []
    hard = data.get("hard") if isinstance(data.get("hard"), list) else []
    return {
        "soft": [x for x in soft if isinstance(x, dict)][:5],
        "hard": [x for x in hard if isinstance(x, dict)][:3],
    }


def build_board(*, ask_deepseek: bool = True) -> dict:
    """Scan autofix queue + assemble board. Optionally classify via DeepSeek."""
    new_fixes = auto_fix.scan_and_queue()
    stats = _critic_stats()
    pending_lessons = lessons.pending()
    fix_items = auto_fix.all_items()
    evidence = _evidence_blob(stats, pending_lessons, fix_items)
    proposals = (
        classify_with_deepseek(evidence)
        if ask_deepseek
        else {"soft": [], "hard": []}
    )
    try:
        from core import prompt_audit

        for p in proposals.get("soft") or []:
            prompt_audit.log_change(
                source="deepseek_improve",
                action="soft_proposal",
                detail=f"{p.get('title')}: {p.get('detail')}",
                enters_live_prompt=False,
                meta={"priority": p.get("priority"), "kind": "soft"},
            )
        for p in proposals.get("hard") or []:
            prompt_audit.log_change(
                source="deepseek_improve",
                action="hard_proposal",
                detail=f"{p.get('title')}: {p.get('problem')}",
                files=list(p.get("files") or []),
                enters_live_prompt=False,
                meta={"priority": p.get("priority"), "kind": "hard"},
            )
    except Exception:
        pass
    board = {
        "generated_at": _now(),
        "new_autofix_queued": len(new_fixes),
        "critic_rules": {k: len(v) for k, v in stats.items()},
        "pending_lessons": pending_lessons,
        "autofix_pending": [i for i in fix_items if i.get("status") == "pending"],
        "proposals": proposals,
        "evidence_preview": evidence[:4000],
    }
    return board


def save_board(board: dict) -> Path:
    with _LOCK:
        _BOARD_JSON.write_text(
            json.dumps(board, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        _BOARD_MD.parent.mkdir(parents=True, exist_ok=True)
        _BOARD_MD.write_text(render_markdown(board), encoding="utf-8")
    return _BOARD_MD


def load_board() -> Optional[dict]:
    if not _BOARD_JSON.exists():
        return None
    try:
        return json.loads(_BOARD_JSON.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def render_markdown(board: dict) -> str:
    lines = [
        "# Improve board (auto — live chats)",
        "",
        f"Generated: `{board.get('generated_at')}`",
        "",
        "You do **not** need to read conversations one by one. DeepSeek critic + this board summarize failures.",
        "",
        "## Critic rules (notable)",
        "",
    ]
    rules = board.get("critic_rules") or {}
    if not rules:
        lines.append("_No repeated severity≥2 errors yet._")
    else:
        for rule, n in sorted(rules.items(), key=lambda kv: -kv[1]):
            lines.append(f"- **{rule}**: {n} distinct examples")
    lines += ["", "## Soft proposals (apply with one command)", ""]
    soft = (board.get("proposals") or {}).get("soft") or []
    if not soft:
        lines.append("_None this cycle._")
    else:
        for i, p in enumerate(soft):
            lines.append(
                f"{i}. **{p.get('title')}** `[{p.get('action')}]` p{p.get('priority')}: "
                f"{p.get('detail')}"
            )
    lines += ["", "## Hard proposals (need redesign agent + your OK)", ""]
    hard = (board.get("proposals") or {}).get("hard") or []
    if not hard:
        lines.append("_None this cycle._")
    else:
        for i, p in enumerate(hard):
            lines.append(f"### H{i}: {p.get('title')} (p{p.get('priority')})")
            lines.append(f"- Problem: {p.get('problem')}")
            lines.append(f"- Why not autofix: {p.get('why_autofix_not_enough')}")
            lines.append(f"- Design: {p.get('design')}")
            files = p.get("files") or []
            if files:
                lines.append(f"- Files: {', '.join(files)}")
            lines.append("")
    lines += [
        "## Pending lessons (prompt injections)",
        "",
    ]
    for i, l in enumerate(board.get("pending_lessons") or []):
        src = l.get("source_fan") or "?"
        lines.append(f"- [{i}] @{src}: {l.get('text')}")
    if not board.get("pending_lessons"):
        lines.append("_None._")
    lines += [
        "",
        "## Autofix queue pending",
        "",
    ]
    for i in board.get("autofix_pending") or []:
        lines.append(f"- `{i.get('id')}` {i.get('rule')} x{i.get('count')}")
    if not board.get("autofix_pending"):
        lines.append("_None._")
    lines += [
        "",
        "## Commands",
        "",
        "```bash",
        "python scripts/improve_once.py              # refresh board",
        "python scripts/improve_once.py --apply-soft # approve safe lessons + Cursor soft fixes",
        "python scripts/improve_once.py --write-briefs",
        "```",
        "",
    ]
    return "\n".join(lines)


def write_hard_briefs(board: Optional[dict] = None) -> List[Path]:
    """Write filled redesign briefs for Hard proposals (ready to paste / agent)."""
    board = board or load_board() or build_board(ask_deepseek=True)
    hard = (board.get("proposals") or {}).get("hard") or []
    _BRIEFS_DIR.mkdir(parents=True, exist_ok=True)
    paths: List[Path] = []
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M")
    for i, p in enumerate(hard):
        title = re.sub(r"[^a-zA-Z0-9_-]+", "_", (p.get("title") or f"hard_{i}"))[:40]
        path = _BRIEFS_DIR / f"{stamp}_H{i}_{title}.md"
        body = f"""# Redesign brief (auto-generated from live chats)

Paste this into a Cursor chat with the redesign agent. Review, then say merge/deploy if OK.

### 1. Problema medible
{p.get('problem') or p.get('title')}

### 2. Por qué auto-fix no basta
{p.get('why_autofix_not_enough') or 'Needs multi-file / structural change.'}

### 3. Diseño propuesto
- Soft or Hard: **Hard**
- Design: {p.get('design')}
- Files to touch: {', '.join(p.get('files') or []) or '(agent decides)'}

### 4. Qué NO cambia
OAuth, tokens, .env, vault prices, secrets. No drive-by refactors.

### 5. Criterio de éxito + verificación
- Success: the repeated critic pattern for this issue stops appearing on the improve board.
- Verify: `python -c "import scripts.poll_inbox"` + watch Railway logs / next improve_once digest.

### 6. Rollback
`git revert` the merge commit / redeploy previous Railway image.

---
You are the Emma Fanvue redesign agent. Follow docs/REDESIGN_BRIEF.md.
Soft first if possible. Branch only. NEVER push main / railway up unless human asks.
"""
        path.write_text(body, encoding="utf-8")
        paths.append(path)
    return paths


def approve_all_pending_lessons(*, max_n: int = 40) -> List[str]:
    """Bulk-activate pending global lessons (Soft path)."""
    return lessons.auto_approve_pending(max_n=max_n)


def run_soft_autopilot(*, ask_deepseek: bool = True) -> dict:
    """
    Full Soft loop used by the poller:
      promote misplaced fan lessons → board → ingest Soft lesson proposals
      → auto-approve all global pending → journal → maybe daily digest
    Hard proposals are written as briefs but NEVER auto-merged.
    """
    from core import daily_digest

    auto_on = os.getenv("AUTO_APPROVE_SOFT_LESSONS", "1") == "1"
    moved, kept = lessons.promote_misplaced_fan_lessons()
    if moved:
        daily_digest.log_event(
            "soft_promote",
            f"Moved {moved} behavioral fan-lessons → global (kept {kept} personal)",
            moved=moved,
            kept=kept,
        )

    board = build_board(ask_deepseek=ask_deepseek)
    save_board(board)

    # Turn DeepSeek Soft "lesson" proposals into pending globals (then approve)
    for p in (board.get("proposals") or {}).get("soft") or []:
        action = (p.get("action") or "lesson").lower()
        detail = (p.get("detail") or p.get("title") or "").strip()
        if action in ("lesson", "lorebook") and detail:
            if lessons.propose_global_lesson(detail, source_fan="improve_board"):
                daily_digest.log_event(
                    "soft_proposal",
                    detail,
                    title=p.get("title"),
                    action=action,
                )

    for p in (board.get("proposals") or {}).get("hard") or []:
        title = (p.get("title") or p.get("problem") or "").strip()
        if title:
            daily_digest.log_event("hard_proposal", title)

    rules = board.get("critic_rules") or {}
    if rules:
        daily_digest.log_event(
            "critic_rules",
            ", ".join(f"{k}:{v}" for k, v in sorted(rules.items())),
        )

    activated: List[str] = []
    if auto_on:
        activated = lessons.auto_approve_pending(max_n=40)
        for t in activated:
            daily_digest.log_event("soft_approve", t)

    briefs: List[Path] = []
    if (board.get("proposals") or {}).get("hard"):
        briefs = write_hard_briefs(board)

    daily_digest.maybe_send_daily_digest(critic_rules=rules)

    return {
        "moved": moved,
        "kept": kept,
        "activated": activated,
        "soft_n": len((board.get("proposals") or {}).get("soft") or []),
        "hard_n": len((board.get("proposals") or {}).get("hard") or []),
        "briefs": [str(p) for p in briefs],
        "auto_on": auto_on,
        "critic_rules": rules,
    }
