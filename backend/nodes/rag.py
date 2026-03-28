"""
nodes/rag.py
Selective RAG node — ONLY activated when confidence < 0.60.
Uses ChromaDB, lazy-loaded to avoid unnecessary startup cost.

Trigger conditions (only two):
  1. confidence < 0.60 and vague_attempt_count < MAX
  2. intent is explicit retrieval ("send the Q3 report to Priya")
"""
import json

from backend.state import AgentState
from backend.utils.llm import get_llm
from backend.profile.schema import UserProfile
from backend.profile.summarizer import build_context_bundle

# ── Lazy ChromaDB ─────────────────────────────────────────────────────────────
_chroma_client = None


def _get_chroma():
    global _chroma_client
    if _chroma_client is None:
        import chromadb
        _chroma_client = chromadb.Client()
    return _chroma_client


# ── RAG boost prompt ──────────────────────────────────────────────────────────

RAG_BOOST_PROMPT = """
You are resolving ambiguity in a user's message using retrieved context.

User message: "{user_input}"
Profile context:
{profile_context}

Retrieved similar past context:
{retrieved_chunks}

Re-parse the intent with this extra context.
Return JSON only — no prose, no markdown fences:
{{
  "intent": "send_email | draft_email | schedule_event | search_email | read_email | find_contact | general_query | unknown",
  "confidence": <0.0–1.0>,
  "recipient_name":  "<if resolved>",
  "recipient_email": "<if resolved>",
  "subject_hint":    "<if resolved>",
  "body_hint":       "<if resolved>",
  "ambiguity_reason": "<if still unclear>"
}}
"""


def selective_rag_node(state: AgentState) -> dict:
    llm = get_llm()
    user_input = state.get("original_input", "")
    user_id    = state.get("user_id", "default")

    profile_dict = state.get("profile", {})
    profile = UserProfile.from_dict(profile_dict) if profile_dict else UserProfile(user_id="?")
    profile_ctx = build_context_bundle(profile)

    # Retrieve from user-specific collection
    try:
        db = _get_chroma()
        collection = db.get_or_create_collection(f"user_{user_id}_context")
        results = collection.query(query_texts=[user_input], n_results=3)
        chunks = "\n".join(results["documents"][0]) if results.get("documents") and results["documents"][0] else "No past context found."
    except Exception:
        chunks = "No past context found."

    response = llm.invoke(RAG_BOOST_PROMPT.format(
        user_input=user_input,
        profile_context=profile_ctx,
        retrieved_chunks=chunks,
    ))
    text = response.content.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    text = text.strip()

    parsed = json.loads(text)
    new_attempts = state.get("vague_attempt_count", 0) + 1

    return {
        "intent":            parsed.get("intent", state.get("intent", "unknown")),
        "confidence":        float(parsed.get("confidence", 0.5)),
        "ambiguity_reason":  parsed.get("ambiguity_reason", ""),
        "recipient_name":    parsed.get("recipient_name", "") or state.get("recipient_name", ""),
        "recipient_email":   parsed.get("recipient_email", "") or state.get("recipient_email", ""),
        "subject_hint":      parsed.get("subject_hint", "") or state.get("subject_hint", ""),
        "body_hint":         parsed.get("body_hint", "") or state.get("body_hint", ""),
        "vague_attempt_count": new_attempts,
    }
