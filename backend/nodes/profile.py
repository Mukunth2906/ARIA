"""
nodes/profile.py
profile_loader_node   — loads profile from DB at session start.
profile_updater_node  — updates + persists profile at session end.
"""
from backend.state import AgentState
from backend.profile.schema import UserProfile
from backend.profile.updater import update_profile_post_session, extract_session_observations
from backend.utils.db import load_profile, save_profile


def profile_loader_node(state: AgentState) -> dict:
    """Load profile from MongoDB / local JSON at session start."""
    user_id = state.get("user_id", "default")
    profile = load_profile(user_id)
    return {"profile": profile.to_dict()}


def profile_updater_node(state: AgentState) -> dict:
    """
    Extract observations from this session, rewrite relevant profile
    sections, and persist back to DB. Runs after audit_log.
    """
    profile_dict = state.get("profile", {})
    if not profile_dict:
        return {}

    profile = UserProfile.from_dict(profile_dict)
    observations = extract_session_observations(state)

    if observations:
        try:
            updated = update_profile_post_session(profile, observations)
            save_profile(updated)
            return {"profile": updated.to_dict()}
        except Exception:
            # Profile update failure should never block the main flow
            return {}

    return {}
