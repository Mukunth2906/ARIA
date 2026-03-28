"""
MongoDB Atlas connection + profile CRUD.
Falls back to a local JSON file if MONGO_URI is not set or connection fails.
"""
import json
import os
import logging
from datetime import datetime
from dotenv import load_dotenv

from backend.profile.schema import UserProfile

load_dotenv()

logger = logging.getLogger(__name__)

MONGO_URI = os.getenv("MONGO_URI")

# ── MongoDB path ─────────────────────────────────────────────────────────────
_db = None
_mongo_failed = False   # once it fails, stop retrying this session


def _get_collection():
    global _db, _mongo_failed
    if _db is not None:
        return _db
    if _mongo_failed:
        return None

    if MONGO_URI:
        try:
            from pymongo import MongoClient
            client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
            # Force a connection test
            client.admin.command("ping")
            _db = client["aria"]["profiles"]
            logger.info("Connected to MongoDB Atlas.")
            return _db
        except Exception as e:
            _mongo_failed = True
            logger.warning(f"MongoDB connection failed ({e}). Falling back to local JSON files.")
            return None

    return None  # no URI set → file-based


# ── File-based fallback ─────────────────────────────────────────────────────
LOCAL_PROFILE_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "profiles")


def _local_path(user_id: str) -> str:
    os.makedirs(LOCAL_PROFILE_DIR, exist_ok=True)
    return os.path.join(LOCAL_PROFILE_DIR, f"{user_id}.json")


# ── Public API ───────────────────────────────────────────────────────────────

def load_profile(user_id: str) -> UserProfile:
    """Load a profile from MongoDB or local JSON file."""
    col = _get_collection()

    if col is not None:
        try:
            doc = col.find_one({"user_id": user_id})
            if doc:
                doc.pop("_id", None)
                return UserProfile.from_dict(doc)
            return UserProfile(user_id=user_id)
        except Exception as e:
            logger.warning(f"MongoDB read failed ({e}). Falling back to local.")

    # File fallback
    path = _local_path(user_id)
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return UserProfile.from_dict(json.load(f))
    return UserProfile(user_id=user_id)


def save_profile(profile: UserProfile) -> None:
    """Persist a profile to MongoDB or local JSON file."""
    col = _get_collection()
    data = profile.to_dict()

    if col is not None:
        try:
            col.update_one(
                {"user_id": profile.user_id},
                {"$set": data},
                upsert=True,
            )
            return
        except Exception as e:
            logger.warning(f"MongoDB write failed ({e}). Saving locally.")

    # File fallback
    path = _local_path(profile.user_id)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, default=str)
