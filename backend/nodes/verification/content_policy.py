"""
Gate 3 — Content Policy
Checks for abusive language, spam patterns, impersonation, tone mismatch.
"""
import json
from backend.state import AgentState
from backend.utils.llm import get_llm

CONTENT_POLICY_PROMPT = """
You are an email content policy checker.

Rules:
1. No threatening, abusive, or harassing language
2. No spam patterns (ALL CAPS, excessive !!!, "URGENT URGENT")
3. No impersonation attempts
4. Tone must match declared intent
5. No bulk-send disguised as personal

Email:
Subject: {subject}
Body:
\"\"\"{body}\"\"\"

Declared intent: {intent_description}
Expected tone: {tone}

Return JSON only — no prose, no markdown fences:
{{
  "policy_pass":     true | false,
  "violations":      ["<description>"],
  "tone_match":      true | false,
  "spam_score":      <0–100>,
  "recommendation":  "ALLOW" | "WARN" | "BLOCK"
}}
"""


def content_policy_node(state: AgentState) -> dict:
    llm = get_llm()
    response = llm.invoke(CONTENT_POLICY_PROMPT.format(
        subject=state.get("subject", ""),
        body=state.get("body_draft", ""),
        intent_description=state.get("intent_description", ""),
        tone=state.get("tone", "formal"),
    ))
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
            "block_reason": f"Content policy: {parsed.get('violations', [])}",
            "content_policy_pass": False,
            "policy_violations": parsed.get("violations", []),
            "spam_score": parsed.get("spam_score", 0),
        }
    return {
        "content_policy_pass": parsed.get("policy_pass", True),
        "policy_violations": parsed.get("violations", []),
        "spam_score": parsed.get("spam_score", 0),
    }
