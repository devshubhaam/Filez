"""
Callback query handler — routes all inline button presses.
"""

from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import ContextTypes

from handlers.admin import approve_payment_handler, reject_payment_handler
from utils.helpers import check_force_join

logger = logging.getLogger(__name__)


async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    data: str = query.data or ""
    config = context.bot_data["config"]
    db = context.bot_data["db"]

    # ── Payment approval ─────────────────────────────────────────────────
    if data.startswith("approve_pay|"):
        utr = data.split("|", 1)[1]
        await approve_payment_handler(update, context, utr)

    elif data.startswith("reject_pay|"):
        utr = data.split("|", 1)[1]
        await reject_payment_handler(update, context, utr)

    # ── Force join recheck ────────────────────────────────────────────────
    elif data.startswith("check_join|"):
        unique_id = data.split("|", 1)[1]
        user = update.effective_user
        missing = await check_force_join(context.bot, user.id, config.FORCE_JOIN_CHANNELS)

        if missing:
            await query.answer("❌ You haven't joined all channels yet!", show_alert=True)
        else:
            await query.edit_message_text("✅ Verified! Please re-send the file link.")
            # Re-trigger file access
            from handlers.start import _handle_file_request
            await _handle_file_request(update, context, unique_id)

    # ── Plan info buttons ─────────────────────────────────────────────────
    elif data.startswith("plan|"):
        plan = data.split("|", 1)[1]
        prices = config.PLAN_PRICES
        upi_id = config.UPI_ID
        await query.answer(
            f"Send ₹{prices.get(plan, '?')} to {upi_id} then use /paid",
            show_alert=True,
        )

    else:
        logger.warning("Unknown callback data: %s", data)
