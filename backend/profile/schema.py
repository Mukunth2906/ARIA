"""
profile/schema.py
UserProfile dataclass — one document per user in MongoDB.
Each section is a compact natural-language summary string, rewritten (never
appended) after every session to keep storage bounded.
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class UserProfile:
    user_id: str
    last_updated: Optional[datetime] = None

    # ── Section summaries ─────────────────────────────────────────────────────
    # Each is ≤ 3 sentences of present-tense natural language.

    gmail_section: str = ""
    # e.g. "Frequently mails: Priya (priya@corp.com), Raj (raj@corp.com).
    #  Common labels: Work, Invoices. Usual send time: 9–11 AM."

    calendar_section: str = ""
    # e.g. "Daily standup 9:30 AM Mon–Fri. Free afternoons. Avoids 6–8 PM."

    food_section: str = ""
    # e.g. "Vegetarian. Prefers South Indian. Avoids dairy."

    travel_section: str = ""
    # e.g. "Daily route: Velachery → T.Nagar. Prefers metro."

    user_info_section: str = ""
    # e.g. "Full-stack developer. Building CogniSphere. Timezone: IST."
    # NOTE: LIVE-UPDATED — never stores outdated facts.

    contacts_section: str = ""
    # e.g. "Top contacts: Priya (manager), Raj (teammate), Amma (personal)."

    # ── Runtime counters (not persisted across sessions) ─────────────────────
    vague_attempt_count: int = 0
    session_context: list = field(default_factory=list)

    # ── Serialisation helpers ─────────────────────────────────────────────────

    def to_dict(self) -> dict:
        return {
            "user_id":            self.user_id,
            "last_updated":       self.last_updated.isoformat() if self.last_updated else None,
            "gmail_section":      self.gmail_section,
            "calendar_section":   self.calendar_section,
            "food_section":       self.food_section,
            "travel_section":     self.travel_section,
            "user_info_section":  self.user_info_section,
            "contacts_section":   self.contacts_section,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "UserProfile":
        lu = data.get("last_updated")
        if isinstance(lu, str):
            lu = datetime.fromisoformat(lu)
        return cls(
            user_id=data.get("user_id", "default"),
            last_updated=lu,
            gmail_section=data.get("gmail_section", ""),
            calendar_section=data.get("calendar_section", ""),
            food_section=data.get("food_section", ""),
            travel_section=data.get("travel_section", ""),
            user_info_section=data.get("user_info_section", ""),
            contacts_section=data.get("contacts_section", ""),
        )
