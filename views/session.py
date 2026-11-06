"""The signed-in user, cached in the Streamlit session so a rerun costs no database round trip.

Every widget click reruns the page, and on Vercel each database call is a network hop, so reading
the user on every rerun made clicks feel frozen. Anything that changes the user (onboarding answers,
saved keys, a spent free run) calls refresh() once instead.
"""

import streamlit as st

from backend import users
from backend.users import UserInfo

KEY = "cra_user"


def cached(sub: str) -> UserInfo | None:
    hit = st.session_state.get(KEY)
    return hit[1] if hit and hit[0] == sub else None


def store(sub: str, info: UserInfo) -> None:
    st.session_state[KEY] = (sub, info)


def refresh() -> UserInfo | None:
    """Re-read the user from the database after something changed it."""
    hit = st.session_state.get(KEY)
    if not hit:
        return None
    fresh = users.get_info(hit[1].id)
    if fresh is not None:
        st.session_state[KEY] = (hit[0], fresh)
    return fresh


def clear() -> None:
    st.session_state.pop(KEY, None)
