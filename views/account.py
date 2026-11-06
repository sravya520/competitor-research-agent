"""Account page: shows what we store about the user and lets them delete it all."""

import streamlit as st

from backend import config, users
from views import auth, chrome, onboarding

user = auth.require_user()
chrome.sidebar(user)

st.title("Account")
st.subheader("What we store about you")
st.markdown(
    f"- **Email:** {user.email}\n"
    f"- **Name:** {user.name or 'Not provided'}\n"
    f"- **Why you use the tool:** {user.use_case if user.use_case and user.use_case != onboarding.SKIPPED else 'Not answered'}\n"
    f"- **Team size:** {user.team_size if user.team_size and user.team_size != onboarding.SKIPPED else 'Not answered'}\n"
    f"- **Accepted terms version:** {config.LEGAL_VERSION}"
)
st.caption(
    "We also keep your 10 most recent researches, including any report you generate, and delete each one when you "
    "delete it, or after 24 hours at the latest. See the Privacy Policy for the full list."
)

st.subheader("Delete your account")
st.write(
    "This permanently deletes your account, your saved researches and anything else we hold about you, including "
    "any API key you saved with an earlier version. You can sign up again later, "
    "but you will start fresh. It can't be undone."
)
with st.expander("Delete my account"):
    confirm = st.checkbox("I understand this can't be undone.")
    if st.button("Delete my account permanently", key="delete_account"):
        if confirm:
            users.delete_user(user.id)
            st.session_state["account_deleted"] = True  # shown on the sign-in card (logout reruns the page)
            auth.sign_out()
            st.rerun()
        else:
            st.error("Tick the box to confirm.")

chrome.footer()
