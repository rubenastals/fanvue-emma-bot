"""
Test the chat flow WITHOUT webhooks, Postgres, Redis or Celery.

Uses the LIVE SIMPLE brain (personas/emma.md) — not the quarantined fat
system_prompt.py essay.

Usage:
  # 1) Generate reply only (prints to terminal):
  python scripts/test_chat_flow.py --message "hola guapa"

  # 2) Generate + send to a real fan (needs OAuth tokens):
  python scripts/test_chat_flow.py --fan-uuid YOUR_FAN_UUID --message "hola" --send

Get a fan UUID: open a chat on Fanvue → the fan's UUID comes from the API
or from a test account you've messaged before.
"""
import argparse
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from openai import OpenAI
from config import config
from core.prompt_core import get_active_persona


def generate_reply(fan_message: str) -> str:
    client = OpenAI(api_key=config.DEEPSEEK_API_KEY, base_url=config.DEEPSEEK_BASE_URL)
    prompt = f"""
You are Emma Carter. A fan just wrote to you.

**Fan's message:** "{fan_message}"

Reply in character. Short (1-3 lines). Follow all tone and psychology rules.
"""
    resp = client.chat.completions.create(
        model=config.DEEPSEEK_MODEL,
        messages=[
            {"role": "system", "content": get_active_persona()},
            {"role": "user", "content": prompt},
        ],
        temperature=config.TEMPERATURE,
        top_p=config.TOP_P,
        frequency_penalty=config.FREQUENCY_PENALTY,
        presence_penalty=config.PRESENCE_PENALTY,
        max_tokens=config.MAX_RESPONSE_TOKENS,
    )
    return resp.choices[0].message.content


def main():
    parser = argparse.ArgumentParser(description="Test Emma chat flow (no webhooks)")
    parser.add_argument("--message", "-m", required=True, help="Fan message to respond to")
    parser.add_argument("--fan-uuid", help="Fan UUID (required with --send)")
    parser.add_argument("--send", action="store_true", help="Send reply via Fanvue API")
    args = parser.parse_args()

    print(f"Fan: {args.message}\n")
    print("Generating Emma's reply...")
    reply = generate_reply(args.message)
    print(f"\nEmma: {reply}\n")

    if args.send:
        if not args.fan_uuid:
            print("❌ --send requires --fan-uuid")
            sys.exit(1)
        from api.fanvue_connector import FanvueConnector
        fv = FanvueConnector()
        result = fv.send_message(args.fan_uuid, reply)
        print(f"✅ Sent via Fanvue (messageUuid: {result.get('messageUuid')})")
    else:
        print("(Dry run — add --send --fan-uuid XXX to deliver via Fanvue)")


if __name__ == "__main__":
    main()
