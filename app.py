"""Streamlit UI for the competitor research pipeline.

Streamlit reruns this entire script top-to-bottom on every interaction —
typing in a box, clicking a button, checking a checkbox. That means the
actual research (identify -> research -> verify -> check) must run exactly
ONCE per company and its result must be stashed in st.session_state;
otherwise ticking a checkbox during review would silently re-run the whole
agent from scratch.

The pipeline functions themselves (pipeline.py, evaluate.py, report.py,
tools.py) know nothing about Streamlit -- this file is the only thing that
does, which is what main.py's CLI and this UI are both able to share.
"""

import os

import streamlit as st

# config.py reads GEMINI_API_KEY / TAVILY_API_KEY from os.environ the moment
# it's imported (populated locally via a .env file, which is gitignored and
# never reaches a deployed server). Streamlit Cloud has its own secrets
# system instead. Bridging st.secrets into os.environ here — before the
# pipeline import below triggers config.py — lets both paths work without
# config.py (or main.py's CLI) ever needing to know Streamlit exists.
for _key in ("GEMINI_API_KEY", "TAVILY_API_KEY"):
    if _key not in os.environ and _key in st.secrets:
        os.environ[_key] = st.secrets[_key]

import evaluate
import pipeline
import report as report_module
import tools

st.set_page_config(page_title="Competitor Research Agent", page_icon="🔍")
st.title("Competitor Research Agent")
st.caption(
    "Identifies a company, researches competitors, independently verifies "
    "them, and lets you review before a report is written. Usually takes "
    "30-90 seconds."
)

# --- one-time state so a rerun (checkbox click, etc.) doesn't lose results ---
for key in ("stage", "identity", "research", "verified", "excluded", "problems",
            "company_name", "company_url", "report_text"):
    st.session_state.setdefault(key, None)
if st.session_state["stage"] is None:
    st.session_state["stage"] = "input"


def reset() -> None:
    """Clear everything so a new company starts from a clean slate."""
    for key in ("identity", "research", "verified", "excluded", "problems", "report_text"):
        st.session_state[key] = None
    st.session_state["stage"] = "input"


# --- Step 0/1/2: identify, research, verify -- runs once per company ---
with st.form("company_form"):
    company_name = st.text_input("Company or startup name")
    company_url = st.text_input(
        "Company website or LinkedIn URL (optional, but strongly recommended)",
        help="Anchors identity to a real page instead of guessing from the "
             "name alone -- important for small or common-named companies.",
    )
    submitted = st.form_submit_button("Research")

if submitted:
    if not company_name.strip():
        st.error("Enter a company name first.")
    else:
        reset()
        tools.reset_sources()
        st.session_state["company_name"] = company_name.strip()
        st.session_state["company_url"] = company_url.strip()

        with st.status("Identifying the company...", expanded=True) as status:
            tools.set_progress_hook(status.write)
            identity = pipeline.identify_company(
                st.session_state["company_name"], st.session_state["company_url"]
            )

            if identity is None:
                status.update(label="Could not confirm identity", state="error")
                st.session_state["stage"] = "identity_failed"
            elif not identity.confident_match:
                status.update(label="Identity is ambiguous", state="error")
                st.session_state["identity"] = identity
                st.session_state["stage"] = "identity_ambiguous"
            else:
                status.update(label=f"Confirmed: {identity.description[:80]}...",
                               state="complete")
                st.session_state["identity"] = identity
                st.session_state["stage"] = "researching"

        if st.session_state["stage"] == "researching":
            with st.status("Researching competitors...", expanded=True) as status:
                tools.set_progress_hook(status.write)
                research = pipeline.research_competitors(
                    st.session_state["company_name"], identity
                )

                if research is None:
                    status.update(label="Ran out of tool calls before finishing",
                                   state="error")
                    st.session_state["stage"] = "research_failed"
                else:
                    status.write("Independently verifying each competitor...")
                    verifications = pipeline.verify_competitors(
                        st.session_state["company_name"], identity, research.competitors
                    )
                    verified, excluded = pipeline.apply_verifications(
                        research.competitors, verifications
                    )

                    problems = evaluate.run_checks(verified, tools.sources_consulted())
                    removed = evaluate.drop_fabricated_sources(verified, tools.sources_consulted())
                    if removed:
                        problems.append(f"Removed {removed} fabricated source URL(s).")

                    status.update(label=f"Found {len(verified)} verified competitor(s)",
                                  state="complete")

                    st.session_state["research"] = research
                    st.session_state["verified"] = verified
                    st.session_state["excluded"] = excluded
                    st.session_state["problems"] = problems
                    st.session_state["stage"] = "review"

# --- Terminal states: identity failed / ambiguous / research failed ---
if st.session_state["stage"] == "identity_failed":
    st.error("Could not confirm the company's identity within the allowed tool calls.")

elif st.session_state["stage"] == "identity_ambiguous":
    identity = st.session_state["identity"]
    st.warning(
        f'Could not confidently identify a single company for '
        f'"{st.session_state["company_name"]}".'
    )
    st.write(f"**What was found:** {identity.description}")
    st.write(f"**Location:** {identity.location or 'unknown'}")
    st.write(f"**Why it's ambiguous:** {identity.ambiguity_note}")
    st.info(
        "Stopping rather than guessing which company you meant. Try again "
        "with a more specific name, or — better — paste the company's URL "
        "above; it outranks search and resolves this directly."
    )

elif st.session_state["stage"] == "research_failed":
    st.error("The agent didn't finish researching within its allowed tool calls.")

# --- Step 3: human review ---
elif st.session_state["stage"] == "review":
    identity = st.session_state["identity"]
    verified = st.session_state["verified"]
    excluded = st.session_state["excluded"]
    problems = st.session_state["problems"]

    st.subheader("The company")
    st.write(identity.description)

    if problems:
        st.warning("Automatic checks flagged:\n" + "\n".join(f"- {p}" for p in problems))

    if excluded:
        with st.expander(f"Automatically excluded ({len(excluded)})"):
            for name, reason in excluded:
                st.write(f"**{name}** — {reason}")

    if not verified:
        st.error("No competitors passed verification. Try a more specific name or URL.")
    else:
        st.subheader(f"Review {len(verified)} competitor(s)")
        st.caption("Uncheck any you want removed before the report is generated.")

        keep_flags = []
        for i, competitor in enumerate(verified):
            keep = st.checkbox(
                f"**{competitor.name}** — {competitor.positioning}",
                value=True,
                key=f"keep_{i}",
            )
            keep_flags.append(keep)
            with st.expander("Details", expanded=False):
                st.write(f"**Why relevant:** {competitor.why_relevant}")
                st.write(f"**Target customers:** {competitor.target_customers}")
                st.write(f"**Pricing:** {competitor.pricing or 'Not publicly available'}")
                st.write(f"**Sources:** {', '.join(competitor.sources) or 'none cited'}")

        if st.button("Generate report", type="primary"):
            final = [c for c, keep in zip(verified, keep_flags) if keep]
            removed_now = [c.name for c, keep in zip(verified, keep_flags) if not keep]
            final_excluded = excluded + [(name, "Removed by human reviewer.") for name in removed_now]

            if not final:
                st.error("Every competitor was removed — nothing to report.")
            else:
                st.session_state["report_text"] = report_module.build_report(
                    company_name=st.session_state["company_name"],
                    company_url=st.session_state["company_url"],
                    identity=identity,
                    research=st.session_state["research"],
                    competitors=final,
                    excluded=final_excluded,
                    sources=tools.sources_consulted(),
                )

# --- Step 4: show and download the report ---
if st.session_state["report_text"]:
    st.subheader("Report")
    st.download_button(
        "Download as Markdown",
        data=st.session_state["report_text"],
        file_name=f"report-{st.session_state['company_name'].lower().replace(' ', '-')}.md",
        mime="text/markdown",
    )
    st.markdown(st.session_state["report_text"])

if st.session_state["stage"] != "input":
    st.divider()
    if st.button("Start a new search"):
        reset()
        st.rerun()
