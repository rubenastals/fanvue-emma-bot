"""
Deep wipe: delete EVERY unpaid PPV lock found in chat history (no age limit).

Purchased locks cannot be deleted by Fanvue API — those stay.
Run on Railway (has tokens + DB):
  railway run --service poller -- python scripts/purge_unpaid_ppv.py
Or just redeploy poller (purge-on-start uses the same deep path).
"""
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
    print(f"Deep-purging ALL unpaid locks as @{me.get('handle')}…")
    n = ppv_expiry.purge_all_unpaid(fv, creator_uuid, chat_size=50)
    print(f"Done. Deleted {n} unpaid lock(s).")
    print("Note: already-purchased locks cannot be unsent via API.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
