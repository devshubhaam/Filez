"""
File delivery — fail-safe, multi-file-id, album-aware sender.

ALBUM RULES (Telegram):
- send_media_group supports: photo + video mixed ✅
- send_media_group supports: document + audio mixed ✅
- photo/video CANNOT be mixed with document/audio ❌
- Max 10 per album
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from telegram import Bot, InputMediaVideo, InputMediaDocument, InputMediaAudio, InputMediaPhoto
from telegram.error import TelegramError

logger = logging.getLogger(__name__)
UTC = timezone.utc

# Telegram's two allowed media group "buckets"
_VISUAL_TYPES  = {"photo", "video"}
_FILE_TYPES    = {"document", "audio"}


def _sort_media(media_list: list[dict]) -> list[dict]:
    """Sort by part number ascending. No-part entries go last."""
    with_part    = [m for m in media_list if m.get("part") is not None]
    without_part = [m for m in media_list if m.get("part") is None]
    with_part.sort(key=lambda m: m["part"])
    return with_part + without_part


def _build_input_media(file_id: str, file_type: str, caption: str = "", parse_mode: str = "HTML"):
    if file_type == "video":
        return InputMediaVideo(media=file_id, caption=caption or None, parse_mode=parse_mode if caption else None)
    elif file_type == "audio":
        return InputMediaAudio(media=file_id, caption=caption or None, parse_mode=parse_mode if caption else None)
    elif file_type == "photo":
        return InputMediaPhoto(media=file_id, caption=caption or None, parse_mode=parse_mode if caption else None)
    else:
        return InputMediaDocument(media=file_id, caption=caption or None, parse_mode=parse_mode if caption else None)


def _can_be_in_same_album(type_a: str, type_b: str) -> bool:
    """Check if two file types can be in the same Telegram media group."""
    if type_a in _VISUAL_TYPES and type_b in _VISUAL_TYPES:
        return True
    if type_a in _FILE_TYPES and type_b in _FILE_TYPES:
        return True
    return False


def _split_into_album_batches(media_list: list[dict]) -> list[list[tuple[int, dict]]]:
    """
    Split media_list into batches that are valid Telegram albums:
    - Max 10 per batch
    - No mixing of visual (photo/video) with file (document/audio) types
    Returns list of batches, each batch is list of (original_idx, media_obj)
    """
    batches: list[list[tuple[int, dict]]] = []
    current_batch: list[tuple[int, dict]] = []
    current_bucket: str | None = None  # "visual" or "file"

    for idx, m in enumerate(media_list):
        ftype = m.get("file_type", "document")
        bucket = "visual" if ftype in _VISUAL_TYPES else "file"

        if current_bucket is None:
            current_bucket = bucket

        # Start new batch if: bucket changed OR batch full (10 items)
        if bucket != current_bucket or len(current_batch) >= 10:
            if current_batch:
                batches.append(current_batch)
            current_batch = []
            current_bucket = bucket

        current_batch.append((idx, m))

    if current_batch:
        batches.append(current_batch)

    return batches


async def _try_send_file_id(
    bot: Bot,
    chat_id: int,
    media_obj: dict,
    caption: str,
) -> tuple[int | None, list[str]]:
    """
    Try each file_id until one succeeds.
    Returns (message_id, failed_file_ids).
    Returns (None, all_file_ids) if all fail.
    """
    file_type = media_obj.get("file_type", "document")
    file_ids: list[str] = list(media_obj.get("file_ids", []))
    failed: list[str] = []

    for fid in file_ids:
        try:
            if file_type == "video":
                msg = await bot.send_video(chat_id=chat_id, video=fid, caption=caption, parse_mode="HTML")
            elif file_type == "audio":
                msg = await bot.send_audio(chat_id=chat_id, audio=fid, caption=caption, parse_mode="HTML")
            elif file_type == "photo":
                msg = await bot.send_photo(chat_id=chat_id, photo=fid, caption=caption, parse_mode="HTML")
            else:
                msg = await bot.send_document(chat_id=chat_id, document=fid, caption=caption, parse_mode="HTML")
            return msg.message_id, failed
        except TelegramError as e:
            logger.warning("file_id %s failed: %s — trying next", fid, e)
            failed.append(fid)

    return None, file_ids  # all failed


async def _send_album_batch(
    bot: Bot,
    chat_id: int,
    batch: list[tuple[int, dict]],
    title: str,
) -> tuple[list[int], list[tuple[int, str]]]:
    """
    Send one album batch (all same bucket type, ≤10 items).
    Falls back to individual sends if album fails.
    Returns (sent_message_ids, [(media_idx, invalid_file_id), ...])
    """
    invalid: list[tuple[int, str]] = []
    sent_ids: list[int] = []

    # Build InputMedia — use first file_id per media entry
    input_media = []
    meta: list[tuple[int, str]] = []  # (original media_idx, file_id used)

    for i, (orig_idx, m) in enumerate(batch):
        fids = m.get("file_ids", [])
        if not fids:
            continue
        fid = fids[0]
        cap = f"🎬 <b>{title}</b>" if i == 0 else ""
        input_media.append(_build_input_media(fid, m.get("file_type", "document"), cap))
        meta.append((orig_idx, fid))

    if not input_media:
        return [], []

    # Try sending as album
    if len(input_media) > 1:
        try:
            messages = await bot.send_media_group(chat_id=chat_id, media=input_media)
            sent_ids = [msg.message_id for msg in messages]
            logger.info("Album sent: %d items", len(sent_ids))
            return sent_ids, invalid
        except TelegramError as e:
            logger.warning("Album send failed (%s) — falling back to individual sends", e)

    # Fallback: send individually
    for orig_idx, m in batch:
        part_label = f" | Part {m['part']}" if m.get("part") is not None else ""
        caption = f"🎬 <b>{title}{part_label}</b>"
        msg_id, failed_fids = await _try_send_file_id(bot, chat_id, m, caption)
        if msg_id:
            sent_ids.append(msg_id)
        # Mark failed file_ids for cleanup
        for fid in failed_fids:
            if fid not in m.get("file_ids", [])[1:]:  # skip valid ones
                invalid.append((orig_idx, fid))
        if msg_id is None:
            logger.error("All file_ids failed for media idx %d", orig_idx)
            # Mark ALL as invalid for cleanup
            for fid in m.get("file_ids", []):
                invalid.append((orig_idx, fid))

    return sent_ids, invalid


async def deliver_file(
    bot: Bot,
    chat_id: int,
    file_doc: dict,
    db,
    auto_delete_minutes: int = 0,
) -> list[int]:
    """
    Deliver all media in file_doc to chat_id.
    - Groups into valid Telegram album batches automatically
    - Falls back to individual sends if album fails
    - Cleans up invalid file_ids from DB
    - Queues auto-delete if configured
    """
    unique_id: str = file_doc["unique_id"]
    title: str     = file_doc.get("title", unique_id) or unique_id
    media_list     = _sort_media(file_doc.get("media", []))

    if not media_list:
        raise ValueError(f"No media found for file {unique_id}")

    all_sent_ids: list[int] = []
    all_invalid:  list[tuple[int, str]] = []

    # Split into valid album batches
    batches = _split_into_album_batches(media_list)
    logger.info(
        "Delivering %s: %d media item(s) in %d batch(es)",
        unique_id, len(media_list), len(batches)
    )

    for batch in batches:
        sent_ids, invalid = await _send_album_batch(bot, chat_id, batch, title)
        all_sent_ids.extend(sent_ids)
        all_invalid.extend(invalid)

    # Clean up invalid file_ids from DB
    for media_idx, fid in all_invalid:
        db.remove_invalid_file_id(unique_id, media_idx, fid)

    if all_sent_ids:
        db.increment_views(unique_id)

    # Queue auto-delete
    if auto_delete_minutes > 0 and all_sent_ids:
        delete_at = datetime.now(UTC) + timedelta(minutes=auto_delete_minutes)
        db.queue_auto_delete(chat_id, all_sent_ids, delete_at)

    return all_sent_ids
