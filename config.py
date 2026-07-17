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

    # Re-engagement
    REENGAGEMENT_INTERVAL_SECONDS = int(os.getenv("REENGAGEMENT_INTERVAL_SECONDS", "1800"))
    INACTIVE_HOURS = int(os.getenv("INACTIVE_HOURS", "12"))

    # Embeddings
    EMBEDDING_DIM = 1536

    # AI Params (DeepSeek roleplay best-practice: tune temperature, leave top_p=1,
    # penalties have no effect on DeepSeek so keep them at 0).
    DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-v4-pro")
    TEMPERATURE = float(os.getenv("DEEPSEEK_TEMPERATURE", "1.3"))
    TOP_P = float(os.getenv("DEEPSEEK_TOP_P", "1.0"))
    FREQUENCY_PENALTY = 0.0
    PRESENCE_PENALTY = 0.0
    # Generous cap — only prevents runaway output, never truncates normal texting
    MAX_RESPONSE_TOKENS = int(os.getenv("MAX_RESPONSE_TOKENS", "400"))
    # v4 models "think" and can burn the whole token budget → empty reply.
    # Disable thinking for fast, natural roleplay (recommended for NSFW chat).
    DEEPSEEK_DISABLE_THINKING = os.getenv("DEEPSEEK_DISABLE_THINKING", "1") == "1"

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

    # Soft autopilot + daily digest
    AUTO_APPROVE_SOFT_LESSONS = os.getenv("AUTO_APPROVE_SOFT_LESSONS", "1") == "1"
    DIGEST_WEBHOOK_URL = os.getenv("DIGEST_WEBHOOK_URL", "")  # Discord/Slack incoming webhook
    DIGEST_EMAIL = os.getenv("DIGEST_EMAIL", "")
    SMTP_HOST = os.getenv("SMTP_HOST", "")
    SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
    SMTP_USER = os.getenv("SMTP_USER", "")
    SMTP_PASS = os.getenv("SMTP_PASS", "")
    SMTP_FROM = os.getenv("SMTP_FROM", "")


config = Config()
