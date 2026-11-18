"""
nodes/rag.py
Selective Persistent RAG node — activated when confidence < 0.60.
Uses ChromaDB PersistentClient (via backend.utils.vector_store) with:
  - Per-user collection + metadata isolation
  - Metadata filtering (doc_type, recipient_email, timestamp / retention TTL)
  - Explicit source attribution (tracks which stored chunks grounded the resolution)
"""
import json
import logging
from typing import List, Optional

from backend.state import AgentState
from backend.utils.llm import get_llm
from backend.utils.vector_store import query_context
from backend.profile.schema import UserProfile
from backend.profile.summarizer import build_context_bundle

logger = logging.getLogger(__name__)


# ── RAG boost prompt with explicit citation instructions ─────────────────────

RAG_BOOST_PROMPT = """
You are resolving ambiguity in a user's message using retrieved historical context.

User message: "{user_input}"
Profile context:
{profile_context}

Retrieved historical context (each item has a SOURCE tag):
{retrieved_chunks}

Instructions:
1. Use the retrieved sources to resolve missing recipients, email addresses, subjects, or meeting details.
2. Only rely on facts actually present in the profile or retrieved sources — never invent emails or facts.
3. Cite which SOURCE tags (e.g. ["SOURCE_1"]) supported your resolution in "cited_source_ids".

Return JSON only — no prose, no markdown fences:
{{
  "intent": "send_email | draft_email | schedule_event | search_email | read_email | find_contact | general_query | unknown",
  "confidence": <0.0-1.0>,
  "recipient_name":  "<if resolved>",
  "recipient_email": "<if resolved>",
  "subject_hint":    "<if resolved>",
  "body_hint":       "<if resolved>",
  "cited_source_ids": ["SOURCE_1"],
  "attribution_summary": "<brief sentence citing which stored context resolved the ambiguity, or empty>",
  "ambiguity_reason": "<if still unclear>"
}}
"""


def _infer_doc_types(intent: str, user_input: str) -> Optional[List[str]]:
    """Select metadata doc_type filters based on intent and query cues."""
    lower = (user_input or "").lower()
    if intent == "schedule_event" or any(w in lower for w in ("meeting", "calendar", "schedule", "call", "sync")):
        return ["calendar_event", "sent_email", "contact_note", "session_summary"]
    if intent == "find_contact":
        return ["contact_note", "sent_email", "session_summary"]
    if intent in ("send_email", "draft_email", "search_email", "read_email"):
        return ["sent_email", "contact_note", "session_summary"]
    return None  # No doc_type restriction when intent is completely ambiguous


def _format_sources_for_prompt(hits: List[dict]) -> str:
    if not hits:
        return "No relevant past context found."
    lines = []
    for idx, hit in enumerate(hits, start=1):
        tag = f"SOURCE_{idx}"
        label = hit.get("source_label", hit.get("doc_id", "unknown"))
        doc_type = hit.get("doc_type", "unknown")
        ts = hit.get("timestamp_iso", "")
        sim = hit.get("similarity", 0.0)
        lines.append(
            f"[{tag}] ({doc_type} | {ts} | relevance={sim:.2f}) {label}\n"
            f"  Content: {hit.get('document', '')}"
        )
    return "\n\n".join(lines)


def selective_rag_node(state: AgentState) -> dict:
    llm = get_llm()
    user_input = state.get("original_input", "")
    user_id = state.get("user_id", "default")
    intent = state.get("intent", "unknown")
    known_email = (state.get("recipient_email") or "").strip().lower()

    profile_dict = state.get("profile", {})
    profile = UserProfile.from_dict(profile_dict) if profile_dict else UserProfile(user_id=user_id)
    profile_ctx = build_context_bundle(profile)

    doc_types = _infer_doc_types(intent, user_input)

    # ── Metadata-filtered vector retrieval (user_id + doc_type + retention TTL) ─
    hits: List[dict] = []
    try:
        # If recipient email is already known, try targeted lookup first, then widen
        if known_email:
            hits = query_context(
                user_id=user_id,
                query_text=user_input,
                n_results=3,
                doc_types=doc_types,
                recipient_email=known_email,
                max_age_days=profile.rag_retention_days,
                exclude_expired=True,
            )
        if not hits:
            hits = query_context(
                user_id=user_id,
                query_text=user_input,
                n_results=3,
                doc_types=doc_types,
                max_age_days=profile.rag_retention_days,
                exclude_expired=True,
            )
    except Exception as e:
        logger.warning(f"Selective RAG query failed: {e}")
        hits = []

    formatted_chunks = _format_sources_for_prompt(hits)

    response = llm.invoke(RAG_BOOST_PROMPT.format(
        user_input=user_input,
        profile_context=profile_ctx,
        retrieved_chunks=formatted_chunks,
    ))
    text = response.content.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    text = text.strip()

    parsed = json.loads(text)
    new_attempts = state.get("vague_attempt_count", 0) + 1

    # ── Map cited SOURCE_N tags back to concrete source records ───────────────
    tag_map = {f"SOURCE_{idx}": hit for idx, hit in enumerate(hits, start=1)}
    cited_tags = parsed.get("cited_source_ids") or []
    attributed_sources = []
    for tag in cited_tags:
        if tag in tag_map:
            src = dict(tag_map[tag])
            src["cited"] = True
            src["citation_tag"] = tag
            attributed_sources.append(src)

    # If the LLM used retrieved context without explicit tags, still expose top hits for transparency
    if not attributed_sources and hits:
        for idx, hit in enumerate(hits, start=1):
            src = dict(hit)
            src["cited"] = False
            src["citation_tag"] = f"SOURCE_{idx}"
            attributed_sources.append(src)

    attribution_summary = (parsed.get("attribution_summary") or "").strip()
    if not attribution_summary and attributed_sources:
        labels = [s.get("source_label", s.get("doc_id", "")) for s in attributed_sources[:2]]
        attribution_summary = f"Grounded using stored context: {'; '.join(labels)}."

    return {
        "intent":              parsed.get("intent", state.get("intent", "unknown")),
        "confidence":          float(parsed.get("confidence", 0.5)),
        "ambiguity_reason":    parsed.get("ambiguity_reason", ""),
        "recipient_name":      parsed.get("recipient_name", "") or state.get("recipient_name", ""),
        "recipient_email":     parsed.get("recipient_email", "") or state.get("recipient_email", ""),
        "subject_hint":        parsed.get("subject_hint", "") or state.get("subject_hint", ""),
        "body_hint":           parsed.get("body_hint", "") or state.get("body_hint", ""),
        "rag_sources":         attributed_sources,
        "rag_attribution":     attribution_summary,
        "vague_attempt_count": new_attempts,
    }
