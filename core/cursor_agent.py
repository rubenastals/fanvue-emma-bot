"""
Launch Cursor agents (SDK via Node) for offline repair / hour review.

Cloud agents edit the GitHub repo (durable). Local agents edit cwd (dev only).
Requires CURSOR_API_KEY + Node + tools/fixer dependencies.
"""
from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path
from typing import Optional, Tuple

_ROOT = Path(__file__).resolve().parent.parent
_FIXER_DIR = _ROOT / "tools" / "fixer"
_RUN_FIX = _FIXER_DIR / "run_fix.mjs"
_RUN_HOUR = _FIXER_DIR / "run_hour_review.mjs"


def cursor_api_key() -> str:
    return (os.getenv("CURSOR_API_KEY") or "").strip()


def node_available() -> bool:
    try:
        r = subprocess.run(
            ["node", "-v"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return r.returncode == 0
    except Exception:
        return False


def launch_agent(
    prompt: str,
    *,
    runner: Path,
    timeout_sec: int = 1800,
    env_extra: Optional[dict] = None,
) -> Tuple[int, str]:
    """
    Run tools/fixer/*.mjs with prompt file. Returns (returncode, combined output).
    """
    api_key = cursor_api_key()
    if not api_key:
        return 1, "STARTUP_ERROR:CURSOR_API_KEY not set"
    if not runner.is_file():
        return 1, f"STARTUP_ERROR:missing runner {runner}"
    if not node_available():
        return 1, "STARTUP_ERROR:node not available"

    with tempfile.NamedTemporaryFile(
        "w", suffix=".txt", delete=False, encoding="utf-8"
    ) as f:
        f.write(prompt)
        prompt_file = f.name

    env = dict(os.environ)
    env["CURSOR_API_KEY"] = api_key
    env["FIX_REPO"] = str(_ROOT)
    if env_extra:
        env.update({k: str(v) for k, v in env_extra.items() if v is not None})

    try:
        proc = subprocess.run(
            ["node", str(runner), prompt_file],
            cwd=str(_FIXER_DIR),
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_sec,
        )
    except subprocess.TimeoutExpired:
        return 1, f"agent timed out ({timeout_sec}s)"
    finally:
        try:
            os.unlink(prompt_file)
        except OSError:
            pass

    out = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
    return int(proc.returncode), out.strip()


def launch_local_fix(prompt: str, *, timeout_sec: int = 1800) -> Tuple[int, str]:
    """Existing autofix path — local agent edits FIX_REPO cwd."""
    return launch_agent(prompt, runner=_RUN_FIX, timeout_sec=timeout_sec)


def launch_cloud_hour_review(
    prompt: str,
    *,
    timeout_sec: int = 2400,
) -> Tuple[int, str]:
    """Hourly review — cloud agent on GitHub repo (survives Railway redeploys)."""
    return launch_agent(
        prompt,
        runner=_RUN_HOUR,
        timeout_sec=timeout_sec,
        env_extra={
            "HOUR_REVIEW_REPO_URL": os.getenv(
                "HOUR_REVIEW_REPO_URL",
                "https://github.com/rubenastals/fanvue-emma-bot",
            ),
            "HOUR_REVIEW_REF": os.getenv("HOUR_REVIEW_REF", "main"),
            "HOUR_REVIEW_AUTO_PR": os.getenv("HOUR_REVIEW_AUTO_PR", "1"),
            "HOUR_REVIEW_MODEL": os.getenv("HOUR_REVIEW_MODEL", "composer-2.5"),
        },
    )
