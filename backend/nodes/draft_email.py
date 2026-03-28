"""
nodes/draft_email.py
Polishes the extracted body_draft into a final email.
"""
import json

from backend.state import AgentState
from backend.utils.llm import get_llm

DRAFT_PROMPT = """
You are a professional email writing assistant.
Polish the draft below. Keep the meaning identical but improve clarity,
grammar, and professional tone (match: {tone}).

Recipient: {recipient_name}
Subject:   {subject}
Draft:
\"\"\"{body_draft}\"\"\"

Return JSON only — no prose, no markdown fences:
{{
  "subject": "<final subject>",
  "body":    "<final polished email body>"
}}
"""


def draft_email_node(state: AgentState) -> dict:
    llm = get_llm()
    response = llm.invoke(DRAFT_PROMPT.format(
        tone=state.get("tone", "formal"),
        recipient_name=state.get("recipient_name", ""),
        subject=state.get("subject", ""),
        body_draft=state.get("body_draft", ""),
    ))
    text = response.content.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    parsed = json.loads(text.strip())
    return {
        "subject":    parsed.get("subject", state.get("subject", "")),
        "body_draft": parsed.get("body",    state.get("body_draft", "")),
    }
