"""
Gmail API client — send + inbox read.
"""
import base64
from email.mime.text import MIMEText

from googleapiclient.discovery import build
from backend.utils.token_manager import get_credentials


def _service():
    return build("gmail", "v1", credentials=get_credentials())


def send_email(to: str, subject: str, body: str) -> str:
    """Send an email, return the Gmail message ID."""
    svc = _service()
    mime = MIMEText(body, "plain")
    mime["to"]      = to
    mime["subject"] = subject
    raw = base64.urlsafe_b64encode(mime.as_bytes()).decode()
    result = svc.users().messages().send(
        userId="me", body={"raw": raw}
    ).execute()
    return result.get("id", "unknown")


def list_inbox(max_results: int = 10) -> list:
    """Return recent inbox message summaries."""
    svc = _service()
    resp = svc.users().messages().list(
        userId="me", labelIds=["INBOX"], maxResults=max_results
    ).execute()
    summaries = []
    for msg in resp.get("messages", []):
        detail = svc.users().messages().get(
            userId="me", id=msg["id"],
            format="metadata",
            metadataHeaders=["From", "Subject", "Date"],
        ).execute()
        headers = {h["name"]: h["value"] for h in detail["payload"]["headers"]}
        summaries.append({
            "id":      msg["id"],
            "from":    headers.get("From", ""),
            "subject": headers.get("Subject", ""),
            "date":    headers.get("Date", ""),
            "snippet": detail.get("snippet", ""),
        })
    return summaries
