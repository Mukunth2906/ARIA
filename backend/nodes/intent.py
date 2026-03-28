"""
nodes/intent.py
parse_intent_node      — classifies intent + extracts ALL entities in ONE call
entity_extractor_node  — passthrough (kept for graph compatibility, no LLM call)

This saves 1 LLM call by combining intent + entity extraction.
"""
import json
import uuid

from backend.state import AgentState
from backend.utils.llm import get_llm
from backend.profile.schema import UserProfile
from backend.profile.summarizer import build_context_bundle

# ── Combined Intent + Entity Extraction (1 LLM call) ─────────────────────────

INTENT_AND_ENTITY_PROMPT = """
You are ARIA, an intelligent email and calendar assistant.

User profile context:
{profile_context}

User message: "{user_input}"

Do TWO things in one response:
1. Classify the intent
2. Extract ALL email entities and write a complete email body

Return JSON only — no prose, no markdown fences:
{{
  "intent": "send_email | draft_email | schedule_event | search_email | read_email | find_contact | general_query | unknown",
  "intent_description": "<one-sentence summary>",
  "confidence": <0.0-1.0>,
  "recipient_name":  "<full name or empty>",
  "recipient_email": "<email address or empty>",
  "subject":         "<email subject line>",
  "body_draft":      "<complete ready-to-send email body>",
  "tone":            "formal | casual | urgent",
  "ambiguity_reason": "<if confidence < 0.6, explain what's unclear>"
}}
"""


def parse_intent_node(state: AgentState) -> dict:
    llm = get_llm()
    user_input = state.get("original_input", "")

    profile_dict = state.get("profile", {})
    profile = UserProfile.from_dict(profile_dict) if profile_dict else UserProfile(user_id="?")
    profile_ctx = build_context_bundle(profile)

    response = llm.invoke(INTENT_AND_ENTITY_PROMPT.format(
        profile_context=profile_ctx,
        user_input=user_input,
    ))
    text = _strip_fences(response.content)
    parsed = json.loads(text)

    return {
        "intent":             parsed.get("intent", "unknown"),
        "intent_description": parsed.get("intent_description", ""),
        "confidence":         float(parsed.get("confidence", 0.5)),
        "ambiguity_reason":   parsed.get("ambiguity_reason", ""),
        "thread_id":          state.get("thread_id") or str(uuid.uuid4()),
        # Entities — extracted in the same call
        "recipient_name":     parsed.get("recipient_name", "") or state.get("recipient_name", ""),
        "recipient_email":    parsed.get("recipient_email", "") or state.get("recipient_email", ""),
        "subject":            parsed.get("subject", ""),
        "body_draft":         parsed.get("body_draft", ""),
        "tone":               parsed.get("tone", "formal"),
    }


def entity_extractor_node(state: AgentState) -> dict:
    """
    Passthrough — entities already extracted in parse_intent_node.
    Kept as a separate graph node so the confidence_router edge still works.
    """
    return {}


# ── Helper ────────────────────────────────────────────────────────────────────

def _strip_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    return text.strip()
