"""
Audit trail for anything that tries to change Emma's live behavior.

Soft lessons / DeepSeek improve proposals / autofix MUST log here.
They do NOT enter the live chat prompt unless a human explicitly enables
INJECT_LESSONS=1 (discouraged).

Format: append-only JSONL + a short markdown digest for the operator.
"""
from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

_ROOT = Path(__file__).resolve().parent.parent
_JSONL = _ROOT / ".prompt_audit.jsonl"
_MD = _ROOT / "docs" / "PROMPT_AUDIT.md"
_LOCK = threading.Lock()
_MAX_MD_LINES = 200


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def log_change(
    *,
    source: str,
    action: str,
    detail: str,
    files: Optional[List[str]] = None,
    enters_live_prompt: bool = False,
    meta: Optional[Dict[str, Any]] = None,
) -> None:
    """
    Record a behavioral / prompt-adjacent change.

    enters_live_prompt=True only if something was actually injected into chat.
    Soft proposals should almost always be False.
    """
    row = {
        "at": _now(),
        "source": source,
        "action": action,
        "detail": (detail or "").strip()[:500],
        "files": files or [],
        "enters_live_prompt": bool(enters_live_prompt),
        "meta": meta or {},
    }
    with _LOCK:
        with _JSONL.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
        _rewrite_md()


def _rewrite_md() -> None:
    rows: List[dict] = []
    if _JSONL.exists():
        for line in _JSONL.read_text(encoding="utf-8").splitlines()[-80:]:
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    lines = [
        "# Prompt / behavior audit",
        "",
        "Soft / DeepSeek / autofix changes are logged here.",
        "**Live chat prompt = CORE + CLIENT CARD + history + turn context only.**",
        "Soft lessons do **not** enter the live prompt unless `INJECT_LESSONS=1`.",
        "",
        "| when (UTC) | source | action | in live? | detail |",
        "|---|---|---|---|---|",
    ]
    for r in reversed(rows[-60:]):
        live = "YES" if r.get("enters_live_prompt") else "no"
        det = (r.get("detail") or "").replace("|", "/").replace("\n", " ")[:120]
        files = ",".join(r.get("files") or [])
        if files:
            det = f"{det} [{files}]"
        lines.append(
            f"| `{r.get('at','')[:19]}` | {r.get('source')} | {r.get('action')} | {live} | {det} |"
        )
    _MD.parent.mkdir(parents=True, exist_ok=True)
    _MD.write_text("\n".join(lines) + "\n", encoding="utf-8")


def recent(n: int = 20) -> List[dict]:
    if not _JSONL.exists():
        return []
    out: List[dict] = []
    for line in _JSONL.read_text(encoding="utf-8").splitlines()[-n:]:
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out
