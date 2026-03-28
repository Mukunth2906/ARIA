"""
backend/main.py — ARIA FastAPI backend
Run: uvicorn backend.main:app --reload --port 8001
"""
import json
import os
import uuid
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from langgraph.checkpoint.memory import MemorySaver
from pydantic import BaseModel 

from backend.graph import build_graph
from backend.utils.db import load_profile

# ── App ────────────────────────────────────────────────────────────────────────
app = FastAPI(title="ARIA API", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

_checkpointer = MemorySaver()
aria_graph     = build_graph(checkpointer=_checkpointer)

AUDIT_LOG_FILE = "aria_audit.jsonl"


# ── Models ─────────────────────────────────────────────────────────────────────

class ChatRequest(BaseModel):
    user_id: str = "default"
    message: str


class ConfirmRequest(BaseModel):
    thread_id: str
    action: str                     # "confirm" | "cancel"


class EditRequest(BaseModel):
    thread_id: str
    user_id: str = "default"
    original_input: str
    new_body: str


# ── Helpers ────────────────────────────────────────────────────────────────────

def _default_state(user_id: str, user_input: str, thread_id: str) -> dict:
    profile = load_profile(user_id)
    return {
        "original_input":            user_input,
        "thread_id":                 thread_id,
        "user_id":                   user_id,
        "messages":                  [{"role": "user", "content": user_input}],
        "profile":                   profile.to_dict(),
        # security defaults
        "blocked":                   False,
        "pii_clean":                 False,
        "pii_warning":               [],
        "pii_warning_acknowledged":  False,
        "recipient_validated":       False,
        "content_policy_pass":       False,
        "policy_violations":         [],
        "spam_score":                0,
        "confirmed":                 False,
        "cancelled":                 False,
        "cleared_to_send":           False,
        "send_success":              False,
        "failed_checks":             [],
        "audit_logged":              False,
        "vague_attempt_count":       0,
    }


def _safe(snapshot) -> dict:
    raw = dict(snapshot.values) if hasattr(snapshot, "values") else dict(snapshot)
    for f in ("pii_warning", "policy_violations", "failed_checks", "messages"):
        if raw.get(f) is None:
            raw[f] = []
    return raw


def _response(thread_id: str, snapshot) -> dict:
    state = _safe(snapshot)
    return {
        "thread_id":    thread_id,
        "state":        state,
        "interrupted":  bool(snapshot.next),
        "next_node":    list(snapshot.next) if snapshot.next else [],
        # convenience fields for frontend
        "needs_confirm": bool(snapshot.next) and not state.get("blocked"),
        "needs_clarify": bool(state.get("assistant_reply")) and not state.get("blocked"),
        "reply":         state.get("assistant_reply", ""),
        "blocked":       state.get("blocked", False),
        "risk_level":    state.get("overall_risk"),
    }


# ── Routes ─────────────────────────────────────────────────────────────────────

@app.get("/")
def root():
    return {"status": "ok", "service": "ARIA v2", "docs": "/docs"}


@app.get("/health")
def health():
    return {"status": "ok", "service": "ARIA v2"}


@app.post("/api/chat")
def chat(req: ChatRequest):
    """
    Start a new ARIA session.  Runs the graph through profile_loader →
    parse_intent → entity_extractor → confidence check → verification
    chain → draft_email, then PAUSES at the human_confirm interrupt
    (or finishes early if blocked / clarification needed).
    """
    thread_id = str(uuid.uuid4())
    config    = {"configurable": {"thread_id": thread_id}}

    initial = _default_state(req.user_id, req.message, thread_id)
    try:
        aria_graph.invoke(initial, config)
    except Exception as e:
        err_msg = str(e)
        if "RESOURCE_EXHAUSTED" in err_msg or "429" in err_msg:
            raise HTTPException(429, "Gemini API rate limit exceeded. Please wait 30-60 seconds and try again.")
        raise HTTPException(500, f"Graph execution error: {err_msg[:200]}")

    snapshot = aria_graph.get_state(config)
    return _response(thread_id, snapshot)


@app.post("/api/confirm")
def confirm(req: ConfirmRequest):
    """Resume paused graph with confirm / cancel decision."""
    config = {"configurable": {"thread_id": req.thread_id}}
    snapshot = aria_graph.get_state(config)
    if not snapshot or not snapshot.values:
        raise HTTPException(404, "Session not found.")

    if req.action == "confirm":
        update = {"confirmed": True, "cancelled": False}
    elif req.action == "cancel":
        update = {"confirmed": False, "cancelled": True,
                  "block_reason": "Cancelled by user."}
    else:
        raise HTTPException(400, "action must be 'confirm' or 'cancel'.")

    aria_graph.update_state(config, update)
    try:
        aria_graph.invoke(None, config)
    except Exception as e:
        err_msg = str(e)
        if "RESOURCE_EXHAUSTED" in err_msg or "429" in err_msg:
            raise HTTPException(429, "Gemini API rate limit exceeded. Please wait and try again.")
        raise HTTPException(500, f"Graph error: {err_msg[:200]}")

    snapshot = aria_graph.get_state(config)
    return _response(req.thread_id, snapshot)


@app.post("/api/edit")
def edit(req: EditRequest):
    """
    User edited the email body. Pull entities from original thread,
    swap body, re-run the full verification chain (new thread).
    """
    orig_config  = {"configurable": {"thread_id": req.thread_id}}
    orig_snap    = aria_graph.get_state(orig_config)
    orig         = _safe(orig_snap) if orig_snap and orig_snap.values else {}

    new_id     = str(uuid.uuid4())
    new_config = {"configurable": {"thread_id": new_id}}

    initial = _default_state(req.user_id, req.original_input, new_id)
    # carry over extracted entities + swap body
    initial.update({
        "recipient_name":     orig.get("recipient_name", ""),
        "recipient_email":    orig.get("recipient_email", ""),
        "subject":            orig.get("subject", ""),
        "tone":               orig.get("tone", "formal"),
        "intent":             orig.get("intent", "send_email"),
        "intent_description": orig.get("intent_description", ""),
        "confidence":         orig.get("confidence", 1.0),
        "body_draft":         req.new_body,
    })

    try:
        aria_graph.invoke(initial, new_config)
    except Exception as e:
        err_msg = str(e)
        if "RESOURCE_EXHAUSTED" in err_msg or "429" in err_msg:
            raise HTTPException(429, "Gemini API rate limit exceeded. Please wait and try again.")
        raise HTTPException(500, f"Graph error: {err_msg[:200]}")

    snapshot = aria_graph.get_state(new_config)
    return _response(new_id, snapshot)


@app.get("/api/profile/{user_id}")
def get_profile(user_id: str):
    profile = load_profile(user_id)
    return profile.to_dict()


@app.get("/api/audit")
def get_audit():
    if not os.path.exists(AUDIT_LOG_FILE):
        return {"entries": []}
    entries = []
    with open(AUDIT_LOG_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return {"entries": list(reversed(entries))}
