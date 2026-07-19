import os
from dotenv import load_dotenv

load_dotenv()

# Scopes requested during OAuth (must be enabled in the Fanvue Builder).
FANVUE_OAUTH_SCOPES = (
    "openid offline_access offline "
    "read:self read:chat write:chat read:fan read:creator "
    "read:media write:media read:insights"
)


class Config:
    # DeepSeek
    DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
    DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1")

    # Fanvue OAuth 2.0
    FANVUE_CLIENT_ID = os.getenv("FANVUE_CLIENT_ID")
    FANVUE_CLIENT_SECRET = os.getenv("FANVUE_CLIENT_SECRET")
    FANVUE_BASE_URL = os.getenv("FANVUE_BASE_URL", "https://api.fanvue.com")
    FANVUE_AUTH_URL = os.getenv("FANVUE_AUTH_URL", "https://auth.fanvue.com/oauth2/auth")
    FANVUE_TOKEN_URL = os.getenv("FANVUE_TOKEN_URL", "https://auth.fanvue.com/oauth2/token")
    FANVUE_API_VERSION = os.getenv("FANVUE_API_VERSION", "2025-06-26")
    FANVUE_REDIRECT_URI = os.getenv("FANVUE_REDIRECT_URI", "https://localhost:8000/oauth/callback")
    FANVUE_OAUTH_SCOPES = FANVUE_OAUTH_SCOPES
    # Path where access/refresh tokens are stored after OAuth login.
    FANVUE_TOKEN_FILE = os.getenv("FANVUE_TOKEN_FILE", ".fanvue_tokens.json")
    # If empty, webhook signature verification is skipped (dev only).
    FANVUE_WEBHOOK_SECRET = os.getenv("FANVUE_WEBHOOK_SECRET", "")

    # DB / multi-account
    DATABASE_URL = os.getenv("DATABASE_URL")
    REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    ACCOUNT_ID = os.getenv("ACCOUNT_ID", "emma")

    # Celery
    CELERY_BROKER_URL = os.getenv("CELERY_BROKER_URL", REDIS_URL)
    CELERY_RESULT_BACKEND = os.getenv("CELERY_RESULT_BACKEND", REDIS_URL)

    # Re-engagement (hot/cold ladder; see core/reengagement.py)
    REENGAGEMENT_INTERVAL_SECONDS = int(os.getenv("REENGAGEMENT_INTERVAL_SECONDS", "1800"))
    INACTIVE_HOURS = int(os.getenv("INACTIVE_HOURS", "12"))
    NUDGE_HOT_MINUTES = int(os.getenv("NUDGE_HOT_MINUTES", "7"))
    NUDGE_COLD_MINUTES = int(os.getenv("NUDGE_COLD_MINUTES", "7"))
    NUDGE_FIRST_MINUTES = int(
        os.getenv("NUDGE_FIRST_MINUTES", str(max(NUDGE_HOT_MINUTES, NUDGE_COLD_MINUTES)))
    )
    NUDGE_SECOND_MINUTES = int(os.getenv("NUDGE_SECOND_MINUTES", "36"))
    MAX_NUDGES_PER_EPISODE = int(os.getenv("MAX_NUDGES_PER_EPISODE", "2"))
    VICTIM_AFTER_SEEN_MINUTES = int(os.getenv("VICTIM_AFTER_SEEN_MINUTES", "60"))
    VICTIM_COOLDOWN_HOURS = int(os.getenv("VICTIM_COOLDOWN_HOURS", "12"))

    # Embeddings
    EMBEDDING_DIM = 1536

    # AI Params — V2 creative defaults (human-like, less repetitive)
    DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-v4-pro")
    TEMPERATURE = float(os.getenv("DEEPSEEK_TEMPERATURE", "1.0"))
    TOP_P = float(os.getenv("DEEPSEEK_TOP_P", "0.95"))
    FREQUENCY_PENALTY = float(os.getenv("DEEPSEEK_FREQUENCY_PENALTY", "0.4"))
    PRESENCE_PENALTY = float(os.getenv("DEEPSEEK_PRESENCE_PENALTY", "0.5"))
    # Ceiling so the API can finish the thought; length rewrite + splitter keep it short.
    MAX_RESPONSE_TOKENS = int(os.getenv("MAX_RESPONSE_TOKENS", "220"))
    DEEPSEEK_DISABLE_THINKING = os.getenv("DEEPSEEK_DISABLE_THINKING", "1") == "1"
    # Per Fanvue bubble. Over-long replies are REWRITTEN short — not mid-cut with "…".
    BUBBLE_MAX_CHARS = int(os.getenv("BUBBLE_MAX_CHARS", "140"))
    MAX_BUBBLES = int(os.getenv("MAX_BUBBLES", "2"))
    # Soft total for the whole reply (triggers length rewrite before send)
    REPLY_SOFT_MAX_CHARS = int(os.getenv("REPLY_SOFT_MAX_CHARS", "160"))

    # Chat history fed to DeepSeek (not the whole inbox — recent window only).
    # Too much history → model imitates old bland turns and loses voice consistency.
    HISTORY_HOURS = int(os.getenv("HISTORY_HOURS", "36"))
    HISTORY_MAX_MESSAGES = int(os.getenv("HISTORY_MAX_MESSAGES", "36"))
    HISTORY_MIN_MESSAGES = int(os.getenv("HISTORY_MIN_MESSAGES", "12"))

    # V2 brain: one English psychology prompt + recent history (default ON).
    # Old pack/analyst/manipulation path only if REPLY_V2=0.
    # Catalog-only sell rails live in reply_engine; V2 off by default.
    REPLY_V2 = os.getenv("REPLY_V2", "0") == "1"
    # Shorter history = less imitation of burned bland turns from old brain
    V2_MAX_HISTORY_TURNS = int(os.getenv("V2_MAX_HISTORY_TURNS", "24"))
    LEAN_CREATIVE = os.getenv("LEAN_CREATIVE", "1") == "1"
    INJECT_LESSONS = os.getenv("INJECT_LESSONS", "0") == "1"
    PHASE_ANALYST = os.getenv("PHASE_ANALYST", "0") == "1"
    SIMPLE_PROMPT = os.getenv("SIMPLE_PROMPT", "1") == "1"
    PHASE_ANALYST_MODEL = os.getenv("PHASE_ANALYST_MODEL", "") or None
    # Ambiguous-turn JSON intent classifier (extra DeepSeek call)
    SOFT_CLASSIFY = os.getenv("SOFT_CLASSIFY", "0") == "1"
    SOFT_CLASSIFY_MODEL = os.getenv("SOFT_CLASSIFY_MODEL", "") or None
    # Closed JSON PPV selector: chooses sell/no-sell + one whitelisted vault UUID.
    OFFER_SELECTOR_AI = os.getenv("OFFER_SELECTOR_AI", "1") == "1"
    OFFER_SELECTOR_MODEL = os.getenv("OFFER_SELECTOR_MODEL", "") or None

    # xAI Grok Vision — vault photo captioning (same key as emma_chatter)
    XAI_API_KEY = os.getenv("XAI_API_KEY", "")
    XAI_BASE_URL = os.getenv("XAI_BASE_URL", "https://api.x.ai/v1")
    XAI_VISION_MODEL = os.getenv("XAI_VISION_MODEL", "grok-4.3")

    # Optional legacy JoyCaption remote (unused if XAI_API_KEY is set)
    JOYCAPTION_BASE_URL = os.getenv("JOYCAPTION_BASE_URL", "")
    JOYCAPTION_API_KEY = os.getenv("JOYCAPTION_API_KEY", "EMPTY")
    JOYCAPTION_MODEL = os.getenv(
        "JOYCAPTION_MODEL",
        "fancyfeast/llama-joycaption-beta-one-hf-llava",
    )

    # Soft autopilot OFF by default — Soft lesson flood broke chat quality
    AUTO_APPROVE_SOFT_LESSONS = os.getenv("AUTO_APPROVE_SOFT_LESSONS", "0") == "1"
    # Hourly DeepSeek review of last-hour turns only (does not inject into live prompt)
    HOUR_REVIEW_ENABLED = os.getenv("HOUR_REVIEW_ENABLED", "1") == "1"
    HOUR_REVIEW_MINUTES = int(os.getenv("HOUR_REVIEW_MINUTES", "60"))
    # Coalesce a burst of fan messages: wait for him to finish typing, then
    # answer the whole batch as ONE turn (better analysis, one reply).
    COALESCE_ENABLED = os.getenv("COALESCE_ENABLED", "1") == "1"
    # Quiet window: if no new fan message arrives for this long, he's done.
    COALESCE_SETTLE_SEC = float(os.getenv("COALESCE_SETTLE_SEC", "4"))
    # Hard cap so we never wait forever on a non-stop typer.
    COALESCE_MAX_WAIT_SEC = float(os.getenv("COALESCE_MAX_WAIT_SEC", "12"))
    # Only wait if his newest message is fresher than this (else we're catching up).
    COALESCE_FRESH_SEC = float(os.getenv("COALESCE_FRESH_SEC", "20"))
    # Show the "Emma is typing…" bubbles the whole time she's thinking/analyzing.
    TYPING_WHILE_THINKING = os.getenv("TYPING_WHILE_THINKING", "1") == "1"
    TYPING_PING_SEC = float(os.getenv("TYPING_PING_SEC", "2.5"))
    # Human-like pause before each bubble (wall-clock; no Fanvue poll stacking)
    BUBBLE_DELAY_FIRST_MIN = float(os.getenv("BUBBLE_DELAY_FIRST_MIN", "4.0"))
    BUBBLE_DELAY_FIRST_MAX = float(os.getenv("BUBBLE_DELAY_FIRST_MAX", "6.5"))
    BUBBLE_DELAY_NEXT_MIN = float(os.getenv("BUBBLE_DELAY_NEXT_MIN", "2.8"))
    BUBBLE_DELAY_NEXT_MAX = float(os.getenv("BUBBLE_DELAY_NEXT_MAX", "4.8"))
    # How often to check barge-in during a bubble delay (API is slow — keep rare)
    BUBBLE_BARGE_CHECK_SEC = float(os.getenv("BUBBLE_BARGE_CHECK_SEC", "3.0"))

    # Unpaid PPV auto-unsend (creates scarcity; keeps chat + bot state clean)
    PPV_EXPIRE_ENABLED = os.getenv("PPV_EXPIRE_ENABLED", "1") == "1"
    PPV_EXPIRE_MINUTES = int(os.getenv("PPV_EXPIRE_MINUTES", "30"))
    # On poller boot: wipe every unpaid lock in recent chats (clean slate), then new ones time out
    PPV_PURGE_ACTIVE_ON_START = os.getenv("PPV_PURGE_ACTIVE_ON_START", "1") == "1"
    DIGEST_WEBHOOK_URL = os.getenv("DIGEST_WEBHOOK_URL", "")  # Discord/Slack incoming webhook
    # When Fanvue refresh dies: alert webhook + optional public callback on poller PORT
    OAUTH_CALLBACK_HTTP = os.getenv("OAUTH_CALLBACK_HTTP", "0") == "1"
    OAUTH_ALERT_COOLDOWN_SEC = int(os.getenv("OAUTH_ALERT_COOLDOWN_SEC", "1800"))
    DIGEST_EMAIL = os.getenv("DIGEST_EMAIL", "")
    SMTP_HOST = os.getenv("SMTP_HOST", "")
    SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
    SMTP_USER = os.getenv("SMTP_USER", "")
    SMTP_PASS = os.getenv("SMTP_PASS", "")
    SMTP_FROM = os.getenv("SMTP_FROM", "")

    # ElevenLabs voice notes (sensual audio at key heating moments)
    ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY", "")
    ELEVENLABS_VOICE_ID = os.getenv("ELEVENLABS_VOICE_ID", "d3MFdIuCfbAIwiu7jC4a")
    ELEVENLABS_MODEL = os.getenv("ELEVENLABS_MODEL", "eleven_multilingual_v2")
    ELEVENLABS_STABILITY = float(os.getenv("ELEVENLABS_STABILITY", "0.38"))
    ELEVENLABS_SIMILARITY = float(os.getenv("ELEVENLABS_SIMILARITY", "0.82"))
    ELEVENLABS_STYLE = float(os.getenv("ELEVENLABS_STYLE", "0.42"))
    ELEVENLABS_TIMEOUT_SEC = int(os.getenv("ELEVENLABS_TIMEOUT_SEC", "45"))
    VOICE_NOTES_ENABLED = os.getenv("VOICE_NOTES_ENABLED", "1") == "1"
    VOICE_NOTES_MIN_MESSAGES = int(os.getenv("VOICE_NOTES_MIN_MESSAGES", "8"))
    VOICE_NOTES_MAX_PER_DAY = int(os.getenv("VOICE_NOTES_MAX_PER_DAY", "2"))
    VOICE_NOTES_COOLDOWN_HOURS = float(os.getenv("VOICE_NOTES_COOLDOWN_HOURS", "6"))
    VOICE_NOTES_CHANCE = float(os.getenv("VOICE_NOTES_CHANCE", "0.55"))
    VOICE_NOTE_MAX_CHARS = int(os.getenv("VOICE_NOTE_MAX_CHARS", "80"))
    VOICE_NOTE_SEND_DELAY_SEC = float(os.getenv("VOICE_NOTE_SEND_DELAY_SEC", "2.5"))
    VOICE_NOTES_VAULT_FOLDER = os.getenv("VOICE_NOTES_VAULT_FOLDER", "voice_notes")

    # Fanvue platform insights → CLIENT CARD (see core/fanvue_insights.py)
    FANVUE_INSIGHTS_ENABLED = os.getenv("FANVUE_INSIGHTS_ENABLED", "1") == "1"
    FANVUE_INSIGHTS_SYNC_HOURS = float(os.getenv("FANVUE_INSIGHTS_SYNC_HOURS", "6"))
    FANVUE_SESSION_HOURS = int(os.getenv("FANVUE_SESSION_HOURS", "24"))
    FANVUE_STATS_MESSAGE_LIMIT = int(os.getenv("FANVUE_STATS_MESSAGE_LIMIT", "200"))
    FANVUE_DIGEST_EVERY_MESSAGES = int(os.getenv("FANVUE_DIGEST_EVERY_MESSAGES", "25"))
    FANVUE_DIGEST_MAX_AGE_HOURS = float(os.getenv("FANVUE_DIGEST_MAX_AGE_HOURS", "12"))


config = Config()
