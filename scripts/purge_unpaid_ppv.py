"""One-shot: delete every unpaid PPV lock in recent Fanvue chats."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from api.fanvue_connector import FanvueConnector
from api.fanvue_oauth import load_tokens
from core import ppv_expiry


def main() -> int:
    if not load_tokens():
        print("No Fanvue tokens. Run oauth login first.")
        return 1
    fv = FanvueConnector()
    me = fv.get_current_user()
    creator_uuid = me.get("uuid")
    print(f"Purging ALL unpaid locks as @{me.get('handle')}…")
    n = ppv_expiry.purge_all_unpaid(fv, creator_uuid)
    print(f"Done. Deleted {n}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
