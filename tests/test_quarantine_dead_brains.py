"""R3: quarantined dead brains stay marked and off the SIMPLE live path."""
from __future__ import annotations

import ast
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from config import config
from core import quarantine, strategy_prompt
from core.prompt_core import get_active_persona


def test_quarantine_markers_present():
    missing = quarantine.missing_markers()
    assert not missing, f"missing QUARANTINE_MARKER in: {missing}"


def test_production_flags_keep_dead_brains_off():
    assert config.SIMPLE_PROMPT is True
    assert config.LEAN_CREATIVE is True
    assert config.REPLY_V2 is False
    assert config.INJECT_LESSONS is False
    assert config.PHASE_ANALYST is False


def test_live_persona_is_emma_md_not_fat_system_prompt():
    persona = get_active_persona()
    assert "Emma" in persona or "emma" in persona.lower()
    # Fat quarantined essay must not be the live CORE
    fat = (_ROOT / "core" / "system_prompt.py").read_text(encoding="utf-8")
    assert quarantine.QUARANTINE_MARKER in fat
    # Live persona comes from emma.md loader, not EMMA_SYSTEM_PROMPT constant
    assert "EMMA_SYSTEM_PROMPT" not in persona


def test_strategy_block_not_called_from_reply_engine():
    src = (_ROOT / "core" / "reply_engine.py").read_text(encoding="utf-8")
    # Must not call the offline essay helper; docstring may mention it as quarantined.
    assert "strategy_block(" not in src
    assert "from core.strategy_prompt import" not in src or "truth_state" in src
    # truth_state IS the live path (imported / used)
    assert "truth_state" in src
    ts = strategy_prompt.truth_state(lock_active=False)
    assert "NO lock" in ts or "candado" in ts.lower()
    essay = strategy_prompt.STRATEGY_BLOCK
    assert "offline" in essay.lower()


def test_poll_inbox_does_not_eager_import_reply_v2():
    src = (_ROOT / "scripts" / "poll_inbox.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    top_imports = []
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module == "core.reply_v2":
            top_imports.append(node.lineno)
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "core.reply_v2":
                    top_imports.append(node.lineno)
    assert not top_imports, f"eager reply_v2 import at lines {top_imports}"
    # Emergency path still reachable via lazy import
    assert "from core.reply_v2 import generate_reply_v2" in src


def test_autofix_points_at_live_not_fat_prompt():
    src = (_ROOT / "core" / "auto_fix.py").read_text(encoding="utf-8")
    assert "personas/emma.md" in src
    assert "core/scheme_guard.py" in src
    # Must warn against dead brains, not list system_prompt as a primary lever
    assert "Do NOT edit quarantined dead brains" in src
    assert "core/system_prompt.py     (persona rules" not in src


if __name__ == "__main__":
    test_quarantine_markers_present()
    test_production_flags_keep_dead_brains_off()
    test_live_persona_is_emma_md_not_fat_system_prompt()
    test_strategy_block_not_called_from_reply_engine()
    test_poll_inbox_does_not_eager_import_reply_v2()
    test_autofix_points_at_live_not_fat_prompt()
    print("ok")
