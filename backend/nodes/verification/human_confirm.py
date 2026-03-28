"""
Gate 5 — Human Confirm
Passthrough node.  The graph is compiled with interrupt_before=["human_confirm"].
Execution pauses before this node; the API collects the user's decision
(confirm/cancel/edit) and updates state via graph.update_state(), then
resumes.  By the time this node runs, confirmed/cancelled is already set.
"""
from backend.state import AgentState


def human_confirm_node(state: AgentState) -> dict:
    return {}
