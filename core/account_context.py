"""Per-account runtime context (display name, boot guards)."""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

from db import account_id

_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_ACCOUNT = "emma"


def creator_display_name() -> str:
    """First line of persona ('You are Sophia Cler.') or PERSONA_DISPLAY_NAME env."""
    custom = (os.getenv("PERSONA_DISPLAY_NAME") or "").strip()
    if custom:
        return custom
    from core.prompt_core import get_active_persona

    first = (get_active_persona().splitlines() or [""])[0]
    m = re.match(r"You are\s+(.+?)\.\s", first)
    if m:
        return m.group(1).strip()
    return account_id().replace("_", " ").title()


def persona_file_path() -> Path | None:
    path = (os.getenv("PERSONA_FILE") or "").strip()
    if path:
        p = Path(path) if Path(path).is_absolute() else _ROOT / path
        return p if p.is_file() else None
    aid = account_id().lower()
    if aid == _DEFAULT_ACCOUNT:
        return _ROOT / "personas" / "emma.md"
    p = _ROOT / "personas" / f"{aid}.md"
    return p if p.is_file() else None


def validate_account_boot(*, strict: bool = True) -> list[str]:
    """Boot-time checks for multi-account isolation. Returns warnings/errors."""
    issues: list[str] = []
    aid = account_id()

    pf = persona_file_path()
    if aid != _DEFAULT_ACCOUNT and not pf:
        issues.append(f"CRITICAL: missing persona file for account={aid!r}")

    env_map = (os.getenv("FANVUE_MEDIA_MAP") or "").strip()
    if aid != _DEFAULT_ACCOUNT and not env_map:
        issues.append(
            f"CRITICAL: FANVUE_MEDIA_MAP unset for account={aid!r} "
            "(risk loading Emma vault)"
        )
    elif env_map and aid not in Path(env_map).name.lower():
        issues.append(
            f"MEDIUM: FANVUE_MEDIA_MAP={env_map!r} filename may not match account={aid!r}"
        )

    if strict and any(i.startswith("CRITICAL") for i in issues):
        for i in issues:
            print(f"   ❌ {i}")
        sys.exit(1)
    return issues
