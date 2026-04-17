"""
Telegram File Sharing Bot - Main Entry Point
Runs Flask (for Render port binding) + bot polling together.
"""

import logging
import asyncio
import threading
from flask import Flask
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, filters,
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

# ── Flask app (keeps Render Web Service alive) ───────────────────────────────
flask_app = Flask(__name__)

@flask_app.route("/")
def health():
    return "Bot is running!", 200

@flask_app.route("/health")
def healthcheck():
    return {"status": "ok"}, 200


def run_flask():
    import os
    port = int(os.environ.get("PORT", 8080))
    flask_app.run(host="0.0.0.0", port=port)


# ── Bot ───────────────────────────────────────────────────────────────────────

async def post_init(application: Application) -> None:
    await start_scheduler(application)
    logger.info("Bot initialized and scheduler started.")


async def run_bot():
    config = Config()
    db = Database(config.MONGO_URI, config.DB_NAME)

    application = (
        Application.builder()
        .token(config.BOT_TOKEN)
        .post_init(post_init)
        .build()
    )

    application.bot_data["config"] = config
    application.bot_data["db"] = db

    application.add_handler(CommandHandler("start", start_handler))

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

    application.add_handler(CommandHandler("buy", buy_handler))
    application.add_handler(CommandHandler("paid", paid_handler))
    application.add_handler(CommandHandler("status", status_handler))
    application.add_handler(CommandHandler("referral", referral_handler))
    application.add_handler(CommandHandler("help", help_handler))

    application.add_handler(CallbackQueryHandler(callback_handler))

    logger.info("Starting bot polling...")

    async with application:
        await application.start()
        await application.updater.start_polling(
            allowed_updates=["message", "callback_query"]
        )
        await asyncio.Event().wait()


if __name__ == "__main__":
    # Start Flask in a background thread
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    logger.info("Flask server started.")

    # Run bot in main thread
    try:
        asyncio.run(run_bot())
    except KeyboardInterrupt:
        logger.info("Bot stopped.")
