"""
Standalone DeepSeek smoke test.

Verifies that the DEEPSEEK_API_KEY works and that Emma generates a reply,
WITHOUT needing Postgres, Redis or Fanvue. It reuses the real system prompt
and the same generation parameters as the pipeline.

Usage:
    python scripts/test_deepseek.py
    python scripts/test_deepseek.py "hola guapa, que haces?"
"""
import os
import sys

# Windows consoles default to cp1252 and choke on emojis; force UTF-8 output.
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

# Make the project root importable when run as `python scripts/test_deepseek.py`
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from config import config
from core.reply_engine import generate_emma_reply


def main():
    fan_message = sys.argv[1] if len(sys.argv) > 1 else "hola guapa, que haces?"

    if not config.DEEPSEEK_API_KEY or config.DEEPSEEK_API_KEY.startswith("sk-xxxx"):
        print("❌ DEEPSEEK_API_KEY is missing or still a placeholder in .env")
        sys.exit(1)

    print(f"→ Fan: {fan_message}")
    print(f"→ Model: {config.DEEPSEEK_MODEL} @ {config.DEEPSEEK_BASE_URL}\n")

    try:
        reply, decision = generate_emma_reply(fan_message)
    except Exception as e:
        print(f"❌ DeepSeek call failed: {type(e).__name__}: {e}")
        sys.exit(1)

    from core.reply_engine import split_into_messages

    bubbles = split_into_messages(reply, max_bubbles=decision.max_bubbles)
    print(f"→ mode: {decision.mode} ({decision.reason})")
    print(f"💬 Emma (would send {len(bubbles)} message(s)):")
    for i, b in enumerate(bubbles, 1):
        print(f"  [{i}] {b}")


if __name__ == "__main__":
    main()
