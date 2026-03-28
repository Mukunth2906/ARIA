"""
state.py — AgentState TypedDict
Single source of truth for every field that flows through the LangGraph.
"""
from typing import TypedDict


class AgentState(TypedDict, total=False):
    # ── Core conversation ────────────────────────────────────────────────────
    messages:           list        # full conversation history
    original_input:     str         # raw user text
    thread_id:          str         # unique session identifier
    user_id:            str         # user identifier for profile lookup

    # ── Profile (serialised dict, not dataclass, for LangGraph compat) ───────
    profile:            dict        # UserProfile.to_dict() output

    # ── Intent + confidence ──────────────────────────────────────────────────
    intent:             str         # send_email | draft_email | schedule_event | …
    intent_description: str
    confidence:         float       # 0.0 – 1.0
    ambiguity_reason:   str
    vague_attempt_count: int        # how many RAG retries so far

    # ── Extracted entities ───────────────────────────────────────────────────
    recipient_name:     str
    recipient_email:    str
    subject:            str
    subject_hint:       str
    body_draft:         str
    body_hint:          str
    tone:               str         # formal / casual / urgent
    time_hint:          str         # for calendar events

    # ── Security: PII scanner ────────────────────────────────────────────────
    pii_clean:                  bool
    pii_warning:                list
    pii_warning_acknowledged:   bool

    # ── Security: recipient validation ───────────────────────────────────────
    recipient_validated:        bool
    validation_error:           str

    # ── Security: content policy ─────────────────────────────────────────────
    content_policy_pass:        bool
    policy_violations:          list
    spam_score:                 int

    # ── Security: risk scorer ────────────────────────────────────────────────
    recipient_risk:     str         # LOW / MEDIUM / HIGH
    content_risk:       str         # LOW / MEDIUM / HIGH
    reversibility:      str         # LOW / HIGH
    overall_risk:       str         # LOW / MEDIUM / HIGH
    action_policy:      str         # AUTO_ALLOW / REQUIRE_CONFIRM / BLOCK

    # ── Gate flags ───────────────────────────────────────────────────────────
    blocked:            bool
    block_reason:       str
    cleared_to_send:    bool
    failed_checks:      list

    # ── Human confirmation ───────────────────────────────────────────────────
    confirmed:          bool
    cancelled:          bool

    # ── Execution ────────────────────────────────────────────────────────────
    send_success:       bool
    gmail_message_id:   str

    # ── Assistant reply (for clarifications / general responses) ─────────────
    assistant_reply:    str

    # ── Audit ────────────────────────────────────────────────────────────────
    audit_logged:       bool
    audit_entry_id:     int
