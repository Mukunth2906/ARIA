"""
profile/updater.py
Runs after every session to refresh only the profile sections that
received new observations.  Sections with no new data stay unchanged.
"""
import json
from datetime import datetime

from backend.profile.schema import UserProfile
from backend.profile.summarizer import SECTIONS, SECTION_UPDATE_PROMPT
from backend.utils.llm import get_llm


def update_profile_post_session(
    profile: UserProfile,
    session_observations: dict,
) -> UserProfile:
    """
    Parameters
    ----------
    profile : UserProfile
        The current user profile.
    session_observations : dict
        Keys are section names (e.g. "gmail_section").
        Values are either a string describing what was observed this session
        or None if nothing new was learned.

    Returns
    -------
    UserProfile with only changed sections rewritten.
    """
    llm = get_llm()

    for section in SECTIONS:
        obs = session_observations.get(section)
        if not obs:
            continue   # nothing new for this section

        current = getattr(profile, section) or "No prior data."

        prompt = SECTION_UPDATE_PROMPT.format(
            section_name=section.replace("_section", "").capitalize(),
            current_summary=current,
            new_observations=obs,
        )
        response = llm.invoke(prompt)
        new_summary = response.content.strip()

        setattr(profile, section, new_summary)

    profile.last_updated = datetime.utcnow()
    profile.vague_attempt_count = 0
    return profile


def extract_session_observations(state: dict) -> dict:
    """
    Examines the finished agent state and returns a dict of observations
    per profile section.  Returns None for sections with no new info.
    """
    observations = {}

    # Gmail section — if an email was sent
    if state.get("send_success"):
        observations["gmail_section"] = (
            f"Sent email to {state.get('recipient_name', '?')} "
            f"({state.get('recipient_email', '?')}) "
            f"about: {state.get('subject', '?')}."
        )

    if state.get("recipient_name"):
        observations["contacts_section"] = (
            f"Interacted with {state.get('recipient_name', '')} "
            f"<{state.get('recipient_email', '')}>."
        )

    # User info — pull from the original_input if the user states facts
    # about themselves.  The LLM rewrite prompt handles de-duplication.
    original = state.get("original_input", "")
    if any(kw in original.lower() for kw in
           ("i am", "i'm", "my name", "i work", "i study", "my role")):
        observations["user_info_section"] = (
            f"User said: \"{original}\""
        )

    return observations
