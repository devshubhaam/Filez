"""
Telegram File Sharing Bot - Main Entry Point
Production-ready, MongoDB-backed, shortlink-monetized
"""

import logging
import asyncio
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, filters, ConversationHandler
)
from config import Config
from handlers.start import start_handler
from handlers.admin import (
    upload_handler, admin_stats_handler, ban_handler, unban_handler,
    broadcast_handler, set_force_join_handler, approve_payment_handler,
    reject_payment_handler, delete_file_handler
)
from handlers.user import (
    buy_handler, paid_handler, status_handler,
    referral_handler, help_handler
)
from handlers.callbacks import callback_handler
from database.db import Database
from utils.scheduler import start_scheduler

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
    handlers=[
        logging.FileHandler("bot.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


async def post_init(application: Application) -> None:
    """Post-init hook: start background scheduler."""
    await start_scheduler(application)
    logger.info("Bot initialized and scheduler started.")


def main():
    config = Config()
    db = Database(config.MONGO_URI, config.DB_NAME)

    application = (
        Application.builder()
        .token(config.BOT_TOKEN)
        .post_init(post_init)
        .build()
    )

    # Store config and db in bot_data
    application.bot_data["config"] = config
    application.bot_data["db"] = db

    # ── Start / deep-link handlers ──────────────────────────────────────
    application.add_handler(CommandHandler("start", start_handler))

    # ── Admin commands ──────────────────────────────────────────────────
    application.add_handler(
        MessageHandler(
            filters.Chat(config.ADMIN_IDS) & (
                filters.VIDEO | filters.Document.ALL |
                filters.AUDIO | filters.PHOTO
            ),
            upload_handler
        )
    )
    application.add_handler(CommandHandler("stats", admin_stats_handler))
    application.add_handler(CommandHandler("ban", ban_handler))
    application.add_handler(CommandHandler("unban", unban_handler))
    application.add_handler(CommandHandler("broadcast", broadcast_handler))
    application.add_handler(CommandHandler("setforcejoin", set_force_join_handler))
    application.add_handler(CommandHandler("delfile", delete_file_handler))

    # ── User commands ───────────────────────────────────────────────────
    application.add_handler(CommandHandler("buy", buy_handler))
    application.add_handler(CommandHandler("paid", paid_handler))
    application.add_handler(CommandHandler("status", status_handler))
    application.add_handler(CommandHandler("referral", referral_handler))
    application.add_handler(CommandHandler("help", help_handler))

    # ── Inline button callbacks ─────────────────────────────────────────
    application.add_handler(CallbackQueryHandler(callback_handler))

    logger.info("Starting bot in polling mode...")
    application.run_polling(allowed_updates=["message", "callback_query"])


if __name__ == "__main__":
    main()
