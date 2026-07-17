"""Emergency quality reset: wipe Soft lesson flood + fix corrupt fan names."""
from __future__ import annotations

import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from dotenv import load_dotenv

load_dotenv(os.path.join(_ROOT, ".env"))

from core import fan_memory, lessons


def main() -> None:
    n = lessons.clear_all_active()
    print(f"Cleared {n} active Soft global lessons")

    # Fix known corrupt cards (name "Un" from soy-un… regex poison)
    fixed = 0
    from db import fan_memory_store

    # Prefer scanning via store if available; else known fan from this chat
    known = [
        ("abe29501-7bef-4486-831d-a6ed0a3a56a8", "Ruben", "patient-guineafowl-495"),
    ]
    for fid, name, handle in known:
        mem = fan_memory.get(fid) or {}
        before = mem.get("name")
        fan_memory._set_confirmed_name(mem, name)  # noqa: SLF001
        mem["handle"] = handle or mem.get("handle")
        fan_memory_store.set_fan(fid, mem)
        print(f"  card @{handle}: name {before!r} → {mem.get('name')!r} (confirmed)")
        fixed += 1
    print(f"Fixed {fixed} client card(s)")


if __name__ == "__main__":
    main()
