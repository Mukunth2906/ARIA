"""
nodes/confidence.py
confidence_router   — decides: proceed / trigger RAG / ask user
clarify_response    — builds a helpful clarification message
"""
from backend.state import AgentState

CONFIDENCE_THRESHOLD = 0.60
MAX_VAGUE_ATTEMPTS   = 2


def confidence_router(state: AgentState) -> str:
    """
    Conditional edge function.
    Returns one of:
      "proceed"   → move to verification chain
      "rag"       → try selective RAG then re-parse
      "clarify"   → ask user to rephrase
    """
    confidence = state.get("confidence", 0.0)

    if confidence >= CONFIDENCE_THRESHOLD:
        return "proceed"

    attempts = state.get("vague_attempt_count", 0)
    if attempts < MAX_VAGUE_ATTEMPTS:
        return "rag"

    return "clarify"


def clarify_response_node(state: AgentState) -> dict:
    """
    Terminal node — builds a reply asking the user to rephrase.
    """
    intent = state.get("intent", "unknown")
    reason = state.get("ambiguity_reason", "Your request was unclear.")

    reply = (
        f"I'm not quite sure what you meant. Here's what I understood:\n"
        f"• Possible intent: **{intent}**\n"
        f"• Unclear because: {reason}\n\n"
        f"Could you please clarify:\n"
        f"1. Who should this go to?\n"
        f"2. What should it say or do?"
    )

    return {
        "assistant_reply":    reply,
        "vague_attempt_count": 0,   # reset for next attempt
    }
