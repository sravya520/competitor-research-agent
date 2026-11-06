"""Sign-in glue between Streamlit's native Google login (st.login / st.user) and backend.users.

Flow: not signed in -> sign-in card -> first time -> consent card -> the page runs.
Identity = Google's stable `sub` claim, and the email must be verified by Google.
"""

import html

import streamlit as st

from backend import config, users, usage
from backend.users import UserInfo
from views import onboarding, session

DEV_SUB = "dev-local"  # only reachable through _dev_auth_on()

LOGO = '<img class="si-logo" src="/app/static/brand/mark.svg" width="40" height="40" alt="Moat">'


def _dev_auth_on() -> bool:
    """The sign-in bypass applies to this connection: CRA_DEV_AUTH=1 and host, origin and client are all local."""
    return config.dev_auth_allowed(st.context.headers, st.context.ip_address)


def _auth_configured() -> bool:
    """True only when every key st.login needs is present, so a half-filled [auth] block can't show a broken button."""
    try:
        auth = st.secrets["auth"]
        return all(auth.get(k) for k in ("redirect_uri", "cookie_secret", "client_id", "client_secret", "server_metadata_url"))
    except Exception:  # no secrets.toml, or no [auth] table
        return False


def _google_identity() -> tuple[str, str, str | None] | None:
    """(sub, email, name) of the signed-in Google user, or None."""
    if not _auth_configured() or not st.user.get("is_logged_in", False):
        return None
    if not st.user.get("email_verified", False):
        return None
    return st.user.get("sub"), st.user.get("email"), st.user.get("name")


def profile() -> tuple[str, str | None] | None:
    """(first name, Google photo URL or None) of the signed-in user, or None. Reads only the sign-in cookie,
    never the database, so the public landing page can show who is signed in at no cost."""
    ident = _google_identity()
    if ident is None:
        if st.session_state.get("dev_signed_in") and _dev_auth_on():
            return "Local", None
        return None
    _, email, name = ident
    first = (name or "").split(" ")[0] or (email or "").split("@")[0] or "Account"
    photo = st.user.get("picture")
    # Only ever put a Google-hosted https image in the page.
    if not (isinstance(photo, str) and photo.startswith("https://") and photo.split("/")[2].endswith(".googleusercontent.com")):
        photo = None
    return first, photo


def current_user() -> UserInfo | None:
    """The signed-in user (created in the database on first sign-in), or None."""
    ident = _google_identity()
    if ident is None and st.session_state.get("dev_signed_in") and _dev_auth_on():
        ident = (DEV_SUB, "dev@localhost", "Local Dev")
    if ident is None:
        session.clear()
        return None
    hit = session.cached(ident[0])
    if hit is not None:
        return hit  # no database call: anything that changes the user calls session.refresh()
    info = users.upsert_login(*ident)
    session.store(ident[0], info)
    return info


def sign_out() -> None:
    session.clear()
    st.session_state.pop("dev_signed_in", None)
    if _google_identity() is not None:
        st.logout()  # ends the Google session cookie and reruns


def _sign_in_card() -> None:
    """One quiet column (ui/signin.css, DESIGN V11): logo, heading, one button, fine print. Everything
    shares one left edge, like Tally's sign-in."""
    with st.container(key="si"):
        if st.session_state.pop("account_deleted", False):
            st.success("Your account and usage history were deleted.")
        st.html(
            f'<div class="si-copy">{LOGO}<h1>Find competitors. See the proof.</h1>'
            "<p>Name a company and get its real competitors, each with sources you can open.</p></div>"
        )
        if _auth_configured():
            st.button("Continue with Google", on_click=st.login, key="si_google")
            if st.user.get("is_logged_in", False) and not st.user.get("email_verified", False):
                st.error("Google says this email address isn't verified, so we can't sign you in with it.")
        elif not _dev_auth_on():
            st.error("Sign-in isn't set up on this server yet. The site owner needs to add Google credentials.")
        st.html(
            '<p class="si-fine">We use your Google email and name to create your account, and we never see '
            'your password. First time here? You will confirm the <a href="/terms">Terms of Use</a> and '
            '<a href="/privacy">Privacy Policy</a> next.</p>'
        )
        if _dev_auth_on():
            st.warning("Local development mode: sign-in is bypassed. This must never be on in production.")
            if st.button("Continue as local dev user", key="dev_login"):
                st.session_state["dev_signed_in"] = True
                st.rerun()


def _consent_card(user: UserInfo) -> None:
    with st.container(key="si"):
        st.html(
            f'<div class="si-copy">{LOGO}<h1>One more step</h1>'
            f"<p>You're signed in as {html.escape(user.email)}. Please confirm before you start.</p></div>"
        )
        # Both boxes start unchecked and are required: consent must be a choice, not a default.
        agreed = st.checkbox("I have read and agree to the Terms of Use and the Privacy Policy.")
        adult = st.checkbox("I am 18 years old or older.")
        st.html(
            '<p class="si-fine">Read the <a href="/terms">Terms of Use</a> and the '
            '<a href="/privacy">Privacy Policy</a>.</p>'
        )
        if st.button("Continue", type="primary", disabled=not (agreed and adult)):
            users.accept_terms(user.id)
            session.refresh()  # accepted_current_terms is now true
            st.rerun()
        st.button("Sign out", type="tertiary", on_click=sign_out)


def require_user() -> UserInfo:
    """Gate for protected pages: returns the user, or renders the sign-in / consent step and stops."""
    user = current_user()
    if user is None:
        _sign_in_card()
        st.stop()
    if not user.accepted_current_terms:
        _consent_card(user)
        st.stop()
    if not user.onboarded:
        onboarding.render(user)
        st.stop()
    return user


def runs_left(user: UserInfo) -> int:
    return usage.remaining(user.id)
