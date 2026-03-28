"""
nodes/executor.py
execute_send_node — sends via Gmail API after all gates pass.
"""
from backend.state import AgentState
from backend.utils.gmail_client import send_email


def execute_send_node(state: AgentState) -> dict:
    if not state.get("cleared_to_send"):
        return {
            "send_success": False,
            "block_reason": "Attempted send without clearance — blocked.",
        }

    try:
        message_id = send_email(
            to=state["recipient_email"],
            subject=state["subject"],
            body=state["body_draft"],
        )
        return {
            "send_success":     True,
            "gmail_message_id": message_id,
        }
    except Exception as e:
        return {
            "send_success": False,
            "block_reason": f"Gmail API error: {e}",
        }
