"""
nodes/profile.py
profile_loader_node   — loads profile from DB at session start.
profile_updater_node  — updates + persists profile and selectively indexes
                        consented, PII-clean session context into persistent ChromaDB.
"""
import logging

from backend.state import AgentState
from backend.profile.schema import UserProfile
from backend.profile.updater import update_profile_post_session, extract_session_observations
from backend.utils.db import load_profile, save_profile
from backend.utils.vector_store import upsert_context, purge_expired_context

logger = logging.getLogger(__name__)


def profile_loader_node(state: AgentState) -> dict:
    """Load profile from MongoDB / local JSON at session start."""
    user_id = state.get("user_id", "default")
    profile = load_profile(user_id)
    # Respect explicit per-request rag_consent override if provided, else use profile setting
    rag_consent = state["rag_consent"] if "rag_consent" in state and state["rag_consent"] is not None else profile.rag_consent
    return {
        "profile":     profile.to_dict(),
        "rag_consent": bool(rag_consent),
    }


def _index_session_to_rag(state: AgentState, profile: UserProfile, observations: dict) -> list:
    """
    Selectively ingest high-signal, PII-clean, user-consented context into ChromaDB.
    Never indexes blocked, cancelled, or PII-flagged content.
    """
    user_id = state.get("user_id", profile.user_id or "default")
    consent = bool(state.get("rag_consent", profile.rag_consent))
    retention_days = profile.rag_retention_days

    # Enforce privacy & completion gates before indexing anything
    if not consent:
        return []
    if state.get("blocked") or state.get("cancelled"):
        return []
    if not (state.get("send_success") or state.get("calendar_success")):
        return []
    if not state.get("pii_clean", False) or state.get("pii_warning"):
        return []

    indexed_ids = []
    thread_id = state.get("thread_id", "")
    recipient_name = state.get("recipient_name", "")
    recipient_email = state.get("recipient_email", "")
    subject = state.get("subject", "")
    body_snippet = (state.get("body_draft", "") or "").strip()[:400]

    # 1. Index sent email summary (compact, grounded contact + topic record)
    if state.get("send_success") and recipient_email and subject:
        email_doc = (
            f"Sent {state.get('tone', 'formal')} email to {recipient_name or recipient_email} "
            f"<{recipient_email}>. Subject: {subject}. Summary: {body_snippet}"
        )
        res = upsert_context(
            user_id=user_id,
            text=email_doc,
            doc_type="sent_email",
            source_label=f"Sent email to {recipient_name or recipient_email} — {subject}",
            recipient_email=recipient_email,
            subject=subject,
            thread_id=thread_id,
            retention_days=retention_days,
            consent=consent,
            pii_clean=True,
        )
        if res.get("indexed") and res.get("doc_id"):
            indexed_ids.append(res["doc_id"])

    # 2. Index scheduled calendar event (if created)
    if state.get("calendar_success") and state.get("calendar_event_title"):
        cal_title = state.get("calendar_event_title", "Meeting")
        start_time = state.get("calendar_start_time", "")
        end_time = state.get("calendar_end_time", "")
        cal_doc = (
            f"Scheduled calendar event '{cal_title}' from {start_time} to {end_time}"
            + (f" with {recipient_name or recipient_email} <{recipient_email}>." if recipient_email else ".")
        )
        res = upsert_context(
            user_id=user_id,
            text=cal_doc,
            doc_type="calendar_event",
            source_label=f"Calendar event: {cal_title} ({start_time[:16]})",
            recipient_email=recipient_email,
            subject=cal_title,
            thread_id=thread_id,
            retention_days=retention_days,
            consent=consent,
            pii_clean=True,
        )
        if res.get("indexed") and res.get("doc_id"):
            indexed_ids.append(res["doc_id"])

    # 3. Index distilled session summary if observations were extracted
    if observations:
        summary_parts = [f"{k.replace('_section', '')}: {v}" for k, v in observations.items() if v]
        if summary_parts:
            res = upsert_context(
                user_id=user_id,
                text=" | ".join(summary_parts),
                doc_type="session_summary",
                source_label=f"Session summary ({subject or 'interaction'})",
                recipient_email=recipient_email,
                subject=subject,
                thread_id=thread_id,
                retention_days=retention_days,
                consent=consent,
                pii_clean=True,
            )
            if res.get("indexed") and res.get("doc_id"):
                indexed_ids.append(res["doc_id"])

    # Enforce retention TTL opportunistically
    try:
        purge_expired_context(user_id)
    except Exception as e:
        logger.debug(f"Expired RAG purge skipped: {e}")

    return indexed_ids


def profile_updater_node(state: AgentState) -> dict:
    """
    Extract observations from this session, rewrite relevant profile
    sections, persist back to DB, and selectively upsert consented context
    into persistent ChromaDB. Runs after audit_log.
    """
    profile_dict = state.get("profile", {})
    if not profile_dict:
        return {}

    profile = UserProfile.from_dict(profile_dict)
    observations = extract_session_observations(state)

    updates = {}

    if observations:
        try:
            updated = update_profile_post_session(profile, observations)
            save_profile(updated)
            profile = updated
            updates["profile"] = updated.to_dict()
        except Exception as e:
            logger.warning(f"Profile update skipped: {e}")

    # Selective, privacy-gated RAG ingestion
    try:
        indexed_ids = _index_session_to_rag(state, profile, observations)
        if indexed_ids:
            updates["rag_indexed_ids"] = indexed_ids
    except Exception as e:
        logger.warning(f"RAG ingestion skipped: {e}")

    return updates
