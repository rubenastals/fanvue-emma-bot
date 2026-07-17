"""
Improve journal + daily digest.

Tracks Soft auto-approvals and critic signals, then once per Los Angeles day
sends a summary via webhook and/or email (and always prints + writes a file).
"""
from __future__ import annotations

import json
import os
import smtplib
import threading
import urllib.request
from datetime import datetime, timezone
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

_ROOT = Path(__file__).resolve().parent.parent
_JOURNAL = _ROOT / ".improve_journal.json"
_DIGEST_MD = _ROOT / "docs" / "DAILY_DIGEST.md"
_LOCK = threading.Lock()
_LA = ZoneInfo("America/Los_Angeles")


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _la_day(dt: Optional[datetime] = None) -> str:
    d = (dt or _now_utc()).astimezone(_LA)
    return d.strftime("%Y-%m-%d")


def _load() -> dict:
    if not _JOURNAL.exists():
        return {"events": [], "last_digest_day": None}
    try:
        return json.loads(_JOURNAL.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"events": [], "last_digest_day": None}


def _save(data: dict) -> None:
    tmp = str(_JOURNAL) + ".tmp"
    Path(tmp).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, _JOURNAL)


def log_event(kind: str, text: str, **extra: Any) -> None:
    """Append a journal event (Soft approve, critic spike, hard proposal, …)."""
    text = (text or "").strip()
    if not text:
        return
    with _LOCK:
        data = _load()
        ev = {
            "ts": _now_utc().isoformat(),
            "day": _la_day(),
            "kind": kind,
            "text": text[:500],
        }
        ev.update({k: v for k, v in extra.items() if v is not None})
        data["events"] = (data.get("events") or [])[-500:] + [ev]
        _save(data)


def events_for_day(day: Optional[str] = None) -> List[dict]:
    day = day or _la_day()
    with _LOCK:
        data = _load()
    return [e for e in (data.get("events") or []) if e.get("day") == day]


def build_digest_text(*, day: Optional[str] = None, critic_rules: Optional[dict] = None) -> str:
    day = day or _la_day()
    events = events_for_day(day)
    soft = [e for e in events if e.get("kind") in ("soft_approve", "soft_promote", "soft_proposal")]
    hard = [e for e in events if e.get("kind") == "hard_proposal"]
    errors = [e for e in events if e.get("kind") == "critic_rules"]
    lines = [
        f"Emma daily digest — {day} (Los Angeles)",
        "",
        f"Soft changes applied: {len(soft)}",
    ]
    if soft:
        for e in soft[-20:]:
            lines.append(f"  • [{e.get('kind')}] {e.get('text')}")
    else:
        lines.append("  • (none)")
    lines += ["", f"Hard proposals (need review): {len(hard)}"]
    if hard:
        for e in hard[-10:]:
            lines.append(f"  • {e.get('text')}")
    else:
        lines.append("  • (none)")
    lines += ["", "Errors / critic signals:"]
    if critic_rules:
        for rule, n in sorted(critic_rules.items(), key=lambda kv: -kv[1]):
            lines.append(f"  • {rule}: {n} distinct examples")
    elif errors:
        for e in errors[-3:]:
            lines.append(f"  • {e.get('text')}")
    else:
        lines.append("  • (no snapshot this cycle)")
    lines += [
        "",
        "Board: docs/IMPROVE_BOARD.md",
        "Hard briefs: docs/briefs/",
        "Soft lessons auto-approve is ON — behavior stays shared across fans.",
    ]
    return "\n".join(lines)


def _post_webhook(url: str, text: str) -> bool:
    """Discord-compatible JSON content, also works for many Slack incoming webhooks."""
    payload = json.dumps({"content": text[:1900], "text": text[:3000]}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json", "User-Agent": "emma-digest/1"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return 200 <= getattr(resp, "status", 200) < 300
    except Exception:
        return False


def _send_email(to_addr: str, subject: str, body: str) -> bool:
    host = (os.getenv("SMTP_HOST") or "").strip()
    if not host or not to_addr:
        return False
    port = int(os.getenv("SMTP_PORT") or "587")
    user = (os.getenv("SMTP_USER") or "").strip()
    password = (os.getenv("SMTP_PASS") or "").strip()
    from_addr = (os.getenv("SMTP_FROM") or user or "emma-bot@localhost").strip()
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = to_addr
    try:
        with smtplib.SMTP(host, port, timeout=30) as s:
            s.starttls()
            if user and password:
                s.login(user, password)
            s.sendmail(from_addr, [to_addr], msg.as_string())
        return True
    except Exception:
        return False


def send_digest(
    *,
    day: Optional[str] = None,
    critic_rules: Optional[dict] = None,
    force: bool = False,
) -> bool:
    """
    Send once per LA day unless force=True.
    Channels: DIGEST_WEBHOOK_URL and/or DIGEST_EMAIL (+ SMTP_*).
    Always writes docs/DAILY_DIGEST.md and prints to stdout.
    """
    day = day or _la_day()
    with _LOCK:
        data = _load()
        if not force and data.get("last_digest_day") == day:
            return False
        data["last_digest_day"] = day
        _save(data)

    text = build_digest_text(day=day, critic_rules=critic_rules)
    _DIGEST_MD.parent.mkdir(parents=True, exist_ok=True)
    _DIGEST_MD.write_text(text + "\n", encoding="utf-8")
    print("\n" + "=" * 60 + f"\n📧 DAILY DIGEST {day}\n" + text + "\n" + "=" * 60 + "\n", flush=True)

    ok_any = False
    webhook = (os.getenv("DIGEST_WEBHOOK_URL") or "").strip()
    if webhook:
        if _post_webhook(webhook, text):
            print("   digest → webhook OK", flush=True)
            ok_any = True
        else:
            print("   digest → webhook FAILED", flush=True)

    email = (os.getenv("DIGEST_EMAIL") or "").strip()
    if email:
        if _send_email(email, f"Emma digest {day}", text):
            print(f"   digest → email {email} OK", flush=True)
            ok_any = True
        else:
            print("   digest → email FAILED (check SMTP_*)", flush=True)

    if not webhook and not email:
        print(
            "   digest: set DIGEST_WEBHOOK_URL (Discord/Slack) or DIGEST_EMAIL+SMTP_* to receive it outside logs",
            flush=True,
        )
    return True


def maybe_send_daily_digest(critic_rules: Optional[dict] = None) -> bool:
    """
    Send after 09:00 America/Los_Angeles, once per calendar day.
    """
    now = _now_utc().astimezone(_LA)
    if now.hour < 9:
        return False
    return send_digest(critic_rules=critic_rules, force=False)
