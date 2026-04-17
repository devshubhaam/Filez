"""
Configuration — all values from environment variables.
"""

import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    # ── Telegram ────────────────────────────────────────────────────────
    BOT_TOKEN: str = os.environ["BOT_TOKEN"]
    BOT_USERNAME: str = os.environ["BOT_USERNAME"]
    ADMIN_IDS: list[int] = [
        int(x.strip()) for x in os.environ["ADMIN_IDS"].split(",")
    ]

    # ── Multi-bot usernames (for Netlify rotation) ───────────────────────
    # Comma-separated bot usernames WITHOUT @
    # Example: BOT_USERNAMES=FileBot1,FileBot2,FileBot3
    BOT_USERNAMES: list[str] = [
        x.strip() for x in os.getenv("BOT_USERNAMES", os.environ["BOT_USERNAME"]).split(",")
        if x.strip()
    ]

    # ── MongoDB ─────────────────────────────────────────────────────────
    MONGO_URI: str = os.environ["MONGO_URI"]
    DB_NAME: str = os.getenv("DB_NAME", "filesharebot")

    # ── Force join ──────────────────────────────────────────────────────
    FORCE_JOIN_CHANNELS: list[str] = [
        x.strip() for x in os.getenv("FORCE_JOIN_CHANNELS", "").split(",")
        if x.strip()
    ]

    # ── Shortlink ───────────────────────────────────────────────────────
    SHORTLINK_PRIMARY: str = os.getenv("SHORTLINK_PRIMARY", "linkshortify")
    SHORTLINK_API_KEY: str = os.getenv("SHORTLINK_API_KEY", "")
    SHORTLINK_API_KEY_2: str = os.getenv("SHORTLINK_API_KEY_2", "")

    # ── Frontend ─────────────────────────────────────────────────────────
    FRONTEND_URL: str = os.getenv("FRONTEND_URL", "https://yourfrontend.netlify.app")

    # ── UPI ──────────────────────────────────────────────────────────────
    UPI_ID: str = os.getenv("UPI_ID", "yourname@upi")
    UPI_NAME: str = os.getenv("UPI_NAME", "Bot Admin")

    # ── Premium plans ────────────────────────────────────────────────────
    PLAN_PRICES: dict[str, int] = {
        "7days":  int(os.getenv("PRICE_7DAYS",  "49")),
        "30days": int(os.getenv("PRICE_30DAYS", "99")),
        "90days": int(os.getenv("PRICE_90DAYS", "199")),
    }
    PLAN_DAYS: dict[str, int] = {"7days": 7, "30days": 30, "90days": 90}

    # ── Rate limiting ────────────────────────────────────────────────────
    RATE_LIMIT_REQUESTS: int = int(os.getenv("RATE_LIMIT_REQUESTS", "10"))
    RATE_LIMIT_WINDOW: int   = int(os.getenv("RATE_LIMIT_WINDOW",   "60"))
    AUTO_BAN_THRESHOLD: int  = int(os.getenv("AUTO_BAN_THRESHOLD",  "5"))

    # ── Auto-delete ──────────────────────────────────────────────────────
    AUTO_DELETE_MINUTES: int = int(os.getenv("AUTO_DELETE_MINUTES", "30"))

    # ── Verification ─────────────────────────────────────────────────────
    VERIFY_HOURS: int = int(os.getenv("VERIFY_HOURS", "24"))

    # ── Scheduler ────────────────────────────────────────────────────────
    CLEANUP_INTERVAL: int = int(os.getenv("CLEANUP_INTERVAL", "3600"))
