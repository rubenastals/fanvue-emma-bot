"""Verify Sophia Cler setup — run locally: python scripts/verify_sophia_setup.py"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

os.environ.setdefault("ACCOUNT_ID", "sophia")
os.environ.setdefault("PERSONA_FILE", "personas/sophia.md")
os.environ.setdefault("FANVUE_MEDIA_MAP", "data/sophia_fanvue_media_map.json")

from dotenv import load_dotenv

load_dotenv(_ROOT / ".env")

OK = "✅"
FAIL = "❌"
WARN = "⚠️ "
errors: list[str] = []
warnings: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    mark = OK if ok else FAIL
    line = f"{mark} {name}"
    if detail:
        line += f" — {detail}"
    print(line)
    if not ok:
        errors.append(name)


def main() -> None:
    print("Sophia Cler setup check\n" + "=" * 40)

    env_path = _ROOT / ".env"
    check(".env exists", env_path.is_file(), str(env_path) if env_path.is_file() else "copy from Emma folder")

    from config import config

    check("FANVUE_CLIENT_ID", bool(config.FANVUE_CLIENT_ID))
    check("FANVUE_CLIENT_SECRET", bool(config.FANVUE_CLIENT_SECRET))

    persona = _ROOT / "personas" / "sophia.md"
    check("personas/sophia.md", persona.is_file())
    text = persona.read_text(encoding="utf-8") if persona.is_file() else ""
    check("Sophia Cler in persona", "Sophia Cler" in text)
    check("English only rule", "ENGLISH ONLY" in text)

    vault = _ROOT / "data" / "sophia_fanvue_media_map.json"
    check("vault map file", vault.is_file())
    if vault.is_file():
        data = json.loads(vault.read_text(encoding="utf-8"))
        n = len(data.get("items") or [])
        print(f"{OK} vault items: {n} (0 = bonding only, OK for launch)")
        if data.get("account_id") != "sophia":
            errors.append("vault account_id")

    start = _ROOT / "scripts" / "start_sophia.py"
    check("start_sophia.py", start.is_file())

    from core.prompt_core import get_active_persona

    p = get_active_persona()
    check("persona loads", "Sophia Cler" in p, f"{len(p)} chars")

    from db import use_postgres, account_id

    aid = account_id()
    check("ACCOUNT_ID", aid == "sophia", f"got {aid!r}")

    if use_postgres():
        print(f"{OK} DATABASE_URL set — tokens per account in Postgres")
        from db import oauth_store

        tok = oauth_store.load_tokens(aid="sophia")
        if tok:
            print(f"{OK} OAuth token for sophia in DB")
            try:
                from api.fanvue_connector import FanvueConnector

                me = FanvueConnector().get_current_user()
                handle = me.get("handle") or me.get("username")
                name = me.get("displayName") or ""
                print(f"{OK} Fanvue API: @{handle} ({name})")
                if "emma" in (str(handle) + name).lower():
                    warnings.append("Connected account looks like Emma — re-OAuth as Sophia")
            except Exception as e:
                errors.append(f"Fanvue API: {e}")
        else:
            print(f"{WARN} No OAuth token for sophia yet — run: python scripts/start_sophia.py")
    else:
        print(f"{WARN} No DATABASE_URL — local file mode (.fanvue_tokens.json)")
        print(f"   For 2 models use Railway DATABASE_URL in .env (same as Emma)")
        tok_file = _ROOT / ".fanvue_tokens.json"
        if tok_file.is_file():
            warnings.append(
                "Single token file — OAuth as Sophia may overwrite Emma unless DATABASE_URL is set"
            )

    print("\n" + "=" * 40)
    for w in warnings:
        print(f"{WARN} {w}")
    if errors:
        print(f"\n{FAIL} {len(errors)} issue(s): {', '.join(errors)}")
        print("\nNext: python scripts/start_sophia.py")
        sys.exit(1)
    if not use_postgres() or not warnings:
        pass
    print(f"\n{OK} Ready — run: python scripts/start_sophia.py")


if __name__ == "__main__":
    main()
