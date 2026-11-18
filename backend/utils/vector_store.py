"""
backend/utils/vector_store.py — Persistent, Privacy-Aware Vector Store for ARIA
Uses ChromaDB PersistentClient with:
  1. Disk persistence (CHROMA_PERSIST_DIR, default ./chroma_store)
  2. Strict per-user collection + metadata isolation
  3. Privacy gates (user consent required + PII/secret rejection)
  4. Metadata filtering (user_id, doc_type, recipient_email, timestamp / retention TTL)
  5. Source attribution metadata (source_label, timestamp_iso, similarity score)
  6. Retention purging and Right-to-be-Forgotten deletion APIs
"""
import hashlib
import logging
import os
import re
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

DEFAULT_PERSIST_DIR = os.getenv("CHROMA_PERSIST_DIR", "./chroma_store")
DEFAULT_RETENTION_DAYS = int(os.getenv("RAG_RETENTION_DAYS", "90"))

VALID_DOC_TYPES = {
    "sent_email",
    "calendar_event",
    "contact_note",
    "session_summary",
}

# Deterministic privacy/secret patterns that must NEVER be indexed into vector memory
_SECRET_PATTERNS = [
    ("api_key", re.compile(r"\b(?:sk-[A-Za-z0-9]{16,}|ghp_[A-Za-z0-9]{20,}|AIza[0-9A-Za-z\-_]{30,})\b")),
    ("password_assignment", re.compile(r"\b(?:password|passwd|pwd|secret|api_key)\s*[:=]\s*\S+", re.IGNORECASE)),
    ("credit_card", re.compile(r"\b(?:\d[ -]*?){13,16}\b")),
    ("ssn", re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),
    ("pan_card", re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b")),
    ("aadhaar", re.compile(r"\b\d{4}\s\d{4}\s\d{4}\b")),
    ("bearer_token", re.compile(r"\bBearer\s+[A-Za-z0-9\-._~+/]+=*\b", re.IGNORECASE)),
]

# Cache clients keyed by resolved persist_dir so tests can use isolated paths cleanly
_clients: Dict[str, Any] = {}


def _sanitize_user_id(user_id: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_-]", "_", (user_id or "default").strip())
    return cleaned[:48] or "default"


def _collection_name(user_id: str) -> str:
    # Chroma collection names must be 3-63 chars, alphanumeric / underscores / hyphens
    return f"user_{_sanitize_user_id(user_id)}_context"


def get_chroma_client(persist_dir: Optional[str] = None):
    """Return a lazy-loaded ChromaDB PersistentClient for the given storage directory."""
    target_dir = os.path.abspath(persist_dir or os.getenv("CHROMA_PERSIST_DIR", DEFAULT_PERSIST_DIR))
    if target_dir not in _clients:
        import chromadb
        os.makedirs(target_dir, exist_ok=True)
        _clients[target_dir] = chromadb.PersistentClient(path=target_dir)
        logger.info(f"Initialized ChromaDB PersistentClient at {target_dir}")
    return _clients[target_dir]


def reset_client_cache(persist_dir: Optional[str] = None) -> None:
    """Clear cached client handles (useful for persistence reload tests)."""
    if persist_dir:
        _clients.pop(os.path.abspath(persist_dir), None)
    else:
        _clients.clear()


def _get_user_collection(user_id: str, persist_dir: Optional[str] = None):
    client = get_chroma_client(persist_dir)
    return client.get_or_create_collection(
        name=_collection_name(user_id),
        metadata={"hnsw:space": "cosine", "user_id": user_id},
    )


def detect_sensitive_patterns(text: str) -> List[str]:
    """Deterministic local PII/secret check before vector ingestion."""
    found = []
    for label, pattern in _SECRET_PATTERNS:
        if pattern.search(text or ""):
            found.append(label)
    return found


def _make_doc_id(user_id: str, doc_type: str, unique_key: str) -> str:
    raw = f"{user_id}:{doc_type}:{unique_key}".encode("utf-8")
    digest = hashlib.sha256(raw).hexdigest()[:16]
    return f"{doc_type}_{digest}"


def upsert_context(
    user_id: str,
    text: str,
    doc_type: str,
    source_label: str,
    *,
    doc_id: Optional[str] = None,
    recipient_email: str = "",
    subject: str = "",
    thread_id: str = "",
    timestamp: Optional[int] = None,
    retention_days: int = DEFAULT_RETENTION_DAYS,
    consent: bool = True,
    pii_clean: bool = True,
    persist_dir: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Privacy-gated idempotent upsert into the user's persistent ChromaDB collection.

    Refuses to index if:
      - User has not granted consent (consent=False)
      - Upstream security scanner flagged PII (pii_clean=False)
      - Deterministic local secret scanner detects credentials/PII in text
    """
    if not consent:
        return {"indexed": False, "doc_id": None, "reason": "User has disabled RAG indexing consent."}

    cleaned_text = (text or "").strip()
    if not cleaned_text:
        return {"indexed": False, "doc_id": None, "reason": "Empty document text."}

    if not pii_clean:
        return {"indexed": False, "doc_id": None, "reason": "Skipped indexing: flagged by PII scanner."}

    detected_secrets = detect_sensitive_patterns(cleaned_text)
    if detected_secrets:
        return {
            "indexed": False,
            "doc_id": None,
            "reason": f"Skipped indexing: sensitive pattern detected ({', '.join(detected_secrets)}).",
        }

    safe_doc_type = doc_type if doc_type in VALID_DOC_TYPES else "session_summary"
    now_ts = int(timestamp if timestamp is not None else time.time())
    ttl_days = max(1, int(retention_days or DEFAULT_RETENTION_DAYS))
    expires_at = now_ts + (ttl_days * 86400)
    ts_iso = datetime.fromtimestamp(now_ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    final_doc_id = doc_id or _make_doc_id(user_id, safe_doc_type, thread_id or cleaned_text[:120])

    metadata = {
        "user_id":         user_id,
        "doc_type":        safe_doc_type,
        "source_label":    (source_label or safe_doc_type)[:160],
        "recipient_email": (recipient_email or "").strip().lower(),
        "subject":         (subject or "")[:160],
        "thread_id":       thread_id or "",
        "timestamp":       now_ts,
        "timestamp_iso":   ts_iso,
        "expires_at":      expires_at,
    }

    collection = _get_user_collection(user_id, persist_dir=persist_dir)
    collection.upsert(
        ids=[final_doc_id],
        documents=[cleaned_text],
        metadatas=[metadata],
    )
    logger.info(f"Indexed RAG doc '{final_doc_id}' ({safe_doc_type}) for user '{user_id}'.")

    return {
        "indexed": True,
        "doc_id": final_doc_id,
        "metadata": metadata,
    }


def query_context(
    user_id: str,
    query_text: str,
    *,
    n_results: int = 3,
    doc_types: Optional[List[str]] = None,
    recipient_email: Optional[str] = None,
    min_timestamp: Optional[int] = None,
    max_age_days: Optional[int] = None,
    exclude_expired: bool = True,
    min_similarity: float = 0.15,
    persist_dir: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Semantic vector search with strict user isolation and metadata filtering.
    Returns structured source records suitable for prompt grounding and citation.
    """
    if not (query_text or "").strip():
        return []

    collection = _get_user_collection(user_id, persist_dir=persist_dir)
    total_count = collection.count()
    if total_count == 0:
        return []

    now_ts = int(time.time())
    clauses: List[Dict[str, Any]] = [{"user_id": {"$eq": user_id}}]

    if doc_types:
        valid = [dt for dt in doc_types if dt in VALID_DOC_TYPES]
        if len(valid) == 1:
            clauses.append({"doc_type": {"$eq": valid[0]}})
        elif len(valid) > 1:
            clauses.append({"doc_type": {"$in": valid}})

    if recipient_email:
        clauses.append({"recipient_email": {"$eq": recipient_email.strip().lower()}})

    effective_min_ts = min_timestamp
    if max_age_days is not None:
        cutoff = now_ts - (int(max_age_days) * 86400)
        effective_min_ts = max(effective_min_ts, cutoff) if effective_min_ts is not None else cutoff

    if effective_min_ts is not None:
        clauses.append({"timestamp": {"$gte": int(effective_min_ts)}})

    if exclude_expired:
        clauses.append({"expires_at": {"$gte": now_ts}})

    where_filter: Dict[str, Any] = clauses[0] if len(clauses) == 1 else {"$and": clauses}

    # Cap n_results to the number of items matching the filter to prevent Chroma errors
    matching = collection.get(where=where_filter, include=[])
    available = len(matching.get("ids", []))
    if available == 0:
        return []

    k = min(max(1, n_results), available)

    raw = collection.query(
        query_texts=[query_text],
        n_results=k,
        where=where_filter,
        include=["documents", "metadatas", "distances"],
    )

    ids = (raw.get("ids") or [[]])[0]
    docs = (raw.get("documents") or [[]])[0]
    metas = (raw.get("metadatas") or [[]])[0]
    dists = (raw.get("distances") or [[]])[0]

    hits: List[Dict[str, Any]] = []
    for doc_id, doc_text, meta, dist in zip(ids, docs, metas, dists):
        # Cosine space: distance in [0, 2], similarity = 1 - distance
        similarity = round(max(0.0, 1.0 - float(dist)), 4)
        if similarity < min_similarity:
            continue
        meta = meta or {}
        hits.append({
            "doc_id":          doc_id,
            "document":        doc_text,
            "similarity":      similarity,
            "doc_type":        meta.get("doc_type", "unknown"),
            "source_label":    meta.get("source_label", doc_id),
            "recipient_email": meta.get("recipient_email", ""),
            "subject":         meta.get("subject", ""),
            "timestamp":       meta.get("timestamp", 0),
            "timestamp_iso":   meta.get("timestamp_iso", ""),
            "thread_id":       meta.get("thread_id", ""),
        })

    return hits


def list_user_context(
    user_id: str,
    *,
    doc_type: Optional[str] = None,
    limit: int = 50,
    persist_dir: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """List stored RAG documents for transparency and user management."""
    collection = _get_user_collection(user_id, persist_dir=persist_dir)
    if collection.count() == 0:
        return []

    clauses: List[Dict[str, Any]] = [{"user_id": {"$eq": user_id}}]
    if doc_type and doc_type in VALID_DOC_TYPES:
        clauses.append({"doc_type": {"$eq": doc_type}})

    where_filter: Dict[str, Any] = clauses[0] if len(clauses) == 1 else {"$and": clauses}
    raw = collection.get(where=where_filter, limit=limit, include=["documents", "metadatas"])

    items: List[Dict[str, Any]] = []
    for doc_id, doc_text, meta in zip(
        raw.get("ids", []), raw.get("documents", []), raw.get("metadatas", [])
    ):
        meta = meta or {}
        items.append({
            "doc_id":          doc_id,
            "document":        doc_text,
            "doc_type":        meta.get("doc_type", "unknown"),
            "source_label":    meta.get("source_label", doc_id),
            "recipient_email": meta.get("recipient_email", ""),
            "subject":         meta.get("subject", ""),
            "timestamp":       meta.get("timestamp", 0),
            "timestamp_iso":   meta.get("timestamp_iso", ""),
            "expires_at":      meta.get("expires_at", 0),
        })

    items.sort(key=lambda x: x.get("timestamp", 0), reverse=True)
    return items


def delete_context_item(
    user_id: str,
    doc_id: str,
    *,
    persist_dir: Optional[str] = None,
) -> bool:
    """Delete a specific document from a user's vector collection."""
    collection = _get_user_collection(user_id, persist_dir=persist_dir)
    existing = collection.get(ids=[doc_id], include=[])
    if not existing.get("ids"):
        return False
    collection.delete(ids=[doc_id])
    logger.info(f"Deleted RAG doc '{doc_id}' for user '{user_id}'.")
    return True


def delete_all_user_context(
    user_id: str,
    *,
    persist_dir: Optional[str] = None,
) -> int:
    """Right-to-be-Forgotten: delete all indexed vector memory for a user."""
    client = get_chroma_client(persist_dir)
    col_name = _collection_name(user_id)
    try:
        collection = client.get_collection(name=col_name)
        count = collection.count()
        client.delete_collection(name=col_name)
        logger.info(f"Wiped RAG collection '{col_name}' ({count} docs) for user '{user_id}'.")
        return count
    except Exception:
        return 0


def purge_expired_context(
    user_id: str,
    *,
    now_ts: Optional[int] = None,
    persist_dir: Optional[str] = None,
) -> int:
    """Remove all documents whose retention TTL (expires_at) has passed."""
    collection = _get_user_collection(user_id, persist_dir=persist_dir)
    if collection.count() == 0:
        return 0

    cutoff = int(now_ts if now_ts is not None else time.time())
    expired = collection.get(
        where={"$and": [{"user_id": {"$eq": user_id}}, {"expires_at": {"$lt": cutoff}}]},
        include=[],
    )
    expired_ids = expired.get("ids", [])
    if not expired_ids:
        return 0

    collection.delete(ids=expired_ids)
    logger.info(f"Purged {len(expired_ids)} expired RAG docs for user '{user_id}'.")
    return len(expired_ids)

