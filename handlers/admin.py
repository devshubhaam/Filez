"""
Admin handlers.
"""

from __future__ import annotations

import logging

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from config import Config
from database.db import Database
from utils.helpers import parse_caption, generate_unique_id

logger = logging.getLogger(__name__)


def _get_deps(context: ContextTypes.DEFAULT_TYPE) -> tuple[Config, Database]:
    return context.bot_data["config"], context.bot_data["db"]


def _is_admin(user_id: int, config: Config) -> bool:
    return user_id in config.ADMIN_IDS


# ── File Upload ───────────────────────────────────────────────────────────────

async def upload_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    config, db = _get_deps(context)
    user = update.effective_user

    if not _is_admin(user.id, config):
        return

    msg = update.message
    caption = msg.caption or ""

    # Detect file type and extract file_id
    file_id: str | None = None
    file_type: str = "document"

    if msg.video:
        file_id = msg.video.file_id
        file_type = "video"
    elif msg.document:
        file_id = msg.document.file_id
        file_type = "document"
    elif msg.audio:
        file_id = msg.audio.file_id
        file_type = "audio"
    elif msg.photo:
        file_id = msg.photo[-1].file_id  # highest res
        file_type = "photo"

    if not file_id:
        await msg.reply_text("❌ Unsupported file type.")
        return

    unique_id, part, title = parse_caption(caption)
    if not unique_id:
        unique_id = generate_unique_id()

    db.upsert_file_media(unique_id, file_id, file_type, part, title)

    config_obj = context.bot_data["config"]
    frontend_url = config_obj.FRONTEND_URL
    file_link = f"{frontend_url}/file.html?id={unique_id}"

    await msg.reply_text(
        f"✅ <b>File Stored!</b>\n\n"
        f"🆔 ID: <code>{unique_id}</code>\n"
        f"📁 Type: {file_type}\n"
        f"🔢 Part: {part if part else 'N/A'}\n"
        f"📝 Title: {title or 'N/A'}\n\n"
        f"🔗 <b>Share Link:</b>\n{file_link}",
        parse_mode=ParseMode.HTML,
    )


# ── Stats ─────────────────────────────────────────────────────────────────────

async def admin_stats_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    config, db = _get_deps(context)
    if not _is_admin(update.effective_user.id, config):
        return

    stats = db.get_analytics()
    pending = db.get_pending_payments()

    text = (
        "📊 <b>Bot Statistics</b>\n\n"
        f"👥 Total Users: <b>{stats['total_users']}</b>\n"
        f"📁 Total Files: <b>{stats['total_files']}</b>\n"
        f"👁 Total Views: <b>{stats['total_views']}</b>\n"
        f"🔗 Shortlink Clicks: <b>{stats['shortlink_clicks']}</b>\n"
        f"💳 Pending Payments: <b>{len(pending)}</b>\n"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


# ── Ban / Unban ───────────────────────────────────────────────────────────────

async def ban_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    config, db = _get_deps(context)
    if not _is_admin(update.effective_user.id, config):
        return

    args = context.args
    if not args:
        await update.message.reply_text("Usage: /ban <user_id> [reason]")
        return

    try:
        uid = int(args[0])
    except ValueError:
        await update.message.reply_text("❌ Invalid user ID.")
        return

    reason = " ".join(args[1:]) if len(args) > 1 else "Admin ban"
    db.ban_user(uid, reason)
    await update.message.reply_text(f"✅ User <code>{uid}</code> banned.\nReason: {reason}", parse_mode=ParseMode.HTML)


async def unban_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    config, db = _get_deps(context)
    if not _is_admin(update.effective_user.id, config):
        return

    args = context.args
    if not args:
        await update.message.reply_text("Usage: /unban <user_id>")
        return

    try:
        uid = int(args[0])
    except ValueError:
        await update.message.reply_text("❌ Invalid user ID.")
        return

    db.unban_user(uid)
    await update.message.reply_text(f"✅ User <code>{uid}</code> unbanned.", parse_mode=ParseMode.HTML)


# ── Broadcast ─────────────────────────────────────────────────────────────────

async def broadcast_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    config, db = _get_deps(context)
    if not _is_admin(update.effective_user.id, config):
        return

    if not context.args:
        await update.message.reply_text(
            "Usage: /broadcast <message>\n\n"
            "Supports HTML formatting."
        )
        return

    text = " ".join(context.args)
    all_ids = db.all_user_ids()
    sent = failed = 0

    status_msg = await update.message.reply_text(f"📡 Broadcasting to {len(all_ids)} users...")

    for uid in all_ids:
        try:
            await context.bot.send_message(chat_id=uid, text=text, parse_mode=ParseMode.HTML)
            sent += 1
        except Exception:
            failed += 1

    await status_msg.edit_text(
        f"✅ Broadcast done!\n✅ Sent: {sent}\n❌ Failed: {failed}"
    )


# ── Force join ────────────────────────────────────────────────────────────────

async def set_force_join_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    config, db = _get_deps(context)
    if not _is_admin(update.effective_user.id, config):
        return

    if not context.args:
        current = ", ".join(config.FORCE_JOIN_CHANNELS) or "None"
        await update.message.reply_text(
            f"Current force-join channels: {current}\n\n"
            "Usage: /setforcejoin channel1 channel2 ..."
        )
        return

    channels = context.args
    config.FORCE_JOIN_CHANNELS = channels
    db.set_setting("force_join_channels", channels)
    await update.message.reply_text(f"✅ Force-join channels updated: {', '.join(channels)}")


# ── Delete file ───────────────────────────────────────────────────────────────

async def delete_file_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    config, db = _get_deps(context)
    if not _is_admin(update.effective_user.id, config):
        return

    if not context.args:
        await update.message.reply_text("Usage: /delfile <unique_id>")
        return

    uid = context.args[0]
    deleted = db.delete_file(uid)
    if deleted:
        await update.message.reply_text(f"🗑 File <code>{uid}</code> deleted.", parse_mode=ParseMode.HTML)
    else:
        await update.message.reply_text(f"❌ File <code>{uid}</code> not found.", parse_mode=ParseMode.HTML)


# ── Payment approval (called from callback) ───────────────────────────────────

async def approve_payment_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    utr: str,
) -> None:
    config, db = _get_deps(context)
    payment = db.get_payment(utr)
    if not payment:
        await update.callback_query.answer("Payment not found.")
        return

    if payment["status"] != "pending":
        await update.callback_query.answer(f"Already {payment['status']}.")
        return

    plan = payment["plan"]
    days = config.PLAN_DAYS.get(plan, 30)
    expiry = db.grant_premium(payment["user_id"], days)
    db.update_payment_status(utr, "approved")

    await update.callback_query.answer("✅ Approved!")
    await update.callback_query.edit_message_text(
        f"✅ Payment <code>{utr}</code> <b>APPROVED</b>.\n"
        f"Plan: {plan} | Expires: {expiry.strftime('%Y-%m-%d %H:%M')} UTC",
        parse_mode=ParseMode.HTML,
    )

    try:
        await context.bot.send_message(
            chat_id=payment["user_id"],
            text=(
                f"🎉 <b>Premium Activated!</b>\n\n"
                f"Plan: <b>{plan}</b>\n"
                f"Expires: <b>{expiry.strftime('%Y-%m-%d %H:%M')} UTC</b>\n\n"
                "Enjoy unlimited file access! 🚀"
            ),
            parse_mode=ParseMode.HTML,
        )
    except Exception:
        pass


async def reject_payment_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    utr: str,
) -> None:
    db = context.bot_data["db"]
    payment = db.get_payment(utr)
    if not payment:
        await update.callback_query.answer("Payment not found.")
        return

    db.update_payment_status(utr, "rejected")
    await update.callback_query.answer("❌ Rejected.")
    await update.callback_query.edit_message_text(
        f"❌ Payment <code>{utr}</code> <b>REJECTED</b>.",
        parse_mode=ParseMode.HTML,
    )

    try:
        await context.bot.send_message(
            chat_id=payment["user_id"],
            text=(
                "❌ <b>Payment Rejected</b>\n\n"
                f"UTR: <code>{utr}</code>\n\n"
                "If you believe this is an error, please contact support."
            ),
            parse_mode=ParseMode.HTML,
        )
    except Exception:
        pass
