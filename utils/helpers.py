"""
Shared utility helpers.
"""

from __future__ import annotations

import re
import logging
import random
import string

from telegram import Bot
from telegram.error import TelegramError

logger = logging.getLogger(__name__)


# ── Caption parsing ───────────────────────────────────────────────────────────

_ID_RE = re.compile(r"\bID\s*:\s*(\S+)", re.IGNORECASE)
_PART_PATTERNS = [
    re.compile(r"\bpart\s*(\d+)\b", re.IGNORECASE),
    re.compile(r"\bep(?:isode)?\s*(\d+)\b", re.IGNORECASE),
    re.compile(r"\bp(\d+)\b", re.IGNORECASE),
    re.compile(r"^(\d+)$"),
]


def parse_caption(caption: str | None) -> tuple[str | None, int | None, str]:
    """
    Returns (unique_id | None, part | None, cleaned_title).
    unique_id  — extracted from "ID: xyz" in caption (or None → caller generates)
    part       — extracted part number (or None)
    title      — caption with ID tag stripped
    """
    if not caption:
        return None, None, ""

    uid: str | None = None
    m = _ID_RE.search(caption)
    if m:
        uid = m.group(1).strip()

    part: int | None = None
    for pat in _PART_PATTERNS:
        pm = pat.search(caption)
        if pm:
            part = int(pm.group(1))
            break

    # Strip ID tag from title
    title = _ID_RE.sub("", caption).strip(" -|:")
    return uid, part, title


def generate_unique_id(length: int = 8) -> str:
    chars = string.ascii_lowercase + string.digits
    return "".join(random.choices(chars, k=length))


# ── Force-join check ──────────────────────────────────────────────────────────

async def check_force_join(bot: Bot, user_id: int, channels: list[str]) -> list[str]:
    """
    Returns list of channel usernames the user has NOT joined.
    Accepts channel IDs (int str like "-100...") or usernames.
    """
    not_joined: list[str] = []
    for ch in channels:
        try:
            chat_id = int(ch) if ch.lstrip("-").isdigit() else f"@{ch}"
            member = await bot.get_chat_member(chat_id=chat_id, user_id=user_id)
            if member.status in ("left", "kicked"):
                not_joined.append(ch)
        except TelegramError as e:
            logger.warning("Force-join check error for %s: %s", ch, e)
    return not_joined


# ── Misc ──────────────────────────────────────────────────────────────────────

def format_timedelta(seconds: int) -> str:
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m {seconds % 60}s"
    h = seconds // 3600
    m = (seconds % 3600) // 60
    return f"{h}h {m}m"


def chunks(lst, n):
    for i in range(0, len(lst), n):
        yield lst[i : i + n]
