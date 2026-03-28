"""
nodes/audit.py
audit_log_node — writes an immutable JSONL entry after every action.
Runs unconditionally (send, block, cancel).
"""
import json
import os
import datetime

from backend.state import AgentState

AUDIT_LOG_FILE = "aria_audit.jsonl"


def _next_id() -> int:
    if not os.path.exists(AUDIT_LOG_FILE):
        return 1
    with open(AUDIT_LOG_FILE, "r", encoding="utf-8") as f:
        return sum(1 for line in f if line.strip()) + 1


def audit_log_node(state: AgentState) -> dict:
    entry_id = _next_id()

    if state.get("send_success"):
        outcome = "SENT"
    elif state.get("cancelled"):
        outcome = "CANCELLED_BY_USER"
    elif state.get("blocked") or state.get("send_blocked"):
        outcome = "BLOCKED"
    elif state.get("assistant_reply"):
        outcome = "CLARIFICATION_REQUESTED"
    else:
        outcome = "UNKNOWN"

    entry = {
        "id":               entry_id,
        "timestamp":        datetime.datetime.utcnow().isoformat() + "Z",
        "thread_id":        state.get("thread_id", "N/A"),
        "user_id":          state.get("user_id", "N/A"),
        "intent":           state.get("intent", "N/A"),
        "confidence":       state.get("confidence"),
        "recipient":        state.get("recipient_email", "N/A"),
        "subject":          state.get("subject", "N/A"),
        "risk_level":       state.get("overall_risk", "UNKNOWN"),
        "pii_detected":     state.get("pii_warning", []),
        "policy_violations": state.get("policy_violations", []),
        "spam_score":       state.get("spam_score", 0),
        "confirmed_by":     "human" if state.get("confirmed") else "N/A",
        "outcome":          outcome,
        "block_reason":     state.get("block_reason") or state.get("validation_error"),
        "failed_checks":    state.get("failed_checks", []),
        "gmail_message_id": state.get("gmail_message_id"),
    }

    with open(AUDIT_LOG_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")

    return {"audit_logged": True, "audit_entry_id": entry_id}
