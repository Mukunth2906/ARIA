"""
Gate 1 — PII Scanner
Scans the email body for passwords, keys, financial data, IDs, etc.
"""
import json
from backend.state import AgentState
from backend.utils.llm import get_llm

PII_SCAN_PROMPT = """
You are a data security scanner.
Scan the email body below for sensitive information.

Flag if you find ANY of:
- Passwords, API keys, tokens, secrets
- Bank account / credit card / CVV numbers
- Aadhaar / PAN / Passport / SSN / national ID numbers
- Private medical or health information
- Confidential salary, financial projections, internal budgets
- Internal server IPs, credentials, connection strings
- Private encryption keys or certificates

Email body:
\"\"\"{body}\"\"\"

Return JSON only — no prose, no markdown fences:
{{
  "pii_found":       true | false,
  "flagged_items":   ["<description>"],
  "severity":        "LOW" | "MEDIUM" | "HIGH",
  "recommendation":  "BLOCK" | "WARN" | "ALLOW"
}}
"""


def pii_scanner_node(state: AgentState) -> dict:
    llm = get_llm()
    body = state.get("body_draft", "")
    response = llm.invoke(PII_SCAN_PROMPT.format(body=body))
    text = response.content.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    parsed = json.loads(text.strip())
    rec = parsed.get("recommendation", "ALLOW")

    if rec == "BLOCK":
        return {
            "blocked": True,
            "block_reason": f"PII detected: {parsed.get('flagged_items', [])}",
            "pii_clean": False,
            "pii_warning": parsed.get("flagged_items", []),
        }
    if rec == "WARN":
        return {"pii_clean": False, "pii_warning": parsed.get("flagged_items", [])}
    return {"pii_clean": True, "pii_warning": []}
