"""
Background scheduler — periodic cleanup and auto-delete tasks.
"""

from __future__ import annotations

import asyncio
import logging

from telegram import Bot
from telegram.error import TelegramError
from telegram.ext import Application

logger = logging.getLogger(__name__)


async def start_scheduler(application: Application) -> None:
    loop = asyncio.get_event_loop()
    loop.create_task(_cleanup_loop(application))
    loop.create_task(_auto_delete_loop(application))
    logger.info("Scheduler tasks started.")


async def _cleanup_loop(application: Application) -> None:
    config = application.bot_data["config"]
    db = application.bot_data["db"]
    while True:
        await asyncio.sleep(config.CLEANUP_INTERVAL)
        try:
            deleted = db.cleanup_expired_verifications()
            if deleted:
                logger.info("Cleaned up %d expired verifications.", deleted)
        except Exception as e:
            logger.error("Cleanup error: %s", e)


async def _auto_delete_loop(application: Application) -> None:
    """Check every 60 seconds for messages to auto-delete."""
    db = application.bot_data["db"]
    bot: Bot = application.bot
    while True:
        await asyncio.sleep(60)
        try:
            tasks = db.get_due_deletions()
            for task in tasks:
                chat_id = task["chat_id"]
                for mid in task.get("message_ids", []):
                    try:
                        await bot.delete_message(chat_id=chat_id, message_id=mid)
                    except TelegramError:
                        pass  # Message already gone
                db.remove_delete_task(task["_id"])
        except Exception as e:
            logger.error("Auto-delete loop error: %s", e)
