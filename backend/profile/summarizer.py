"""
profile/summarizer.py
Builds the compact context bundle injected into every LLM call,
and provides the section-aware rewrite prompt.
"""
from backend.profile.schema import UserProfile

# The six profile sections that can be independently updated.
SECTIONS = [
    "gmail_section",
    "calendar_section",
    "food_section",
    "travel_section",
    "user_info_section",
    "contacts_section",
]

SECTION_UPDATE_PROMPT = """
You are updating the **{section_name}** section of a personal assistant's
user profile.

Current summary:
{current_summary}

New information observed this session:
{new_observations}

Rules:
- Rewrite the summary from scratch. Do NOT append to the old text.
- Keep it under 3 sentences. Use present tense.
  Good: "Frequently mails Priya about invoices."
  Bad:  "The user has been mailing Priya about invoices since Jan 2025."
- Never store temporary or outdated facts (e.g. "currently in 2nd year").
  If new info contradicts the current summary, the new info wins.
- If the new info is a one-off or vague, do NOT include it.

Return ONLY the rewritten summary string.  No JSON, no markdown, no preamble.
"""


def build_context_bundle(profile: UserProfile) -> str:
    """
    Produces a compact multi-line string that is prepended to every prompt
    so the LLM knows the user's habits and preferences.
    """
    lines = ["[PERSONAL CONTEXT]"]

    mappings = {
        "Gmail habits": profile.gmail_section,
        "Calendar":     profile.calendar_section,
        "Food prefs":   profile.food_section,
        "Travel":       profile.travel_section,
        "About user":   profile.user_info_section,
        "Key contacts": profile.contacts_section,
    }

    for label, value in mappings.items():
        if value:
            lines.append(f"{label}: {value}")

    if len(lines) == 1:
        lines.append("No profile data yet.")

    return "\n".join(lines)
