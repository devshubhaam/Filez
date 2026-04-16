"""
Shortlink service — supports Linkshortify and GPlink with automatic fallback.
"""

from __future__ import annotations

import logging
import urllib.parse

import httpx

logger = logging.getLogger(__name__)


class ShortlinkService:
    """
    Generates monetized shortlinks using configured providers.
    Falls back to secondary provider if primary fails.
    """

    PROVIDERS = {
        "linkshortify": _linkshortify_shorten,
        "gplink": _gplink_shorten,
    }

    def __init__(self, primary: str, api_key: str, api_key_2: str = "") -> None:
        self.primary = primary.lower()
        self.api_key = api_key
        self.api_key_2 = api_key_2
        self.fallback = "gplink" if self.primary == "linkshortify" else "linkshortify"

    async def shorten(self, url: str) -> str | None:
        """Try primary provider, then fallback. Returns short URL or None."""
        result = await _dispatch(self.primary, url, self.api_key)
        if result:
            return result
        logger.warning("Primary shortlink provider '%s' failed. Trying fallback.", self.primary)
        result = await _dispatch(self.fallback, url, self.api_key_2 or self.api_key)
        return result


# ── Provider implementations ─────────────────────────────────────────────────

async def _dispatch(provider: str, url: str, api_key: str) -> str | None:
    if not api_key:
        return None
    try:
        if provider == "linkshortify":
            return await _linkshortify_shorten(url, api_key)
        elif provider == "gplink":
            return await _gplink_shorten(url, api_key)
    except Exception as exc:
        logger.error("Shortlink provider '%s' error: %s", provider, exc)
    return None


async def _linkshortify_shorten(url: str, api_key: str) -> str | None:
    """
    Linkshortify API:
    GET https://linkshortify.com/api?api=<key>&url=<encoded_url>
    Response JSON: { "status": "success", "shortenedUrl": "https://..." }
    """
    endpoint = "https://linkshortify.com/api"
    params = {"api": api_key, "url": url}
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(endpoint, params=params)
        resp.raise_for_status()
        data = resp.json()
        if data.get("status") == "success":
            return data["shortenedUrl"]
    return None


async def _gplink_shorten(url: str, api_key: str) -> str | None:
    """
    GPlink API:
    GET https://gplinks.in/api?api=<key>&url=<encoded_url>
    Response JSON: { "status": "success", "shortenedUrl": "https://..." }
    """
    endpoint = "https://gplinks.in/api"
    params = {"api": api_key, "url": url}
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(endpoint, params=params)
        resp.raise_for_status()
        data = resp.json()
        if data.get("status") == "success":
            return data["shortenedUrl"]
    return None
