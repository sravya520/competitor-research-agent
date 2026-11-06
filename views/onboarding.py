"""Onboarding: what Moat is for, team size (and teammates to invite).

Which step to show comes from what is already saved, not from session state, because on Vercel the
session resets about once a minute and a half-finished onboarding must pick up where it was.
"""

import streamlit as st

from backend import users
from backend.users import UserInfo
from views import session

USE_CASES = [
    "For my startup",
    "For my company or work",
    "As a student or researcher",
    "For a client (agency or consultant)",
    "Just exploring",
]
TEAM_SIZES = ["Just me", "2 to 5", "6 to 20", "21 to 100", "More than 100"]
SKIPPED = "(skipped)"  # old rows from when these steps could be skipped
MAX_INVITES = 5


def _heading(step: int, title: str, body: str = "") -> None:
    sub = f"<p>{body}</p>" if body else ""
    st.html(f'<div class="si-copy"><p class="si-step">Step {step} of 2</p><h1>{title}</h1>{sub}</div>')


def _invites() -> list[str]:
    """Email boxes for teammates, shown when the team is bigger than one. Returns what was typed."""
    n = st.session_state.setdefault("ob_invite_n", 1)
    st.html('<p class="si-fine si-guide">Add your teammates\' emails. We\'ll keep them until sharing opens.</p>')
    typed = [
        st.text_input("Teammate email", key=f"ob_invite_{i}", placeholder="name@company.com",
                      label_visibility="collapsed")
        for i in range(n)
    ]
    if n < MAX_INVITES and st.button("Add collaborator", type="tertiary", key="ob_add_collab"):
        st.session_state["ob_invite_n"] = n + 1
        st.rerun()
    return typed


def render(user: UserInfo) -> None:
    """Show the next unfinished onboarding step. The caller stops the page after this."""
    with st.container(key="si"):
        if user.use_case is None:
            _heading(1, "What will you use Moat for?")
            choice = st.radio("What will you use Moat for?", USE_CASES, index=None,
                              label_visibility="collapsed", key="ob_use_case")
            if st.button("Continue", type="primary", key="ob_next1", disabled=choice is None):
                users.save_use_case(user.id, choice)
                session.refresh()
                st.rerun()

        elif user.team_size is None:
            _heading(2, "How big is your team?")
            choice = st.radio("How big is your team?", TEAM_SIZES, index=None,
                              label_visibility="collapsed", key="ob_team")
            typed = _invites() if choice and choice != TEAM_SIZES[0] else []
            if st.button("Continue", type="primary", key="ob_next2", disabled=choice is None):
                users.save_team_size(user.id, choice)
                users.save_team_invites(user.id, typed)
                users.finish_onboarding(user.id)
                session.refresh()
                st.rerun()

        else:
            # Both questions answered but never finished: someone who stopped at the old API-key step.
            users.finish_onboarding(user.id)
            session.refresh()
            st.rerun()
