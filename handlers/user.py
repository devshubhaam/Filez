"""
User command handlers.
"""

from __future__ import annotations

import logging

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from config import Config
from database.db import Database

logger = logging.getLogger(__name__)


def _get_deps(context: ContextTypes.DEFAULT_TYPE) -> tuple[Config, Database]:
    return context.bot_data["config"], context.bot_data["db"]


# ── /buy ─────────────────────────────────────────────────────────────────────

async def buy_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    config, db = _get_deps(context)
    user = update.effective_user
    db.upsert_user(user.id, user.first_name, user.username)

    prices = config.PLAN_PRICES
    upi_id = config.UPI_ID
    upi_name = config.UPI_NAME

    text = (
        "💎 <b>Premium Plans</b>\n\n"
        f"🟢 <b>7 Days</b>  — ₹{prices['7days']}\n"
        f"🔵 <b>30 Days</b> — ₹{prices['30days']}\n"
        f"🟣 <b>90 Days</b> — ₹{prices['90days']}\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "💳 <b>How to Pay:</b>\n"
        f"1. Send payment to UPI:\n   <code>{upi_id}</code>\n"
        f"   Name: <b>{upi_name}</b>\n\n"
        "2. After payment, send:\n"
        "   <code>/paid &lt;UTR_NUMBER&gt; &lt;plan&gt;</code>\n\n"
        "   Example:\n"
        "   <code>/paid 123456789012 30days</code>\n\n"
        "Plans: <code>7days</code> | <code>30days</code> | <code>90days</code>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "✅ Premium = <b>bypass all verifications</b> forever."
    )

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("7 Days ₹" + str(prices["7days"]), callback_data="plan|7days"),
            InlineKeyboardButton("30 Days ₹" + str(prices["30days"]), callback_data="plan|30days"),
        ],
        [InlineKeyboardButton("90 Days ₹" + str(prices["90days"]), callback_data="plan|90days")],
    ])

    await update.message.reply_text(text, reply_markup=keyboard, parse_mode=ParseMode.HTML)


# ── /paid ─────────────────────────────────────────────────────────────────────

async def paid_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    config, db = _get_deps(context)
    user = update.effective_user
    db.upsert_user(user.id, user.first_name, user.username)

    args = context.args
    if len(args) < 2:
        await update.message.reply_text(
            "Usage: <code>/paid &lt;UTR&gt; &lt;plan&gt;</code>\n\n"
            "Example: <code>/paid 123456789012 30days</code>",
            parse_mode=ParseMode.HTML,
        )
        return

    utr = args[0].strip()
    plan = args[1].strip().lower()

    if plan not in config.PLAN_DAYS:
        await update.message.reply_text(
            f"❌ Invalid plan. Choose: <code>7days</code>, <code>30days</code>, <code>90days</code>",
            parse_mode=ParseMode.HTML,
        )
        return

    if len(utr) < 8 or len(utr) > 25:
        await update.message.reply_text("❌ UTR number looks invalid.")
        return

    success = db.create_payment(user.id, utr, plan)
    if not success:
        await update.message.reply_text(
            f"❌ UTR <code>{utr}</code> already submitted. Contact support if needed.",
            parse_mode=ParseMode.HTML,
        )
        return

    # Notify admins
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Approve", callback_data=f"approve_pay|{utr}"),
            InlineKeyboardButton("❌ Reject", callback_data=f"reject_pay|{utr}"),
        ]
    ])
    admin_text = (
        f"💳 <b>New Payment Request</b>\n\n"
        f"👤 User: <a href='tg://user?id={user.id}'>{user.first_name}</a> "
        f"(<code>{user.id}</code>)\n"
        f"🔢 UTR: <code>{utr}</code>\n"
        f"📦 Plan: <b>{plan}</b>\n"
        f"💰 Amount: ₹{config.PLAN_PRICES[plan]}"
    )

    for admin_id in config.ADMIN_IDS:
        try:
            await context.bot.send_message(
                chat_id=admin_id,
                text=admin_text,
                reply_markup=keyboard,
                parse_mode=ParseMode.HTML,
            )
        except Exception as e:
            logger.error("Failed to notify admin %s: %s", admin_id, e)

    await update.message.reply_text(
        f"✅ <b>Payment submitted for review!</b>\n\n"
        f"UTR: <code>{utr}</code>\nPlan: <b>{plan}</b>\n\n"
        "You'll be notified once approved (usually within a few hours).",
        parse_mode=ParseMode.HTML,
    )


# ── /status ───────────────────────────────────────────────────────────────────

async def status_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    config, db = _get_deps(context)
    user = update.effective_user
    db.upsert_user(user.id, user.first_name, user.username)

    is_premium = db.is_premium(user.id)
    is_verified = db.is_verified(user.id)
    expiry = db.get_premium_expiry(user.id)
    ref_count = db.get_referral_count(user.id)

    lines = [f"👤 <b>Status for {user.first_name}</b>\n"]

    if is_premium:
        lines.append(f"💎 <b>Premium</b>: Active ✅")
        if expiry:
            lines.append(f"⏳ Expires: {expiry.strftime('%Y-%m-%d %H:%M')} UTC")
    else:
        lines.append("💎 Premium: Not active")
        if is_verified:
            lines.append("🔓 Verification: Active (24h access)")
        else:
            lines.append("🔒 Verification: Not verified")

    lines.append(f"\n👥 Referrals: <b>{ref_count}</b>")
    lines.append("\nUse /buy to get premium access.")

    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)


# ── /referral ─────────────────────────────────────────────────────────────────

async def referral_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    config, db = _get_deps(context)
    user = update.effective_user
    db.upsert_user(user.id, user.first_name, user.username)

    ref_link = f"https://t.me/{config.BOT_USERNAME}?start=ref_{user.id}"
    ref_count = db.get_referral_count(user.id)

    text = (
        f"👥 <b>Your Referral Link</b>\n\n"
        f"<code>{ref_link}</code>\n\n"
        f"📊 Total Referrals: <b>{ref_count}</b>\n\n"
        f"🎁 <b>How it works:</b>\n"
        f"• Share your link with friends\n"
        f"• When they complete shortlink verification, <b>you get {config.VERIFY_HOURS}h free access</b>!\n\n"
        f"Reward is granted <b>automatically</b> after their first verification."
    )
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


# ── /help ─────────────────────────────────────────────────────────────────────

async def help_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    config, _ = _get_deps(context)
    text = (
        "ℹ️ <b>Help & Commands</b>\n\n"
        "/start — Start the bot\n"
        "/buy — View and purchase premium plans\n"
        "/paid &lt;UTR&gt; &lt;plan&gt; — Submit payment\n"
        "/status — Check your current access status\n"
        "/referral — Get your referral link\n"
        "/help — Show this message\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "📁 <b>Accessing Files:</b>\n"
        "• Click any file share link\n"
        "• Complete the short verification task\n"
        "• Your file will be delivered instantly\n\n"
        "💎 <b>Premium:</b>\n"
        "• Skip all verifications\n"
        "• Instant file access always\n\n"
        "❓ Issues? Contact the bot admin."
    )
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)
