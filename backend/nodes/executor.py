"""
nodes/executor.py
execute_send_node — sends via Gmail API and creates Google Calendar events after all gates pass.
"""
import logging
from backend.state import AgentState
from backend.utils.gmail_client import send_email
from backend.utils.calendar_client import create_event

logger = logging.getLogger(__name__)


def execute_send_node(state: AgentState) -> dict:
    if not state.get("cleared_to_send"):
        return {
            "send_success": False,
            "block_reason": "Attempted send without clearance — blocked.",
        }

    results = {
        "send_success": False,
        "calendar_success": False,
        "gmail_message_id": "",
        "calendar_event_id": "",
    }

    # ── 1. Dispatch Email (if recipient and body exist) ───────────────────────
    if state.get("recipient_email") and state.get("body_draft"):
        try:
            message_id = send_email(
                to=state["recipient_email"],
                subject=state["subject"],
                body=state["body_draft"],
            )
            results["send_success"] = True
            results["gmail_message_id"] = message_id
        except Exception as e:
            logger.warning(f"Gmail send failed: {e}")
            results["block_reason"] = f"Gmail API error: {e}"

    # ── 2. Create Calendar Event (if meeting requested) ───────────────────────
    if state.get("calendar_event_needed"):
        try:
            title = state.get("calendar_event_title") or state.get("subject") or "Meeting"
            start_time = state.get("calendar_start_time")
            end_time = state.get("calendar_end_time")
            attendees = [state["recipient_email"]] if state.get("recipient_email") else None

            if start_time and end_time:
                event_id = create_event(
                    summary=title,
                    start_time=start_time,
                    end_time=end_time,
                    description=state.get("body_draft", ""),
                    attendees=attendees,
                    reminder_minutes=10,
                )
                results["calendar_success"] = True
                results["calendar_event_id"] = event_id
        except Exception as e:
            logger.warning(f"Calendar creation error: {e}")
            results["calendar_error"] = str(e)

    # Consider action successful if at least one succeeded
    if results["send_success"] or results["calendar_success"]:
        results["send_success"] = True
    else:
        results["send_success"] = False
        if not results.get("block_reason"):
            results["block_reason"] = "Both email dispatch and calendar creation failed."

    return results
