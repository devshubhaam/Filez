"""
/start handler — routes deep-links for file access and verification.

Deep-link patterns:
  /start                        → welcome
  /start file_<id>              → file request
  /start verify_access_<id>     → shortlink callback → grant 24h → deliver file
  /start ref_<referrer_id>      → referral tracking
"""

from __future__ import annotations

import logging

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from database.db import Database
from config import Config
from utils.delivery import deliver_file
from utils.helpers import check_force_join
from utils.shortlink import ShortlinkService

logger = logging.getLogger(__name__)


def _get_deps(context: ContextTypes.DEFAULT_TYPE) -> tuple[Config, Database]:
    return context.bot_data["config"], context.bot_data["db"]


async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    config, db = _get_deps(context)

    # Track user
    db.upsert_user(user.id, user.first_name, user.username)

    args = context.args or []
    payload = args[0] if args else ""

    # ── Route deep-links ────────────────────────────────────────────────
    if payload.startswith("file_"):
        unique_id = payload[len("file_"):]
        await _handle_file_request(update, context, unique_id)

    elif payload.startswith("verify_access_"):
        unique_id = payload[len("verify_access_"):]
        await _handle_verify_access(update, context, unique_id)

    elif payload.startswith("ref_"):
        referrer_raw = payload[len("ref_"):]
        try:
            referrer_id = int(referrer_raw)
            db.record_referral(referrer_id, user.id)
        except ValueError:
            pass
        await _send_welcome(update, context)

    else:
        await _send_welcome(update, context)


async def _send_welcome(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    config, db = _get_deps(context)
    text = (
        f"👋 <b>Welcome, {user.first_name}!</b>\n\n"
        "📁 This bot lets you access shared files securely.\n\n"
        "🔗 Use a file link to request a file.\n"
        "💎 Use /buy to get a premium subscription.\n"
        "👥 Use /referral to get your referral link.\n"
        "ℹ️ Use /help for more info."
    )
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


async def _handle_file_request(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    unique_id: str,
) -> None:
    user = update.effective_user
    config, db = _get_deps(context)

    # 1. Ban check
    if db.is_banned(user.id):
        await update.message.reply_text("🚫 You have been banned from this bot.")
        return

    # 2. Rate limiting
    allowed, count = db.check_rate_limit(
        user.id, config.RATE_LIMIT_REQUESTS, config.RATE_LIMIT_WINDOW
    )
    if not allowed:
        violations = db.increment_violation(user.id)
        if violations >= config.AUTO_BAN_THRESHOLD:
            db.ban_user(user.id, "Auto-banned: rate limit abuse")
            await update.message.reply_text("🚫 You have been auto-banned for abuse.")
            return
        await update.message.reply_text(
            f"⏳ You're sending requests too fast. Please wait a moment.\n"
            f"Warning {violations}/{config.AUTO_BAN_THRESHOLD}"
        )
        return

    # 3. Force join check
    missing_channels = await check_force_join(
        context.bot, user.id, config.FORCE_JOIN_CHANNELS
    )
    if missing_channels:
        await _send_force_join(update, context, missing_channels, unique_id)
        return

    # 4. Fetch file
    file_doc = db.get_file(unique_id)
    if not file_doc:
        await update.message.reply_text("❌ File not found. The link may be invalid.")
        return

    # 5. Access priority
    if db.is_premium(user.id):
        await _deliver(update, context, file_doc)
        return

    if db.is_verified(user.id):
        await _deliver(update, context, file_doc)
        return

    # 6. Require shortlink verification
    await _send_shortlink_gate(update, context, unique_id)


async def _handle_verify_access(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    unique_id: str,
) -> None:
    user = update.effective_user
    config, db = _get_deps(context)

    # Ban check
    if db.is_banned(user.id):
        await update.message.reply_text("🚫 You have been banned.")
        return

    # Grant verification
    db.verify_user(user.id, config.VERIFY_HOURS)
    db.track_shortlink_click()

    # Reward referrer if this is their first verification
    referrer_id = db.reward_referrer_if_eligible(user.id, config.VERIFY_HOURS)
    if referrer_id:
        try:
            await context.bot.send_message(
                chat_id=referrer_id,
                text=(
                    "🎉 <b>Referral Reward!</b>\n"
                    f"One of your referrals just verified.\n"
                    f"You've been granted {config.VERIFY_HOURS}h free access!"
                ),
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            pass

    await update.message.reply_text(
        f"✅ <b>Verified!</b> You have {config.VERIFY_HOURS}h free access.\n\n"
        "Fetching your file...",
        parse_mode=ParseMode.HTML,
    )

    # Deliver file if unique_id is valid
    file_doc = db.get_file(unique_id)
    if not file_doc:
        await update.message.reply_text("❌ File not found.")
        return

    await _deliver(update, context, file_doc)


async def _deliver(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    file_doc: dict,
) -> None:
    config, db = _get_deps(context)
    chat_id = update.effective_chat.id
    unique_id = file_doc["unique_id"]

    sending_msg = await update.message.reply_text("📤 Sending your file(s)...")

    try:
        sent_ids = await deliver_file(
            bot=context.bot,
            chat_id=chat_id,
            file_doc=file_doc,
            db=db,
            auto_delete_minutes=config.AUTO_DELETE_MINUTES,
        )
    except Exception as e:
        logger.error("Delivery error for %s: %s", unique_id, e)
        await sending_msg.edit_text("❌ Failed to deliver file. Please try again later.")
        return

    await sending_msg.delete()

    # Share button
    share_url = f"{config.FRONTEND_URL}/file.html?id={unique_id}"
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔗 Share this file", url=f"https://t.me/share/url?url={share_url}")]
    ])

    note = ""
    if config.AUTO_DELETE_MINUTES > 0:
        note = f"\n\n⚠️ Files will be deleted in <b>{config.AUTO_DELETE_MINUTES} minutes</b>."

    await update.message.reply_text(
        f"✅ File delivered!{note}",
        reply_markup=keyboard,
        parse_mode=ParseMode.HTML,
    )


async def _send_shortlink_gate(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    unique_id: str,
) -> None:
    config, db = _get_deps(context)

    # Build verify URL
    verify_url = f"https://t.me/{config.BOT_USERNAME}?start=verify_access_{unique_id}"

    # Generate shortlink
    svc = ShortlinkService(
        config.SHORTLINK_PRIMARY,
        config.SHORTLINK_API_KEY,
        config.SHORTLINK_API_KEY_2,
    )
    short_url = await svc.shorten(verify_url)

    if not short_url:
        # Fallback: direct verify link (no monetization but no breakage)
        short_url = verify_url
        logger.warning("Shortlink generation failed, using direct link as fallback.")

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔓 Unlock File (Complete Task)", url=short_url)]
    ])
    await update.message.reply_text(
        "🔒 <b>This file requires verification.</b>\n\n"
        "1️⃣ Click the button below\n"
        "2️⃣ Complete the short task/ad\n"
        "3️⃣ You'll be redirected back to get your file\n\n"
        f"✅ Access valid for <b>{config.VERIFY_HOURS} hours</b> after verification.",
        reply_markup=keyboard,
        parse_mode=ParseMode.HTML,
    )


async def _send_force_join(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    channels: list[str],
    unique_id: str,
) -> None:
    config = context.bot_data["config"]
    buttons = []
    for ch in channels:
        label = f"@{ch}" if not ch.startswith("-") else ch
        invite_url = f"https://t.me/{ch}" if not ch.startswith("-") else f"https://t.me/c/{ch[4:]}"
        buttons.append([InlineKeyboardButton(f"📢 Join {label}", url=invite_url)])

    buttons.append([
        InlineKeyboardButton(
            "✅ I've Joined — Check Again",
            callback_data=f"check_join|{unique_id}",
        )
    ])

    await update.message.reply_text(
        "⚠️ <b>You must join our channel(s) to use this bot.</b>\n\n"
        "Please join and then click <b>Check Again</b>.",
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode=ParseMode.HTML,
    )
