"""Quick test: verify OAuth tokens work against Fanvue API."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from api.fanvue_connector import FanvueConnector


def main():
    fv = FanvueConnector()
    me = fv.get_current_user()
    print("✅ Fanvue API connected!")
    print(f"   Creator: @{me.get('handle')} ({me.get('displayName')})")
    print(f"   UUID:    {me.get('uuid')}")


if __name__ == "__main__":
    main()
