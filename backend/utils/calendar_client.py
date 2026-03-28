"""
Google Calendar API client — read events + create events.
"""
from datetime import datetime, timedelta

from googleapiclient.discovery import build
from backend.utils.token_manager import get_credentials


def _service():
    return build("calendar", "v3", credentials=get_credentials())


def list_upcoming_events(max_results: int = 10) -> list:
    """Return upcoming calendar events."""
    svc = _service()
    now = datetime.utcnow().isoformat() + "Z"
    result = svc.events().list(
        calendarId="primary",
        timeMin=now,
        maxResults=max_results,
        singleEvents=True,
        orderBy="startTime",
    ).execute()
    events = []
    for e in result.get("items", []):
        start = e["start"].get("dateTime", e["start"].get("date"))
        events.append({
            "id":      e.get("id"),
            "summary": e.get("summary", "(no title)"),
            "start":   start,
            "end":     e["end"].get("dateTime", e["end"].get("date")),
        })
    return events


def create_event(
    summary: str,
    start_time: str,
    end_time: str,
    description: str = "",
    attendees: list = None,
) -> str:
    """Create a calendar event, return the event ID."""
    svc = _service()
    body = {
        "summary":     summary,
        "description": description,
        "start":       {"dateTime": start_time, "timeZone": "Asia/Kolkata"},
        "end":         {"dateTime": end_time,   "timeZone": "Asia/Kolkata"},
    }
    if attendees:
        body["attendees"] = [{"email": a} for a in attendees]
    result = svc.events().insert(calendarId="primary", body=body).execute()
    return result.get("id", "unknown")
