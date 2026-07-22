"""
Dead-brain quarantine registry (audit R3).

Live creative path under production defaults (SIMPLE_PROMPT=1, LEAN_CREATIVE=1,
REPLY_V2=0) is ONLY:

  personas/emma.md → prompt_core.get_active_persona()
  + CLIENT CARD + HISTORY + TURN facts (truth_state / LOCK/SELL/…)
  + AUTHOR via reply_engine.generate_emma_reply

Do NOT patch quarantined modules to “fix chat”. Emergency flags:
  SIMPLE_PROMPT=0  → legacy manip + pack inject
  REPLY_V2=1 and SIMPLE=0 → reply_v2 / emma_prompt_v2
  LEAN_CREATIVE=0 → fat EMMA_SYSTEM_PROMPT
"""
from __future__ import annotations

from pathlib import Path
from typing import List, Tuple

_ROOT = Path(__file__).resolve().parents[1]

# Marker every quarantined source file must contain (banner / docstring).
QUARANTINE_MARKER = "QUARANTINED — not the live SIMPLE brain"

# (repo-relative path, short why)
QUARANTINED_SURFACES: List[Tuple[str, str]] = [
    ("core/reply_v2.py", "parallel V2 brain; ignored when SIMPLE_PROMPT=1"),
    ("core/emma_prompt_v2.py", "V2 persona essay; only via reply_v2"),
    ("core/system_prompt.py", "fat EMMA_SYSTEM_PROMPT; only LEAN_CREATIVE=0"),
    ("core/strategy_prompt.py", "STRATEGY_BLOCK essay offline; live uses truth_state()"),
    ("core/manipulation.py", "technique banner; only SIMPLE_PROMPT=0"),
    ("core/phase_analyst.py", "extra analyst call; off unless PHASE_ANALYST + non-SIMPLE"),
    ("core/strategy_orchestrator.py", "Celery legacy pipeline; not poll_inbox"),
]

# Live surfaces agents SHOULD edit for production chat quality
LIVE_CREATIVE_SURFACES: List[str] = [
    "personas/emma.md",
    "core/prompt_core.py",
    "core/prompt_layers.py",
    "core/reply_engine.py",
    "core/reply_assemble.py",
    "core/reply_sanitize.py",
    "core/scheme_guard.py",
    "core/intent_router.py",
    "scripts/poll_inbox.py",
]


def quarantined_paths() -> List[Path]:
    return [_ROOT / rel for rel, _ in QUARANTINED_SURFACES]


def missing_markers() -> List[str]:
    """Return relative paths that lack QUARANTINE_MARKER."""
    bad: List[str] = []
    for rel, _ in QUARANTINED_SURFACES:
        text = (_ROOT / rel).read_text(encoding="utf-8")
        if QUARANTINE_MARKER not in text:
            bad.append(rel)
    return bad
