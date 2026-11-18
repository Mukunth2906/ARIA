"""
backend/main.py — ARIA FastAPI backend
Run: uvicorn backend.main:app --reload --port 8001
"""
import asyncio
import json
import os
import uuid
from typing import Optional, Dict, List

from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from langgraph.checkpoint.memory import MemorySaver
from pydantic import BaseModel

from backend.graph import build_graph
from backend.utils.db import load_profile, save_profile
from backend.utils.stt import transcribe_audio
from backend.utils.vector_store import (
    upsert_context,
    query_context,
    list_user_context,
    delete_context_item,
    delete_all_user_context,
    purge_expired_context,
)

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
    rag_consent: Optional[bool] = None


class ConfirmRequest(BaseModel):
    thread_id: str
    action: str                     # "confirm" | "cancel"


class ScheduleSendRequest(BaseModel):
    thread_id: str
    delay_seconds: int = 10


class UndoRequest(BaseModel):
    thread_id: str


class RagIngestRequest(BaseModel):
    user_id: str = "default"
    text: str
    doc_type: str = "contact_note"  # sent_email | calendar_event | contact_note | session_summary
    source_label: str = "User note"
    recipient_email: str = ""
    subject: str = ""
    retention_days: Optional[int] = None


class RagQueryRequest(BaseModel):
    user_id: str = "default"
    query: str
    n_results: int = 3
    doc_types: Optional[List[str]] = None
    recipient_email: Optional[str] = None
    max_age_days: Optional[int] = None


class RagSettingsRequest(BaseModel):
    rag_consent: Optional[bool] = None
    rag_retention_days: Optional[int] = None


# ── Active delayed dispatch tasks ──────────────────────────────────────────────
_pending_dispatches: Dict[str, asyncio.Task] = {}


class EditRequest(BaseModel):
    thread_id: str
    user_id: str = "default"
    original_input: str
    new_body: str


# ── Helpers ────────────────────────────────────────────────────────────────────

def _default_state(
    user_id: str,
    user_input: str,
    thread_id: str,
    rag_consent: Optional[bool] = None,
) -> dict:
    profile = load_profile(user_id)
    effective_consent = profile.rag_consent if rag_consent is None else bool(rag_consent)
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
        # persistent RAG defaults
        "rag_consent":               effective_consent,
        "rag_sources":               [],
        "rag_attribution":           "",
        "rag_indexed_ids":           [],
    }


def _safe(snapshot) -> dict:
    raw = dict(snapshot.values) if hasattr(snapshot, "values") else dict(snapshot)
    for f in ("pii_warning", "policy_violations", "failed_checks", "messages", "rag_sources", "rag_indexed_ids"):
        if raw.get(f) is None:
            raw[f] = []
    return raw


def _response(thread_id: str, snapshot) -> dict:
    state = _safe(snapshot)
    return {
        "thread_id":       thread_id,
        "state":           state,
        "interrupted":     bool(snapshot.next),
        "next_node":       list(snapshot.next) if snapshot.next else [],
        # convenience fields for frontend
        "needs_confirm":   bool(snapshot.next) and not state.get("blocked"),
        "needs_clarify":   bool(state.get("assistant_reply")) and not state.get("blocked"),
        "reply":           state.get("assistant_reply", ""),
        "blocked":         state.get("blocked", False),
        "risk_level":      state.get("overall_risk"),
        "rag_sources":     state.get("rag_sources", []),
        "rag_attribution": state.get("rag_attribution", ""),
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

    initial = _default_state(req.user_id, req.message, thread_id, rag_consent=req.rag_consent)
    try:
        aria_graph.invoke(initial, config)
    except Exception as e:
        err_msg = str(e)
        if "RESOURCE_EXHAUSTED" in err_msg or "429" in err_msg:
            raise HTTPException(429, "Gemini API rate limit exceeded. Please wait 30-60 seconds and try again.")
        raise HTTPException(500, f"Graph execution error: {err_msg[:200]}")

    snapshot = aria_graph.get_state(config)
    return _response(thread_id, snapshot)


@app.post("/api/voice")
async def voice_chat(
    file: UploadFile = File(...),
    user_id: str = Form("default"),
):
    """
    Ingest voice recording, transcribe it using Whisper STT,
    and trigger the LangGraph verification pipeline with the transcribed text.
    """
    audio_bytes = await file.read()
    if not audio_bytes:
        raise HTTPException(400, "Empty audio file received.")

    filename = file.filename or "recording.wav"
    try:
        transcription = transcribe_audio(audio_bytes, filename=filename)
    except Exception as e:
        raise HTTPException(500, f"Speech-to-text error: {str(e)}")

    if not transcription.strip():
        raise HTTPException(400, "Could not detect any speech in the audio.")

    thread_id = str(uuid.uuid4())
    config    = {"configurable": {"thread_id": thread_id}}

    initial = _default_state(user_id, transcription, thread_id)
    try:
        aria_graph.invoke(initial, config)
    except Exception as e:
        err_msg = str(e)
        if "RESOURCE_EXHAUSTED" in err_msg or "429" in err_msg:
            raise HTTPException(429, "Gemini API rate limit exceeded. Please wait 30-60 seconds and try again.")
        raise HTTPException(500, f"Graph execution error: {err_msg[:200]}")

    snapshot = aria_graph.get_state(config)
    res = _response(thread_id, snapshot)
    res["transcription"] = transcription
    return res


@app.post("/api/transcribe")
async def transcribe_only(file: UploadFile = File(...)):
    """
    Transcribe audio only using Whisper STT without triggering the graph.
    """
    audio_bytes = await file.read()
    if not audio_bytes:
        raise HTTPException(400, "Empty audio file received.")

    filename = file.filename or "recording.wav"
    try:
        transcription = transcribe_audio(audio_bytes, filename=filename)
    except Exception as e:
        raise HTTPException(500, f"Speech-to-text error: {str(e)}")

    return {"transcription": transcription}


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


@app.post("/api/schedule_send")
async def schedule_send(req: ScheduleSendRequest):
    """
    Queue email for sending with an undo grace period (default 10s).
    If /api/undo is called before the timer expires, the send is cancelled.
    """
    thread_id = req.thread_id
    config = {"configurable": {"thread_id": thread_id}}
    snapshot = aria_graph.get_state(config)
    if not snapshot or not snapshot.values:
        raise HTTPException(404, "Session not found.")

    # Cancel any existing queued task for this thread
    if thread_id in _pending_dispatches and not _pending_dispatches[thread_id].done():
        _pending_dispatches[thread_id].cancel()

    async def _execute_after_delay():
        try:
            await asyncio.sleep(req.delay_seconds)
            # Grace period elapsed without undo -> execute send!
            aria_graph.update_state(config, {"confirmed": True, "cancelled": False})
            aria_graph.invoke(None, config)
        except asyncio.CancelledError:
            # User triggered Undo! Do not invoke send.
            pass
        finally:
            _pending_dispatches.pop(thread_id, None)

    task = asyncio.create_task(_execute_after_delay())
    _pending_dispatches[thread_id] = task

    return {
        "status": "queued",
        "thread_id": thread_id,
        "undo_window_seconds": req.delay_seconds,
        "message": f"Sending queued with a {req.delay_seconds}s undo window.",
    }


@app.post("/api/undo")
def undo_send(req: UndoRequest):
    """
    Cancel an email queued in the delayed dispatch buffer.
    """
    thread_id = req.thread_id
    task = _pending_dispatches.get(thread_id)
    if task and not task.done():
        task.cancel()
        _pending_dispatches.pop(thread_id, None)
        return {
            "status": "undone",
            "thread_id": thread_id,
            "message": "Dispatch cancelled successfully. No email was sent.",
        }

    config = {"configurable": {"thread_id": thread_id}}
    snapshot = aria_graph.get_state(config)
    state = _safe(snapshot) if snapshot else {}
    if state.get("send_success"):
        raise HTTPException(400, "Cannot undo: email has already been dispatched via Gmail API.")

    return {"status": "not_queued", "message": "No active queued dispatch found for this session."}


@app.get("/api/status/{thread_id}")
def thread_status(thread_id: str):
    """
    Check current execution status of a thread (e.g. queued, sent, paused).
    """
    is_queued = thread_id in _pending_dispatches and not _pending_dispatches[thread_id].done()
    config = {"configurable": {"thread_id": thread_id}}
    snapshot = aria_graph.get_state(config)
    state = _safe(snapshot) if snapshot else {}
    return {
        "thread_id": thread_id,
        "is_queued": is_queued,
        "state": state,
    }


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


@app.patch("/api/profile/{user_id}/rag-settings")
def update_rag_settings(user_id: str, req: RagSettingsRequest):
    """Update user's RAG indexing consent and retention TTL policy."""
    profile = load_profile(user_id)
    if req.rag_consent is not None:
        profile.rag_consent = bool(req.rag_consent)
    if req.rag_retention_days is not None:
        if req.rag_retention_days < 1 or req.rag_retention_days > 365:
            raise HTTPException(400, "rag_retention_days must be between 1 and 365.")
        profile.rag_retention_days = int(req.rag_retention_days)
    save_profile(profile)
    return profile.to_dict()


# ── Persistent RAG Management & Privacy Routes ─────────────────────────────────

@app.get("/api/rag/context/{user_id}")
def get_rag_context(user_id: str, doc_type: Optional[str] = None, limit: int = 50):
    """Inspect all vector documents indexed for this user."""
    items = list_user_context(user_id, doc_type=doc_type, limit=limit)
    return {"user_id": user_id, "count": len(items), "items": items}


@app.post("/api/rag/context")
def ingest_rag_context(req: RagIngestRequest):
    """
    Privacy-gated ingestion of selected user context into persistent ChromaDB.
    Enforces user consent and deterministic PII/secret blocking.
    """
    profile = load_profile(req.user_id)
    retention = req.retention_days if req.retention_days is not None else profile.rag_retention_days
    result = upsert_context(
        user_id=req.user_id,
        text=req.text,
        doc_type=req.doc_type,
        source_label=req.source_label,
        recipient_email=req.recipient_email,
        subject=req.subject,
        retention_days=retention,
        consent=profile.rag_consent,
        pii_clean=True,
    )
    if not result.get("indexed"):
        raise HTTPException(400, result.get("reason", "Context could not be indexed."))
    return result


@app.post("/api/rag/query")
def query_rag_context(req: RagQueryRequest):
    """Metadata-filtered semantic search returning attributed source records."""
    profile = load_profile(req.user_id)
    max_age = req.max_age_days if req.max_age_days is not None else profile.rag_retention_days
    hits = query_context(
        user_id=req.user_id,
        query_text=req.query,
        n_results=req.n_results,
        doc_types=req.doc_types,
        recipient_email=req.recipient_email,
        max_age_days=max_age,
        exclude_expired=True,
    )
    return {"user_id": req.user_id, "count": len(hits), "sources": hits}


@app.delete("/api/rag/context/{user_id}/{doc_id}")
def delete_single_rag_item(user_id: str, doc_id: str):
    """Delete a single indexed RAG document."""
    deleted = delete_context_item(user_id, doc_id)
    if not deleted:
        raise HTTPException(404, f"Document '{doc_id}' not found for user '{user_id}'.")
    return {"deleted": True, "user_id": user_id, "doc_id": doc_id}


@app.delete("/api/rag/context/{user_id}")
def wipe_user_rag_context(user_id: str):
    """Right-to-be-Forgotten: permanently wipe all RAG vectors for a user."""
    removed = delete_all_user_context(user_id)
    return {"wiped": True, "user_id": user_id, "deleted_count": removed}


@app.post("/api/rag/purge/{user_id}")
def purge_user_expired_rag(user_id: str):
    """Purge all indexed RAG items past their retention TTL."""
    purged = purge_expired_context(user_id)
    return {"user_id": user_id, "purged_count": purged}


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
