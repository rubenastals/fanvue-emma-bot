"""CLI: create poller tables + seed ACCOUNT_ID (default emma)."""
from __future__ import annotations

import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from dotenv import load_dotenv

load_dotenv(os.path.join(_ROOT, ".env"))

from db.schema import init_schema
from db import account_id

if __name__ == "__main__":
    init_schema(seed_account=True)
    print("OK: schema ready, account seeded:", account_id())
