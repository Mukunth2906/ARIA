"""
Gate 6 — Final Safety Check
Last gate before execute_send.  Validates all upstream checks passed.
"""
from backend.state import AgentState

REQUIRED = {
    "recipient_validated": "Recipient was not validated",
    "confirmed":           "Human confirmation missing",
    "not_blocked":         "Action was blocked upstream",
    "risk_acceptable":     "Risk level too high",
    "pii_ok":              "PII issue not resolved",
}


def final_safety_check_node(state: AgentState) -> dict:
    checks = {
        "recipient_validated": state.get("recipient_validated", False),
        "confirmed":           state.get("confirmed", False),
        "not_blocked":         not state.get("blocked", False),
        "risk_acceptable":     state.get("overall_risk", "HIGH") in ("LOW", "MEDIUM"),
        "pii_ok":              state.get("pii_clean", False) or state.get("pii_warning_acknowledged", False),
    }
    failed = [REQUIRED[k] for k, v in checks.items() if not v]

    if failed:
        return {
            "cleared_to_send": False,
            "send_blocked": True,
            "failed_checks": failed,
            "block_reason": "Final safety: " + "; ".join(failed),
        }
    return {"cleared_to_send": True, "failed_checks": []}
