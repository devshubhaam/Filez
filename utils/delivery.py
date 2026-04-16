"""
File delivery — fail-safe, multi-file-id, album-aware sender.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from telegram import Bot, InputMediaVideo, InputMediaDocument, InputMediaAudio, InputMediaPhoto
from telegram.error import TelegramError

logger = logging.getLogger(__name__)
UTC = timezone.utc


def _sort_media(media_list: list[dict]) -> list[dict]:
    """Sort by part number (ascending). Entries with no part go last."""
    with_part = [m for m in media_list if m.get("part") is not None]
    without_part = [m for m in media_list if m.get("part") is None]
    with_part.sort(key=lambda m: m["part"])
    return with_part + without_part


def _build_input_media(file_id: str, file_type: str, caption: str = ""):
    if file_type == "video":
        return InputMediaVideo(media=file_id, caption=caption)
    elif file_type == "audio":
        return InputMediaAudio(media=file_id, caption=caption)
    elif file_type == "photo":
        return InputMediaPhoto(media=file_id, caption=caption)
    else:
        return InputMediaDocument(media=file_id, caption=caption)


async def _send_single(bot: Bot, chat_id: int, media_obj: dict, caption: str) -> list[int]:
    """
    Try each file_id in media_obj["file_ids"] until one succeeds.
    Returns list of sent message IDs.
    Raises RuntimeError if ALL file_ids fail.
    """
    file_type = media_obj.get("file_type", "document")
    file_ids: list[str] = list(media_obj.get("file_ids", []))
    failed: list[str] = []

    for fid in file_ids:
        try:
            if file_type == "video":
                msg = await bot.send_video(chat_id=chat_id, video=fid, caption=caption)
            elif file_type == "audio":
                msg = await bot.send_audio(chat_id=chat_id, audio=fid, caption=caption)
            elif file_type == "photo":
                msg = await bot.send_photo(chat_id=chat_id, photo=fid, caption=caption)
            else:
                msg = await bot.send_document(chat_id=chat_id, document=fid, caption=caption)
            return [msg.message_id], failed
        except TelegramError as e:
            logger.warning("file_id %s failed (%s), trying next.", fid, e)
            failed.append(fid)

    raise RuntimeError(f"All file_ids exhausted for media {media_obj}")


async def deliver_file(
    bot: Bot,
    chat_id: int,
    file_doc: dict,
    db,
    auto_delete_minutes: int = 0,
) -> list[int]:
    """
    Deliver all media in a file_doc to chat_id.
    Returns list of all sent message_ids.
    Cleans up invalid file_ids from DB.
    """
    unique_id: str = file_doc["unique_id"]
    title: str = file_doc.get("title", unique_id)
    media_list: list[dict] = _sort_media(file_doc.get("media", []))

    if not media_list:
        raise ValueError(f"No media in file {unique_id}")

    all_sent_ids: list[int] = []
    all_invalid: list[tuple[int, str]] = []  # (media_idx, file_id)

    # ── Album mode: batch up to 10 items of same type ───────────────────
    # We'll send each part individually for reliability; album only when
    # all items are the same type (photo or video) and ≤ 10
    can_album = (
        len(media_list) > 1
        and len(media_list) <= 10
        and len({m.get("file_type") for m in media_list}) == 1
        and media_list[0].get("file_type") in ("photo", "video")
    )

    if can_album:
        sent_ids, invalid = await _send_album(bot, chat_id, media_list, title, unique_id, db)
        all_sent_ids.extend(sent_ids)
        all_invalid.extend(invalid)
    else:
        for idx, media_obj in enumerate(media_list):
            part_label = f" | Part {media_obj['part']}" if media_obj.get("part") else ""
            caption = f"🎬 <b>{title}{part_label}</b>"
            try:
                sent_ids, invalid = await _send_single(bot, chat_id, media_obj, caption)
                all_sent_ids.extend(sent_ids)
                all_invalid.extend([(idx, fid) for fid in invalid])
            except RuntimeError:
                # Remove all invalid ids for this part
                for fid in media_obj.get("file_ids", []):
                    db.remove_invalid_file_id(unique_id, idx, fid)
                logger.error("Could not deliver part %s of %s", idx, unique_id)

    # Clean up invalid file_ids
    for media_idx, fid in all_invalid:
        db.remove_invalid_file_id(unique_id, media_idx, fid)

    db.increment_views(unique_id)

    # Queue auto-delete
    if auto_delete_minutes > 0 and all_sent_ids:
        delete_at = datetime.now(UTC) + timedelta(minutes=auto_delete_minutes)
        db.queue_auto_delete(chat_id, all_sent_ids, delete_at)

    return all_sent_ids


async def _send_album(
    bot: Bot,
    chat_id: int,
    media_list: list[dict],
    title: str,
    unique_id: str,
    db,
) -> tuple[list[int], list[tuple[int, str]]]:
    """Attempt to send as media group (album). Falls back to individual."""
    invalid: list[tuple[int, str]] = []
    sent_ids: list[int] = []

    # Build InputMedia list using first valid file_id per part
    input_media = []
    meta = []  # (media_idx, file_id)
    for idx, m in enumerate(media_list):
        fids = m.get("file_ids", [])
        if not fids:
            continue
        fid = fids[0]
        cap = f"🎬 <b>{title}</b>" if idx == 0 else ""
        input_media.append(_build_input_media(fid, m.get("file_type", "document"), cap))
        meta.append((idx, fid))

    if not input_media:
        return [], []

    try:
        messages = await bot.send_media_group(chat_id=chat_id, media=input_media)
        sent_ids = [m.message_id for m in messages]
        return sent_ids, invalid
    except TelegramError as e:
        logger.warning("Album send failed (%s), falling back to individual.", e)

    # Fallback: individual
    for idx, media_obj in enumerate(media_list):
        part_label = f" | Part {media_obj['part']}" if media_obj.get("part") else ""
        caption = f"🎬 <b>{title}{part_label}</b>"
        try:
            s_ids, inv = await _send_single(bot, chat_id, media_obj, caption)
            sent_ids.extend(s_ids)
            invalid.extend([(idx, fid) for fid in inv])
        except RuntimeError:
            for fid in media_obj.get("file_ids", []):
                db.remove_invalid_file_id(unique_id, idx, fid)

    return sent_ids, invalid
