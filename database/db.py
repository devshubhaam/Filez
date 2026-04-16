"""
Database layer — all MongoDB operations for the file-sharing bot.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from pymongo import MongoClient, ASCENDING, DESCENDING
from pymongo.collection import Collection
from pymongo.database import Database as MongoDatabase

logger = logging.getLogger(__name__)

UTC = timezone.utc


def _now() -> datetime:
    return datetime.now(UTC)


class Database:
    """Wraps all MongoDB collections and exposes typed helper methods."""

    def __init__(self, mongo_uri: str, db_name: str) -> None:
        self.client = MongoClient(mongo_uri, serverSelectionTimeoutMS=5000)
        self.db: MongoDatabase = self.client[db_name]

        # Collections
        self.users: Collection = self.db["users"]
        self.files: Collection = self.db["files"]
        self.verified: Collection = self.db["verified"]
        self.payments: Collection = self.db["payments"]
        self.premium: Collection = self.db["premium"]
        self.referrals: Collection = self.db["referrals"]
        self.rate_limits: Collection = self.db["rate_limits"]
        self.banned: Collection = self.db["banned"]
        self.analytics: Collection = self.db["analytics"]
        self.settings: Collection = self.db["settings"]
        self.auto_delete_queue: Collection = self.db["auto_delete_queue"]

        self._ensure_indexes()
        logger.info("Database connected: %s / %s", mongo_uri[:30], db_name)

    # ── Indexes ──────────────────────────────────────────────────────────

    def _ensure_indexes(self) -> None:
        self.users.create_index("user_id", unique=True)
        self.files.create_index("unique_id", unique=True)
        self.verified.create_index("user_id")
        self.verified.create_index("expires_at", expireAfterSeconds=0)  # TTL
        self.payments.create_index("utr", unique=True)
        self.payments.create_index("user_id")
        self.premium.create_index("user_id", unique=True)
        self.referrals.create_index([("referrer_id", ASCENDING), ("referee_id", ASCENDING)], unique=True)
        self.rate_limits.create_index("user_id")
        self.rate_limits.create_index("window_start", expireAfterSeconds=120)
        self.banned.create_index("user_id", unique=True)
        self.auto_delete_queue.create_index("delete_at", expireAfterSeconds=0)

    # ══════════════════════════════════════════════════════════════════════
    # USER
    # ══════════════════════════════════════════════════════════════════════

    def upsert_user(self, user_id: int, first_name: str, username: str | None = None) -> None:
        now = _now()
        self.users.update_one(
            {"user_id": user_id},
            {
                "$set": {"last_seen": now, "first_name": first_name, "username": username},
                "$setOnInsert": {"first_seen": now},
            },
            upsert=True,
        )

    def get_user(self, user_id: int) -> dict | None:
        return self.users.find_one({"user_id": user_id})

    def total_users(self) -> int:
        return self.users.count_documents({})

    def all_user_ids(self) -> list[int]:
        return [u["user_id"] for u in self.users.find({}, {"user_id": 1})]

    # ══════════════════════════════════════════════════════════════════════
    # BAN
    # ══════════════════════════════════════════════════════════════════════

    def ban_user(self, user_id: int, reason: str = "") -> None:
        self.banned.update_one(
            {"user_id": user_id},
            {"$set": {"reason": reason, "banned_at": _now()}},
            upsert=True,
        )

    def unban_user(self, user_id: int) -> None:
        self.banned.delete_one({"user_id": user_id})

    def is_banned(self, user_id: int) -> bool:
        return self.banned.count_documents({"user_id": user_id}) > 0

    # ══════════════════════════════════════════════════════════════════════
    # RATE LIMITING
    # ══════════════════════════════════════════════════════════════════════

    def check_rate_limit(self, user_id: int, limit: int, window_seconds: int) -> tuple[bool, int]:
        """Returns (allowed, current_count). Increments counter."""
        now = _now()
        window_start = now - timedelta(seconds=window_seconds)

        doc = self.rate_limits.find_one_and_update(
            {"user_id": user_id, "window_start": {"$gte": window_start}},
            {"$inc": {"count": 1}, "$setOnInsert": {"window_start": now}},
            upsert=True,
            return_document=True,
        )
        count = doc["count"] if doc else 1
        return count <= limit, count

    def get_violation_count(self, user_id: int) -> int:
        doc = self.users.find_one({"user_id": user_id}, {"violations": 1})
        return (doc or {}).get("violations", 0)

    def increment_violation(self, user_id: int) -> int:
        result = self.users.find_one_and_update(
            {"user_id": user_id},
            {"$inc": {"violations": 1}},
            return_document=True,
        )
        return (result or {}).get("violations", 1)

    # ══════════════════════════════════════════════════════════════════════
    # FILES
    # ══════════════════════════════════════════════════════════════════════

    def get_file(self, unique_id: str) -> dict | None:
        return self.files.find_one({"unique_id": unique_id})

    def upsert_file_media(
        self,
        unique_id: str,
        file_id: str,
        file_type: str,
        part: int | None,
        title: str = "",
    ) -> None:
        now = _now()
        existing = self.files.find_one({"unique_id": unique_id})

        if not existing:
            # Create new file document
            media_obj = {
                "file_ids": [file_id],
                "file_type": file_type,
                "part": part,
            }
            self.files.insert_one(
                {
                    "unique_id": unique_id,
                    "title": title,
                    "media": [media_obj],
                    "views": 0,
                    "created_at": now,
                    "updated_at": now,
                }
            )
            return

        # Find matching part in existing media
        media_list: list[dict] = existing.get("media", [])
        target_idx = None
        for i, m in enumerate(media_list):
            if m.get("part") == part and m.get("file_type") == file_type:
                target_idx = i
                break

        if target_idx is not None:
            # Append file_id if not duplicate
            if file_id not in media_list[target_idx]["file_ids"]:
                self.files.update_one(
                    {"unique_id": unique_id},
                    {
                        "$push": {f"media.{target_idx}.file_ids": file_id},
                        "$set": {"updated_at": now},
                    },
                )
        else:
            # Add new media entry
            new_media = {"file_ids": [file_id], "file_type": file_type, "part": part}
            self.files.update_one(
                {"unique_id": unique_id},
                {"$push": {"media": new_media}, "$set": {"updated_at": now}},
            )

    def remove_invalid_file_id(self, unique_id: str, media_idx: int, file_id: str) -> None:
        self.files.update_one(
            {"unique_id": unique_id},
            {"$pull": {f"media.{media_idx}.file_ids": file_id}},
        )

    def increment_views(self, unique_id: str) -> None:
        self.files.update_one({"unique_id": unique_id}, {"$inc": {"views": 1}})
        self.analytics.update_one(
            {"_id": "global"}, {"$inc": {"total_views": 1}}, upsert=True
        )

    def delete_file(self, unique_id: str) -> bool:
        result = self.files.delete_one({"unique_id": unique_id})
        return result.deleted_count > 0

    def total_files(self) -> int:
        return self.files.count_documents({})

    # ══════════════════════════════════════════════════════════════════════
    # VERIFICATION  (24-hour access)
    # ══════════════════════════════════════════════════════════════════════

    def verify_user(self, user_id: int, hours: int = 24) -> None:
        expires = _now() + timedelta(hours=hours)
        self.verified.update_one(
            {"user_id": user_id},
            {"$set": {"verified_at": _now(), "expires_at": expires}},
            upsert=True,
        )

    def is_verified(self, user_id: int) -> bool:
        doc = self.verified.find_one({"user_id": user_id})
        if not doc:
            return False
        return doc["expires_at"].replace(tzinfo=UTC) > _now()

    def cleanup_expired_verifications(self) -> int:
        # MongoDB TTL index handles this; this is a manual fallback
        result = self.verified.delete_many({"expires_at": {"$lt": _now()}})
        return result.deleted_count

    # ══════════════════════════════════════════════════════════════════════
    # PREMIUM
    # ══════════════════════════════════════════════════════════════════════

    def is_premium(self, user_id: int) -> bool:
        doc = self.premium.find_one({"user_id": user_id})
        if not doc:
            return False
        return doc["expires_at"].replace(tzinfo=UTC) > _now()

    def grant_premium(self, user_id: int, days: int) -> datetime:
        now = _now()
        existing = self.premium.find_one({"user_id": user_id})
        if existing and existing["expires_at"].replace(tzinfo=UTC) > now:
            # Extend existing plan
            new_expiry = existing["expires_at"].replace(tzinfo=UTC) + timedelta(days=days)
        else:
            new_expiry = now + timedelta(days=days)

        self.premium.update_one(
            {"user_id": user_id},
            {"$set": {"expires_at": new_expiry, "granted_at": now}},
            upsert=True,
        )
        return new_expiry

    def get_premium_expiry(self, user_id: int) -> datetime | None:
        doc = self.premium.find_one({"user_id": user_id})
        if doc:
            return doc["expires_at"].replace(tzinfo=UTC)
        return None

    # ══════════════════════════════════════════════════════════════════════
    # PAYMENTS
    # ══════════════════════════════════════════════════════════════════════

    def create_payment(self, user_id: int, utr: str, plan: str) -> bool:
        try:
            self.payments.insert_one(
                {
                    "user_id": user_id,
                    "utr": utr,
                    "plan": plan,
                    "status": "pending",
                    "created_at": _now(),
                }
            )
            self.analytics.update_one(
                {"_id": "global"}, {"$inc": {"total_payments_pending": 1}}, upsert=True
            )
            return True
        except Exception:
            return False  # Duplicate UTR

    def get_payment(self, utr: str) -> dict | None:
        return self.payments.find_one({"utr": utr})

    def get_payment_by_id(self, payment_id: str) -> dict | None:
        from bson import ObjectId
        try:
            return self.payments.find_one({"_id": ObjectId(payment_id)})
        except Exception:
            return None

    def update_payment_status(self, utr: str, status: str) -> None:
        self.payments.update_one(
            {"utr": utr},
            {"$set": {"status": status, "processed_at": _now()}},
        )

    def get_pending_payments(self) -> list[dict]:
        return list(self.payments.find({"status": "pending"}).sort("created_at", ASCENDING))

    # ══════════════════════════════════════════════════════════════════════
    # REFERRALS
    # ══════════════════════════════════════════════════════════════════════

    def record_referral(self, referrer_id: int, referee_id: int) -> bool:
        """Returns True if this is a new referral."""
        if referrer_id == referee_id:
            return False
        try:
            self.referrals.insert_one(
                {
                    "referrer_id": referrer_id,
                    "referee_id": referee_id,
                    "rewarded": False,
                    "created_at": _now(),
                }
            )
            return True
        except Exception:
            return False

    def reward_referrer_if_eligible(self, referee_id: int, verify_hours: int) -> int | None:
        """
        If referee just verified, find their referrer and grant verify_hours to them.
        Returns referrer_id if rewarded, else None.
        """
        doc = self.referrals.find_one({"referee_id": referee_id, "rewarded": False})
        if not doc:
            return None
        referrer_id = doc["referrer_id"]
        self.verify_user(referrer_id, verify_hours)
        self.referrals.update_one(
            {"_id": doc["_id"]}, {"$set": {"rewarded": True, "rewarded_at": _now()}}
        )
        return referrer_id

    def get_referral_count(self, referrer_id: int) -> int:
        return self.referrals.count_documents({"referrer_id": referrer_id})

    # ══════════════════════════════════════════════════════════════════════
    # ANALYTICS
    # ══════════════════════════════════════════════════════════════════════

    def get_analytics(self) -> dict:
        doc = self.analytics.find_one({"_id": "global"}) or {}
        return {
            "total_users": self.total_users(),
            "total_files": self.total_files(),
            "total_views": doc.get("total_views", 0),
            "shortlink_clicks": doc.get("shortlink_clicks", 0),
            "total_payments_pending": doc.get("total_payments_pending", 0),
        }

    def track_shortlink_click(self) -> None:
        self.analytics.update_one(
            {"_id": "global"}, {"$inc": {"shortlink_clicks": 1}}, upsert=True
        )

    # ══════════════════════════════════════════════════════════════════════
    # SETTINGS
    # ══════════════════════════════════════════════════════════════════════

    def get_setting(self, key: str, default=None):
        doc = self.settings.find_one({"_id": key})
        return doc["value"] if doc else default

    def set_setting(self, key: str, value) -> None:
        self.settings.update_one(
            {"_id": key}, {"$set": {"value": value}}, upsert=True
        )

    # ══════════════════════════════════════════════════════════════════════
    # AUTO-DELETE QUEUE
    # ══════════════════════════════════════════════════════════════════════

    def queue_auto_delete(
        self,
        chat_id: int,
        message_ids: list[int],
        delete_at: datetime,
    ) -> None:
        self.auto_delete_queue.insert_one(
            {"chat_id": chat_id, "message_ids": message_ids, "delete_at": delete_at}
        )

    def get_due_deletions(self) -> list[dict]:
        return list(self.auto_delete_queue.find({"delete_at": {"$lte": _now()}}))

    def remove_delete_task(self, task_id) -> None:
        self.auto_delete_queue.delete_one({"_id": task_id})
