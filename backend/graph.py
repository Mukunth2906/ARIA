"""
graph.py — Full LangGraph wiring for ARIA (optimised: 4 LLM calls per email)

LLM calls per email:
  1. parse_intent       (intent + entity extraction combined)
  2. security_scanner   (PII + content policy + risk in ONE call)
  3. draft_email        (polish body)
  4. profile_updater    (update profile sections — only if something changed)

Flow:
  profile_loader → parse_intent → entity_extractor
    → [CONFIDENCE ROUTER]
        ├─ proceed → security_scanner
        │   ├─(blocked)→ audit_log → profile_updater → END
        │   └─(ok)→ draft_email → ★ INTERRUPT ★ human_confirm
        │       ├─(cancelled)→ audit_log → profile_updater → END
        │       ├─(re_verify)→ security_scanner (on edit)
        │       └─(confirmed)→ final_safety_check
        │           ├─(blocked)→ audit_log → profile_updater → END
        │           └─(send)→ execute_send → audit_log → profile_updater → END
        ├─ rag → selective_rag → parse_intent (loop, max 2x)
        └─ clarify → ask_clarify → audit_log → profile_updater → END
"""
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver

from backend.state import AgentState

# Core nodes
from backend.nodes.profile    import profile_loader_node, profile_updater_node
from backend.nodes.intent     import parse_intent_node, entity_extractor_node
from backend.nodes.confidence import confidence_router, clarify_response_node
from backend.nodes.rag        import selective_rag_node
from backend.nodes.draft_email import draft_email_node
from backend.nodes.executor   import execute_send_node
from backend.nodes.audit      import audit_log_node

# Combined security node (replaces 4 separate LLM calls)
from backend.nodes.verification.security_scanner import security_scanner_node
from backend.nodes.verification.human_confirm    import human_confirm_node
from backend.nodes.verification.final_safety     import final_safety_check_node


# ── Conditional edge functions ─────────────────────────────────────────────────

def _route_after_security(state: AgentState) -> str:
    if state.get("blocked") or state.get("validation_error"):
        return "blocked"
    return "draft"


def _route_after_human_confirm(state: AgentState) -> str:
    if state.get("cancelled"):
        return "cancelled"
    if not state.get("confirmed"):
        return "re_verify"
    return "confirmed"


def _route_after_final_check(state: AgentState) -> str:
    if not state.get("cleared_to_send"):
        return "blocked"
    return "send"


# ── Builder ────────────────────────────────────────────────────────────────────

def build_graph(checkpointer=None):
    g = StateGraph(AgentState)

    # ── Register nodes ────────────────────────────────────────────────────────
    g.add_node("profile_loader",       profile_loader_node)
    g.add_node("parse_intent",         parse_intent_node)
    g.add_node("entity_extractor",     entity_extractor_node)
    g.add_node("selective_rag",        selective_rag_node)
    g.add_node("ask_clarify",          clarify_response_node)

    g.add_node("security_scanner",     security_scanner_node)   # 1 call = PII+policy+risk
    g.add_node("draft_email",          draft_email_node)
    g.add_node("human_confirm",        human_confirm_node)
    g.add_node("final_safety_check",   final_safety_check_node)
    g.add_node("execute_send",         execute_send_node)
    g.add_node("audit_log",            audit_log_node)
    g.add_node("profile_updater",      profile_updater_node)

    # ── Entry ─────────────────────────────────────────────────────────────────
    g.set_entry_point("profile_loader")

    # ── Linear: profile → intent → entities ───────────────────────────────────
    g.add_edge("profile_loader",  "parse_intent")
    g.add_edge("parse_intent",    "entity_extractor")

    # ── Confidence routing ────────────────────────────────────────────────────
    g.add_conditional_edges(
        "entity_extractor",
        confidence_router,
        {
            "proceed": "security_scanner",
            "rag":     "selective_rag",
            "clarify": "ask_clarify",
        },
    )

    g.add_edge("selective_rag", "parse_intent")     # loop back
    g.add_edge("ask_clarify",   "audit_log")        # terminal

    # ── After security scanner: blocked or draft ──────────────────────────────
    g.add_conditional_edges(
        "security_scanner",
        _route_after_security,
        {"blocked": "audit_log", "draft": "draft_email"},
    )

    g.add_edge("draft_email", "human_confirm")

    # ── After human confirm ───────────────────────────────────────────────────
    g.add_conditional_edges(
        "human_confirm",
        _route_after_human_confirm,
        {
            "cancelled":  "audit_log",
            "re_verify":  "security_scanner",
            "confirmed":  "final_safety_check",
        },
    )

    # ── After final check ─────────────────────────────────────────────────────
    g.add_conditional_edges(
        "final_safety_check",
        _route_after_final_check,
        {"blocked": "audit_log", "send": "execute_send"},
    )

    # ── Terminal path ─────────────────────────────────────────────────────────
    g.add_edge("execute_send",    "audit_log")
    g.add_edge("audit_log",       "profile_updater")
    g.add_edge("profile_updater", END)

    # ── Compile ───────────────────────────────────────────────────────────────
    compile_kwargs = {}
    if checkpointer is not None:
        compile_kwargs["checkpointer"]     = checkpointer
        compile_kwargs["interrupt_before"] = ["human_confirm"]

    return g.compile(**compile_kwargs)
