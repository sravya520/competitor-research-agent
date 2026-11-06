"""Shared page chrome: the left rail for signed-in pages, a brand bar for the legal pages, and the footer.

There is no top bar. Navigation lives in the left rail (ui/workspace.css); sign-in, consent and
onboarding screens show nothing but their own column.
"""

import html
from datetime import date

import streamlit as st

from backend import config, jobs
from backend.users import UserInfo
from views import auth

BRAND = (
    '<header class="si-top"><a class="lp-nav__brand" href="/">'
    '<img class="lp-mark-img" src="/app/static/brand/mark.svg" width="32" height="32" alt="">'
    "Moat</a></header>"
)
RAIL_BRAND = (
    '<a class="ws-brand" href="/">'
    '<img class="lp-mark-img" src="/app/static/brand/mark.svg" width="32" height="32" alt="">Moat</a>'
)

_STATUS = {"running": "Researching", "review": "Ready to review", "failed": "Stopped"}


def header_for_legal() -> None:
    """The legal pages are public and have no rail, so they get a brand bar to get back home."""
    st.html(BRAND)


@st.cache_data(ttl=8, show_spinner=False)
def _recent(user_id: int) -> list[jobs.JobRow]:
    # Cached a few seconds: the rail redraws on every click, and a status label can be a few seconds old.
    return jobs.list_for(user_id)


def forget_recent() -> None:
    _recent.clear()


def open_job(job_id: str | None) -> None:
    """Go to a research (or, with None, to a blank new one). tool.py reads this flag first thing."""
    st.session_state["open_job"] = job_id or ""
    st.switch_page("views/tool.py")


def sidebar(user: UserInfo, active_job_id: str | None = None) -> None:
    """The left rail: brand, New research, previous research, then account and sign out at the bottom."""
    with st.sidebar:
        st.html(RAIL_BRAND)
        if st.button("New research", key="nav_new", type="tertiary", icon=":material/add:"):
            open_job(None)
        st.html('<p class="ws-label">Recent</p>')
        rows = _recent(user.id)
        # The list gets whatever height is left between New research and the footer and is clipped there,
        # so the rail never scrolls (ui/workspace.css).
        with st.container(key="ws_recent"):
            if not rows:
                st.html('<p class="ws-empty">Your research will show up here.</p>')
            for row in rows:
                active = row.id == active_job_id
                clicked = st.button(
                    row.company_name, key=f"nav_job_{row.id}", type="secondary" if active else "tertiary",
                    help=_STATUS.get(row.status, ""), width="stretch",
                )
                if clicked:
                    open_job(row.id)
        with st.container(key="ws_foot"):
            st.html(f'<p class="ws-user">{html.escape(user.email)}</p>')
            st.page_link("views/account.py", label="Account")
            st.button("Sign out", key="nav_signout", type="tertiary", on_click=auth.sign_out)
            st.html('<p class="ws-legal"><a href="/privacy">Privacy</a><a href="/terms">Terms</a></p>')


def footer() -> None:
    st.divider()
    with st.container(horizontal=True, gap="small"):
        st.page_link("views/privacy.py", label="Privacy Policy")
        st.page_link("views/terms.py", label="Terms of Use")
        if config.CONTACT_EMAIL:
            st.markdown(f"[Contact]({'mailto:' + config.CONTACT_EMAIL})")
    owner = config.OPERATOR_NAME or "Moat"
    st.caption(
        f"© {date.today().year} {owner}. Reports are AI-assisted and can be wrong. "
        "Check the sources before you rely on them."
    )
