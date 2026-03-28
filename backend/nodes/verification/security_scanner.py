"""
security_scanner.py — COMBINED verification node
Replaces 4 separate LLM calls (pii_scanner + recipient_validator +
content_policy + risk_scorer) with ONE single call.

This cuts LLM usage from 7 calls/email → 4 calls/email.
"""
import json
import re

from backend.state import AgentState
from backend.utils.llm import get_llm

BLOCKED_DOMAINS = {
    "tempmail.com", "throwaway.email", "10minutemail.com",
    "mailinator.com", "guerrillamail.com", "yopmail.com",
}

EMAIL_RE = re.compile(r'^[\w\.\+\-]+@[\w\.\-]+\.\w{2,}$')

COMBINED_SCAN_PROMPT = """
You are a security scanner for an email assistant.
Analyse this email and return a single JSON assessment.

EMAIL:
  To:      {recipient_name} <{recipient_email}>
  Subject: {subject}
  Body:    \"\"\"{body_preview}\"\"\"
  Intent:  {intent_description}
  Tone:    {tone}

CHECK ALL OF THESE:

1. PII SCAN — Does the body contain passwords, API keys, bank/card numbers,
   Aadhaar/PAN/SSN, medical data, salary figures, or server credentials?

2. CONTENT POLICY — Any abusive language, spam patterns (ALL CAPS, !!!),
   impersonation, or tone mismatch?

3. RISK SCORE — Rate recipient risk (internal=LOW, external=MEDIUM,
   unknown=HIGH), content risk, and overall risk.

Return JSON ONLY — no prose, no markdown fences:
{{
  "pii_found": false,
  "pii_items": [],
  "pii_action": "ALLOW",
  "policy_pass": true,
  "violations": [],
  "spam_score": 0,
  "recipient_risk": "LOW",
  "content_risk": "LOW",
  "overall_risk": "MEDIUM",
  "action": "REQUIRE_CONFIRM",
  "reason": "brief explanation"
}}
"""


def security_scanner_node(state: AgentState) -> dict:
    """
    Combined PII + content policy + risk scoring in ONE LLM call.
    Recipient format/blocklist checks are done locally (no LLM needed).
    """
    email = state.get("recipient_email", "").strip()

    # ── Local checks (no LLM) ────────────────────────────────────────────────
    if not email:
        return {"validation_error": "No recipient email found.", "blocked": True,
                "block_reason": "No recipient email found."}

    if not EMAIL_RE.match(email):
        return {"validation_error": f"Invalid email format: '{email}'", "blocked": True,
                "block_reason": f"Invalid email format: '{email}'"}

    domain = email.split("@")[1].lower()
    if domain in BLOCKED_DOMAINS:
        return {"validation_error": f"Disposable domain: {domain}", "blocked": True,
                "block_reason": f"Blocked domain: {domain}"}

    # ── Single LLM call for all security checks ──────────────────────────────
    llm = get_llm()
    body = state.get("body_draft", "")
    body_preview = body[:500].replace('"', "'")

    response = llm.invoke(COMBINED_SCAN_PROMPT.format(
        recipient_name=state.get("recipient_name", ""),
        recipient_email=email,
        subject=state.get("subject", ""),
        body_preview=body_preview,
        intent_description=state.get("intent_description", ""),
        tone=state.get("tone", "formal"),
    ))

    text = response.content.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    parsed = json.loads(text.strip())

    # ── Build result ──────────────────────────────────────────────────────────
    result = {
        # PII
        "pii_clean":           not parsed.get("pii_found", False),
        "pii_warning":         parsed.get("pii_items", []),
        # Content policy
        "content_policy_pass": parsed.get("policy_pass", True),
        "policy_violations":   parsed.get("violations", []),
        "spam_score":          parsed.get("spam_score", 0),
        # Risk
        "recipient_risk":      parsed.get("recipient_risk", "MEDIUM"),
        "content_risk":        parsed.get("content_risk", "LOW"),
        "overall_risk":        parsed.get("overall_risk", "MEDIUM"),
        "action_policy":       parsed.get("action", "REQUIRE_CONFIRM"),
        # Recipient
        "recipient_validated": True,
    }

    pii_action = parsed.get("pii_action", "ALLOW")
    action     = parsed.get("action", "REQUIRE_CONFIRM")

    if pii_action == "BLOCK" or action == "BLOCK":
        result.update({
            "blocked":      True,
            "block_reason": parsed.get("reason", "Blocked by security scanner"),
        })

    return result
