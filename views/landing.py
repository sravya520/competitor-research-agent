"""Public landing page. Markup lives in ui/landing.html, styles in ui/landing.css.

Every claim here is something the pipeline really does (DESIGN P7). Navigation uses plain links
(<a href>), which is what navigation should be; Streamlit's router picks the page from the URL.
"""

from datetime import date
from html import escape

import streamlit as st

from backend import config
from views import auth


def _free_runs() -> str:
    """The real limit (DESIGN P7): a number of free runs for the life of the account, not a daily allowance."""
    return f"{config.FREE_RUNS} free research" if config.FREE_RUNS == 1 else f"{config.FREE_RUNS} free researches"


def _nav_end(profile: tuple[str, str | None] | None) -> str:
    """Top-right of the nav: "Try it free" for visitors, the account (first name + Google photo) once signed in."""
    if profile is None:
        return '<a class="lp-btn lp-btn--sm" href="/app">Try it free</a>'
    first, photo = profile
    img = f'<img src="{escape(photo, quote=True)}" alt="" width="32" height="32">' if photo else ""
    return (
        f'<a class="lp-user" href="/app" aria-label="Open Moat as {escape(first, quote=True)}">'
        f'<span class="lp-user__av"><span class="lp-user__init" aria-hidden="true">{escape(first[:1].upper())}</span>{img}</span>'
        f'<span class="lp-user__name">{escape(first)}</span></a>'
    )


profile = auth.profile()
html = (config.ROOT / "ui" / "landing.html").read_text(encoding="utf-8")
for key, value in {
    "{{NAV_END}}": _nav_end(profile),
    "{{CTA}}": "Try it free" if profile is None else "Open Moat",
    "{{SIGNIN}}": "Sign in with Google. " if profile is None else "",
    "{{LIMIT}}": _free_runs().capitalize(),
    "{{LIMIT_LOWER}}": _free_runs(),
    "{{YEAR}}": str(date.today().year),
    "{{OPERATOR}}": config.OPERATOR_NAME or "Moat",
    "{{CONTACT}}": config.CONTACT_EMAIL or "",
}.items():
    html = html.replace(key, value)

st.html(html)

# Interactions (GSAP, vendored under static/). Served by Streamlit's static server at /app/static.
# The page is complete without this; it only adds motion. ?v= busts the browser cache on edits.
_js = config.ROOT / "static" / "landing.js"
st.html(f'<script src="/app/static/landing.js?v={int(_js.stat().st_mtime)}"></script>', unsafe_allow_javascript=True)
