"""Renders legal/*.md with the operator's details filled in."""

import streamlit as st

from backend import config
from views import chrome


def render(doc: str) -> None:
    chrome.header_for_legal()
    missing = [
        name
        for name, value in (
            ("OPERATOR_NAME", config.OPERATOR_NAME),
            ("CONTACT_EMAIL", config.CONTACT_EMAIL),
            ("JURISDICTION", config.JURISDICTION),
        )
        if not value
    ]
    if missing:
        st.warning(
            "Draft: these details aren't set yet, so this page shows placeholders: "
            + ", ".join(missing)
            + ". The site owner must set them, and have a lawyer review this text, before launch."
        )
    text = (config.ROOT / "legal" / f"{doc}.md").read_text(encoding="utf-8")
    for key, value in {
        "{{VERSION}}": config.LEGAL_VERSION,
        "{{OPERATOR}}": config.OPERATOR_NAME or "[operator name]",
        "{{EMAIL}}": config.CONTACT_EMAIL or "[contact email]",
        "{{JURISDICTION}}": config.JURISDICTION or "[jurisdiction]",
    }.items():
        text = text.replace(key, value)
    st.markdown(text)
    chrome.footer()
