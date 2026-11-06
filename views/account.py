"""Account page: shows exactly what we store about the user, manages their own API keys, and lets them delete it all."""

import streamlit as st

from backend import config, users
from views import auth, chrome, onboarding, session

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
st.caption("We don't keep your finished reports. See the Privacy Policy for the full list.")

st.subheader("Your API keys")
hints = users.key_hints(user.id)
if hints:
    st.write(f"Research uses your own keys: AI key ending {hints[0][1:]}, search key ending {hints[1][1:]}. They are stored encrypted.")
    if st.button("Remove my keys", key="remove_keys"):
        users.clear_keys(user.id)
        session.refresh()
        st.rerun()
    with st.expander("Replace my keys"):
        if onboarding.keys_form(user.id, prefix="acct_replace", submit_label="Save new keys"):
            session.refresh()
            st.rerun()
else:
    st.write(
        "Research needs an AI key and a search key. Add yours so reports use your own credits, "
        "with no limit from us."
    )
    if onboarding.keys_form(user.id, prefix="acct_keys", submit_label="Save keys"):
        session.refresh()
        st.rerun()

st.subheader("Delete your account")
st.write(
    "This permanently deletes your account, saved keys and any research in progress. You can sign up again later, "
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
