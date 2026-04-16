"""
Configuration — all values from environment variables.
Copy .env.example to .env and fill in your values.
"""

import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    # ── Telegram ────────────────────────────────────────────────────────
    BOT_TOKEN: str = os.environ["BOT_TOKEN"]
    BOT_USERNAME: str = os.environ["BOT_USERNAME"]          # without @
    ADMIN_IDS: list[int] = [
        int(x.strip()) for x in os.environ["ADMIN_IDS"].split(",")
    ]

    # ── MongoDB ─────────────────────────────────────────────────────────
    MONGO_URI: str = os.environ["MONGO_URI"]
    DB_NAME: str = os.getenv("DB_NAME", "filesharebot")

    # ── Force join ──────────────────────────────────────────────────────
    # Comma-separated channel usernames (without @) or IDs
    FORCE_JOIN_CHANNELS: list[str] = [
        x.strip() for x in os.getenv("FORCE_JOIN_CHANNELS", "").split(",")
        if x.strip()
    ]

    # ── Shortlink providers ─────────────────────────────────────────────
    SHORTLINK_PRIMARY: str = os.getenv("SHORTLINK_PRIMARY", "linkshortify")
    SHORTLINK_API_KEY: str = os.getenv("SHORTLINK_API_KEY", "")
    SHORTLINK_API_KEY_2: str = os.getenv("SHORTLINK_API_KEY_2", "")   # fallback

    # ── Frontend (Netlify) ───────────────────────────────────────────────
    FRONTEND_URL: str = os.getenv(
        "FRONTEND_URL", "https://yourfrontend.netlify.app"
    )

    # ── UPI Payment ─────────────────────────────────────────────────────
    UPI_ID: str = os.getenv("UPI_ID", "yourname@upi")
    UPI_NAME: str = os.getenv("UPI_NAME", "Bot Admin")

    # ── Premium plan prices (INR) ────────────────────────────────────────
    PLAN_PRICES: dict[str, int] = {
        "7days": int(os.getenv("PRICE_7DAYS", "49")),
        "30days": int(os.getenv("PRICE_30DAYS", "99")),
        "90days": int(os.getenv("PRICE_90DAYS", "199")),
    }
    PLAN_DAYS: dict[str, int] = {
        "7days": 7,
        "30days": 30,
        "90days": 90,
    }

    # ── Rate limiting ────────────────────────────────────────────────────
    RATE_LIMIT_REQUESTS: int = int(os.getenv("RATE_LIMIT_REQUESTS", "10"))
    RATE_LIMIT_WINDOW: int = int(os.getenv("RATE_LIMIT_WINDOW", "60"))   # seconds
    AUTO_BAN_THRESHOLD: int = int(os.getenv("AUTO_BAN_THRESHOLD", "5"))  # violations

    # ── Auto-delete files after X minutes (0 = no delete) ───────────────
    AUTO_DELETE_MINUTES: int = int(os.getenv("AUTO_DELETE_MINUTES", "30"))

    # ── Verification window ──────────────────────────────────────────────
    VERIFY_HOURS: int = int(os.getenv("VERIFY_HOURS", "24"))

    # ── Scheduler intervals (seconds) ────────────────────────────────────
    CLEANUP_INTERVAL: int = int(os.getenv("CLEANUP_INTERVAL", "3600"))
