"""Set Railway poller env vars from local .env (run from fanvue-emma-bot/)."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parent.parent
env = dotenv_values(ROOT / ".env")

pairs = {
    "ACCOUNT_ID": "emma",
    "DATABASE_URL": "${{Postgres.DATABASE_URL}}",
    "REDIS_URL": "${{Redis.REDIS_URL}}",
    "DEEPSEEK_API_KEY": env.get("DEEPSEEK_API_KEY") or "",
    "DEEPSEEK_BASE_URL": env.get("DEEPSEEK_BASE_URL") or "https://api.deepseek.com/v1",
    "DEEPSEEK_MODEL": env.get("DEEPSEEK_MODEL") or "deepseek-v4-pro",
    "DEEPSEEK_DISABLE_THINKING": env.get("DEEPSEEK_DISABLE_THINKING") or "1",
    "DEEPSEEK_TEMPERATURE": env.get("DEEPSEEK_TEMPERATURE") or "0.9",
    "LEAN_CREATIVE": env.get("LEAN_CREATIVE") or "1",
    "SIMPLE_PROMPT": env.get("SIMPLE_PROMPT") or "1",
    "ENGLISH_ONLY": env.get("ENGLISH_ONLY") or "1",
    "REPLY_V2": env.get("REPLY_V2") or "0",
    "PHASE_ANALYST": env.get("PHASE_ANALYST") or "0",
    "INJECT_LESSONS": env.get("INJECT_LESSONS") or "0",
    "AUTO_APPROVE_SOFT_LESSONS": env.get("AUTO_APPROVE_SOFT_LESSONS") or "0",
    "FANVUE_CLIENT_ID": env.get("FANVUE_CLIENT_ID") or "",
    "FANVUE_CLIENT_SECRET": env.get("FANVUE_CLIENT_SECRET") or "",
    "FANVUE_BASE_URL": env.get("FANVUE_BASE_URL") or "https://api.fanvue.com",
    "FANVUE_AUTH_URL": env.get("FANVUE_AUTH_URL") or "https://auth.fanvue.com/oauth2/auth",
    "FANVUE_TOKEN_URL": env.get("FANVUE_TOKEN_URL") or "https://auth.fanvue.com/oauth2/token",
    "FANVUE_API_VERSION": env.get("FANVUE_API_VERSION") or "2025-06-26",
    "XAI_API_KEY": env.get("XAI_API_KEY") or "",
    "XAI_BASE_URL": env.get("XAI_BASE_URL") or "https://api.x.ai/v1",
    "XAI_VISION_MODEL": env.get("XAI_VISION_MODEL") or "grok-4.3",
    "ELEVENLABS_API_KEY": env.get("ELEVENLABS_API_KEY") or "",
    "ELEVENLABS_VOICE_ID": env.get("ELEVENLABS_VOICE_ID") or "oYoxu0RJZLh7yD78dUU7",
    "VOICE_NOTES_ENABLED": env.get("VOICE_NOTES_ENABLED") or "1",
}

railway = "railway.cmd" if sys.platform.startswith("win") else "railway"
# Set in batches — Windows command line length limits
items = [(k, v) for k, v in pairs.items() if v]
print("setting", len(items), "vars...")
for i in range(0, len(items), 4):
    batch = items[i : i + 4]
    args = [railway, "variable", "set", "--service", "poller", "--skip-deploys"]
    args.extend(f"{k}={v}" for k, v in batch)
    print(" ", ", ".join(k for k, _ in batch))
    r = subprocess.run(args, cwd=ROOT)
    if r.returncode != 0:
        sys.exit(r.returncode)
print("OK")
