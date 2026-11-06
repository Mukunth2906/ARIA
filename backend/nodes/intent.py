"""
nodes/intent.py
parse_intent_node      — classifies intent + extracts ALL entities in ONE call
entity_extractor_node  — passthrough (kept for graph compatibility, no LLM call)

This saves 1 LLM call by combining intent + entity extraction.
"""
import json
import uuid
from datetime import datetime, timedelta

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

Do the following in ONE JSON response:
1. Classify the intent:
   - "send_email": Send an email (including meeting invitations/requests).
   - "draft_email": Create a draft only.
   - "schedule_event": Scheduling a calendar event or reminder.
2. Extract email entities (recipient_name, recipient_email, subject, polished body_draft).
3. If the request mentions scheduling or proposing a meeting, call, or appointment (e.g. "meet at 4pm", "call tomorrow at 10 AM"):
   - Set "calendar_event_needed": true
   - Set "calendar_title": "<e.g. Meeting with Priya>"
   - Set "meeting_date": "<YYYY-MM-DD or 'today' or 'tomorrow'>"
   - Set "meeting_time": "<HH:MM in 24-hr format, e.g. 16:00>"
   - Set "duration_minutes": 30
   Otherwise set "calendar_event_needed": false.

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
  "calendar_event_needed": <true or false>,
  "calendar_title": "<meeting title or empty>",
  "meeting_date": "<YYYY-MM-DD or today or tomorrow>",
  "meeting_time": "<HH:MM in 24hr or empty>",
  "duration_minutes": 30,
  "ambiguity_reason": "<if confidence < 0.6, explain what's unclear>"
}}
"""


def _build_event_timestamps(parsed: dict) -> tuple:
    now = datetime.now()
    date_str = str(parsed.get("meeting_date", "")).strip().lower()
    time_str = str(parsed.get("meeting_time", "16:00")).strip()

    target_date = now.date()
    if "tomorrow" in date_str:
        target_date = target_date + timedelta(days=1)
    elif date_str and date_str != "today":
        try:
            target_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        except Exception:
            target_date = now.date()

    hour, minute = 16, 0
    if time_str:
        try:
            t = time_str.lower().replace("am", "").replace("pm", "").strip()
            parts = t.split(":")
            h = int(parts[0])
            m = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0
            if "pm" in time_str.lower() and h < 12:
                h += 12
            elif "am" in time_str.lower() and h == 12:
                h = 0
            hour, minute = h, m
        except Exception:
            hour, minute = 16, 0

    duration = int(parsed.get("duration_minutes") or 30)
    start_dt = datetime.combine(target_date, datetime.min.time()).replace(hour=hour, minute=minute)
    end_dt = start_dt + timedelta(minutes=duration)

    tz_offset = "+05:30"
    start_iso = start_dt.strftime("%Y-%m-%dT%H:%M:%S") + tz_offset
    end_iso = end_dt.strftime("%Y-%m-%dT%H:%M:%S") + tz_offset
    return start_iso, end_iso


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

    cal_needed = bool(parsed.get("calendar_event_needed", False))
    if parsed.get("intent") == "schedule_event":
        cal_needed = True

    start_iso, end_iso = "", ""
    cal_title = ""
    if cal_needed:
        start_iso, end_iso = _build_event_timestamps(parsed)
        cal_title = parsed.get("calendar_title") or f"Meeting with {parsed.get('recipient_name') or 'Team'}"

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
        # Calendar Dual-Action details
        "calendar_event_needed": cal_needed,
        "calendar_event_title":  cal_title,
        "calendar_start_time":   start_iso,
        "calendar_end_time":     end_iso,
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
