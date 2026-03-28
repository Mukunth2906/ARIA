"""
Gate 2 — Recipient Validator
Format check → domain blocklist → LLM intent-match confirmation.
"""
import json
import re
from backend.state import AgentState
from backend.utils.llm import get_llm

BLOCKED_DOMAINS = {
    "tempmail.com", "throwaway.email", "10minutemail.com",
    "mailinator.com", "guerrillamail.com", "sharklasers.com",
    "trashmail.com", "yopmail.com", "dispostable.com",
}

EMAIL_RE = re.compile(r'^[\w\.\+\-]+@[\w\.\-]+\.\w{2,}$')

CONFIRM_PROMPT = """
The user said: "{original_input}"
Extracted recipient: {recipient_name} <{recipient_email}>

Does this recipient make sense for this request?

Return JSON only — no prose, no markdown fences:
{{
  "match":      true | false,
  "confidence": <0.0–1.0>,
  "reason":     "<brief explanation>"
}}
"""


def recipient_validator_node(state: AgentState) -> dict:
    llm = get_llm()
    email = state.get("recipient_email", "").strip()

    if not email:
        return {"validation_error": "No recipient email found."}
    if not EMAIL_RE.match(email):
        return {"validation_error": f"Invalid email format: '{email}'"}

    domain = email.split("@")[1].lower()
    if domain in BLOCKED_DOMAINS:
        return {
            "blocked": True,
            "block_reason": f"Blocked domain: {domain}",
            "validation_error": f"Disposable email domain: {domain}",
        }

    response = llm.invoke(CONFIRM_PROMPT.format(
        original_input=state.get("original_input", ""),
        recipient_name=state.get("recipient_name", ""),
        recipient_email=email,
    ))
    text = response.content.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    parsed = json.loads(text.strip())

    if not parsed.get("match") or parsed.get("confidence", 0) < 0.75:
        return {
            "validation_error": f"Recipient mismatch ({parsed.get('confidence', 0):.0%}): {parsed.get('reason', '')}",
            "recipient_validated": False,
        }
    return {"recipient_validated": True}
