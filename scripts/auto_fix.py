"""
Auto-fix runner — lets a Cursor agent repair the bot's own steering code.

Usage:
    python scripts/auto_fix.py                 # show fix queue
    python scripts/auto_fix.py --scan          # aggregate critic errors now
    python scripts/auto_fix.py --run           # fix ONE pending item (supervised)
    python scripts/auto_fix.py --run --max 3   # fix up to 3 items
    python scripts/auto_fix.py --dismiss ID    # drop a proposal

Requires CURSOR_API_KEY (cursor.com/dashboard → Integrations) in env or .env.
After a fix runs, review `git diff` and restart the poller.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from dotenv import load_dotenv

load_dotenv(os.path.join(_ROOT, ".env"))

from core import auto_fix


def _smoke_test() -> bool:
    r = subprocess.run(
        [sys.executable, "-c", "import scripts.poll_inbox"],
        cwd=_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )
    if r.returncode != 0:
        print(f"  ❌ smoke test failed:\n{r.stderr[-800:]}")
        return False
    return True


def _run_fix(item: dict) -> bool:
    api_key = (os.getenv("CURSOR_API_KEY") or "").strip()
    if not api_key:
        print("❌ CURSOR_API_KEY missing. Create one at cursor.com/dashboard → Integrations")
        print("   and add CURSOR_API_KEY=... to fanvue-emma-bot/.env")
        return False

    import tempfile

    runner = os.path.join(_ROOT, "tools", "fixer", "run_fix.mjs")
    if not os.path.exists(runner):
        print(f"❌ runner missing: {runner}")
        return False

    prompt = auto_fix.build_fix_prompt(item)
    print(f"→ [{item['id']}] {item['rule']} x{item['count']} — launching Cursor agent...")
    auto_fix.update_item(item["id"], status="running")

    with tempfile.NamedTemporaryFile(
        "w", suffix=".txt", delete=False, encoding="utf-8"
    ) as f:
        f.write(prompt)
        prompt_file = f.name

    env = dict(os.environ)
    env["CURSOR_API_KEY"] = api_key
    env["FIX_REPO"] = _ROOT
    try:
        proc = subprocess.run(
            ["node", runner, prompt_file],
            cwd=os.path.dirname(runner),
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=1800,  # agents editing code can take a while
        )
    except subprocess.TimeoutExpired:
        print("  ❌ agent timed out (30 min)")
        auto_fix.update_item(item["id"], status="pending")
        return False
    finally:
        try:
            os.unlink(prompt_file)
        except OSError:
            pass

    out = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
    summary = out.strip()[:1500]

    if proc.returncode == 1:
        print(f"  ❌ agent failed to start: {summary[:300]}")
        auto_fix.update_item(item["id"], status="pending")
        return False
    if proc.returncode != 0:
        print(f"  ❌ agent run failed: {summary[:300]}")
        auto_fix.update_item(item["id"], status="failed", result=summary)
        return False

    if not _smoke_test():
        auto_fix.update_item(
            item["id"], status="failed", result="smoke test failed after edit\n" + summary
        )
        print("  ⚠️ Code was modified but imports broke — review `git diff` and fix/revert.")
        return False

    auto_fix.update_item(item["id"], status="done", result=summary)
    print(f"  ✅ fixed. Agent summary:\n{summary[:600]}")
    return True


def _restart_poller() -> None:
    """Kill the running poller and start a fresh one detached."""
    try:
        subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
                "Where-Object { $_.CommandLine -match 'poll_inbox|start_emma' } | "
                "ForEach-Object { Stop-Process -Id $_.ProcessId -Force }",
            ],
            timeout=60,
        )
    except Exception:
        pass
    import time as _t

    _t.sleep(2)
    flags = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    subprocess.Popen(
        [sys.executable, "scripts/start_emma.py"],
        cwd=_ROOT,
        creationflags=flags,
        stdout=open(os.path.join(_ROOT, "logs", "poller.out"), "a", encoding="utf-8"),
        stderr=subprocess.STDOUT,
    )
    print("  🔄 poller restarted")


def _watch(interval_min: int, auto_restart: bool) -> None:
    """Fully autonomous loop: scan → fix (1 per cycle) → optional restart."""
    import time as _t

    print(
        f"👁️ auto-fix watch: every {interval_min} min "
        f"(auto-restart={'on' if auto_restart else 'off'}). Ctrl+C stops."
    )
    while True:
        try:
            new = auto_fix.scan_and_queue()
            if new:
                print(f"\n🧠 {len(new)} new fix proposal(s) queued")
            items = auto_fix.pending()[:1]
            if items and _run_fix(items[0]):
                if auto_restart:
                    _restart_poller()
        except KeyboardInterrupt:
            print("\nStopped.")
            return
        except Exception as e:
            print(f"⚠️ watch error: {e}")
        _t.sleep(max(5, interval_min) * 60)


def main() -> None:
    ap = argparse.ArgumentParser(description="Self-repair via Cursor agent")
    ap.add_argument("--scan", action="store_true", help="aggregate critic errors now")
    ap.add_argument("--run", action="store_true", help="run fixes for pending items")
    ap.add_argument("--max", type=int, default=1, help="max fixes per invocation")
    ap.add_argument("--dismiss", type=str, default=None, help="dismiss item by id")
    ap.add_argument("--watch", action="store_true", help="autonomous scan+fix loop")
    ap.add_argument("--interval", type=int, default=30, help="watch interval minutes")
    ap.add_argument(
        "--auto-restart",
        action="store_true",
        help="restart the poller automatically after a successful fix (watch mode)",
    )
    args = ap.parse_args()

    if args.watch:
        _watch(args.interval, args.auto_restart)
        return

    if args.dismiss:
        auto_fix.update_item(args.dismiss, status="dismissed")
        print(f"🗑️ dismissed {args.dismiss}")
        return

    if args.scan:
        new = auto_fix.scan_and_queue()
        print(f"scan complete — {len(new)} new proposal(s)")

    if args.run:
        items = auto_fix.pending()[: max(1, args.max)]
        if not items:
            print("No pending fixes. (Run --scan first, or the bot queues them itself.)")
            return
        fixed = 0
        for item in items:
            if _run_fix(item):
                fixed += 1
        if fixed:
            print(
                "\n⚠️ Review changes with `git diff`, then restart the poller:\n"
                "   python scripts/start_emma.py"
            )
        return

    items = auto_fix.all_items()
    if not items:
        print("Fix queue empty. The critic queues proposals automatically as errors repeat.")
        return
    print(f"FIX QUEUE ({len(items)}):")
    for i in items:
        print(f"  [{i['id']}] {i['status']:9} {i['rule']} x{i['count']} — {i['created'][:16]}")
        for e in (i.get("examples") or [])[:2]:
            print(f"       · {e[:90]}")
    print("\nRun one fix: python scripts/auto_fix.py --run")


if __name__ == "__main__":
    main()
