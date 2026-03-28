"""
Gate 4 — Risk Scorer
Assigns LOW/MEDIUM/HIGH risk and an action policy.
"""
import json
from backend.state import AgentState
from backend.utils.llm import get_llm

RISK_PROMPT = """
Score this email action on 3 axes. Return JSON only.

1. RECIPIENT RISK
   Internal colleague → LOW | External client → MEDIUM | Unknown → HIGH

2. CONTENT RISK
   General update → LOW | Numbers/data → MEDIUM | Credentials/PII → HIGH (BLOCK)

3. REVERSIBILITY
   Draft only → LOW | External send → HIGH

Input:
{{
  "recipient_email": "{recipient_email}",
  "recipient_name":  "{recipient_name}",
  "pii_warning":     {pii_warning},
  "body_preview":    "{body_preview}",
  "spam_score":      {spam_score},
  "policy_violations": {policy_violations}
}}

Return:
{{
  "recipient_risk": "LOW" | "MEDIUM" | "HIGH",
  "content_risk":   "LOW" | "MEDIUM" | "HIGH",
  "reversibility":  "LOW" | "HIGH",
  "overall_risk":   "LOW" | "MEDIUM" | "HIGH",
  "action":         "AUTO_ALLOW" | "REQUIRE_CONFIRM" | "BLOCK",
  "reason":         "..."
}}
"""


def risk_scorer_node(state: AgentState) -> dict:
    llm = get_llm()
    body_preview = state.get("body_draft", "")[:200].replace('"', "'")
    response = llm.invoke(RISK_PROMPT.format(
        recipient_email=state.get("recipient_email", ""),
        recipient_name=state.get("recipient_name", ""),
        pii_warning=json.dumps(state.get("pii_warning", [])),
        body_preview=body_preview,
        spam_score=state.get("spam_score", 0),
        policy_violations=json.dumps(state.get("policy_violations", [])),
    ))
    text = response.content.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    parsed = json.loads(text.strip())
    action = parsed.get("action", "REQUIRE_CONFIRM")

    result = {
        "overall_risk":   parsed.get("overall_risk", "MEDIUM"),
        "recipient_risk": parsed.get("recipient_risk", "MEDIUM"),
        "content_risk":   parsed.get("content_risk", "LOW"),
        "reversibility":  parsed.get("reversibility", "HIGH"),
        "action_policy":  action,
    }

    if action == "BLOCK":
        result.update({
            "blocked": True,
            "block_reason": f"Risk scorer: {parsed.get('reason', '')}",
        })
    return result
