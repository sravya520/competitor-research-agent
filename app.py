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
import failures  # stdlib-only, so it is safe to import before config.py

failures.bridge_secrets(st.secrets, os.environ)

from google.genai import errors

import evaluate
import memory
import pipeline
import recall
import report as report_module
from config import MODEL
from runstate import RunState

st.set_page_config(page_title="Competitor Research Agent", page_icon="🔍")
st.title("Competitor Research Agent")
st.caption(
    "Identifies a company, researches competitors, independently verifies "
    "them, and lets you review before a report is written. Usually takes "
    "30-90 seconds."
)

# --- one-time state so a rerun (checkbox click, etc.) doesn't lose results ---
for key in ("stage", "identity", "research", "verified", "excluded", "problems",
            "company_name", "company_url", "report_text", "run_logged",
            "identity_recalled", "candidates", "url_remembered", "run"):
    st.session_state.setdefault(key, None)

# Not in the loop above: None is falsy, and this one defaults to on.
st.session_state.setdefault("allow_recall", True)
if st.session_state["stage"] is None:
    st.session_state["stage"] = "input"


def reset() -> None:
    """Clear everything so a new company starts from a clean slate."""
    for key in ("identity", "research", "verified", "excluded", "problems",
                "report_text", "run_logged", "identity_recalled",
                "candidates", "url_remembered", "run"):
        st.session_state[key] = None
    st.session_state["allow_recall"] = True
    st.session_state["stage"] = "input"


# --- Step 0/1/2: identify, research, verify -- runs once per company ---

EXAMPLE_REPORT = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              "example-report.md")


def show_example_report() -> None:
    """Show the committed example report when the demo cannot run.

    The daily limit is shared across every visitor, so someone arriving
    late sees only an apology and no idea what the tool produces. This is a
    real report from an earlier run, so they can still judge the output.
    """
    try:
        with open(EXAMPLE_REPORT, encoding="utf-8") as handle:
            content = handle.read()
    except OSError:
        return  # Nothing to show, and this is already the failure path.

    st.info("That limit is shared across all visitors, so nothing was "
            "researched for you just now. Below is a saved example from an "
            "earlier run, kept in the repository, so you can still see what "
            "this tool produces. It is not a report about the company you "
            "entered.")
    with st.expander("Saved example report (not your result)", expanded=True):
        st.caption("Saved example: a different company, researched on an "
                   "earlier date. Not your result.")
        st.markdown(content)


def research_company() -> None:
    """Identify, research, verify. Reads and writes st.session_state only.

    A function rather than inline script because there are now two ways in:
    submitting the form, and accepting a website this ledger remembered.
    Streamlit reruns this file top to bottom on every interaction, so both
    entry points have to sit above the review section further down, which
    renders whatever this leaves behind.

    This app runs on ONE shared API key for every visitor -- there is no
    per-user quota. Free-tier limits are real and we hit them ourselves
    during development, so a visitor arriving after the key is already near
    its daily cap is an expected case, not a rare edge case. It is caught
    here and shown as a plain message instead of Streamlit's default crash
    screen; the retries in config.py, tools.py and pipeline.py have already
    absorbed anything short-lived, so an error reaching this point means
    they were exhausted and retrying again immediately will not help.
    """
    try:
        with st.status("Identifying the company...", expanded=True) as status:
            st.session_state["run"].progress = status.write
            identity, identity_recalled = recall.establish_identity(
                st.session_state["company_name"],
                st.session_state["company_url"],
                st.session_state["run"],
                allow_recall=st.session_state["allow_recall"],
            )
            st.session_state["identity_recalled"] = identity_recalled
            if identity_recalled:
                status.write(
                    f"Reusing the identity established on "
                    f"{identity_recalled['established_at'][:10]} "
                    f"({identity_recalled['age_days']:.0f} days ago). Tick "
                    f"\"Re-establish identity\" above to check it live instead."
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
                st.session_state["run"].progress = status.write
                research = pipeline.research_competitors(
                    st.session_state["company_name"], identity,
                    st.session_state["run"]
                )

                if research is None:
                    status.update(label="Ran out of tool calls before finishing",
                                  state="error")
                    st.session_state["stage"] = "research_failed"
                else:
                    status.write("Independently verifying each competitor...")
                    verifications = pipeline.verify_competitors(
                        st.session_state["company_name"], identity,
                        research.competitors, st.session_state["run"]
                    )
                    verified, excluded = pipeline.apply_verifications(
                        research.competitors, verifications
                    )

                    problems = evaluate.run_checks(verified, st.session_state["run"].sources_consulted())
                    removed = evaluate.drop_fabricated_sources(
                        verified, st.session_state["run"].sources_consulted())
                    if removed:
                        problems.append(f"Removed {removed} fabricated source URL(s).")
                    # After stripping fabricated URLs above, not before --
                    # a fake source shouldn't count toward corroboration.
                    problems += evaluate.check_source_corroboration(verified)
                    problems += evaluate.check_precise_claims_are_corroborated(verified)

                    status.update(label=f"Found {len(verified)} verified competitor(s)",
                                  state="complete")

                    st.session_state["research"] = research
                    st.session_state["verified"] = verified
                    st.session_state["excluded"] = excluded
                    st.session_state["problems"] = problems
                    st.session_state["stage"] = "review"

    except errors.APIError as exc:
        # Logged unconditionally: Streamlit Cloud's "Manage app" panel
        # captures stdout, and this is the only trace of a deployed
        # failure. Discarding it is what made a transient 503 look like a
        # defect in the report.
        print(failures.api_error_log_line(exc), flush=True)
        st.session_state["stage"] = "input"
        st.error(failures.api_error_message(exc.code))

        if exc.code == 429:
            show_example_report()

    except Exception as exc:  # noqa: BLE001 - last resort, and it logs
        # Anything that is not a provider API error previously reached the
        # user as a raw traceback: a Tavily failure, a dropped connection,
        # a missing optional key, or a genuine bug. Streamlit's own
        # control flow (RerunException, StopException) derives from
        # BaseException rather than Exception, so it passes through here
        # untouched.
        print(failures.unexpected_error_log_line(exc), flush=True)
        st.session_state["stage"] = "input"
        st.error(failures.unexpected_error_message())


with st.form("company_form"):
    company_name = st.text_input("Company or startup name")
    company_url = st.text_input(
        "Company website or LinkedIn URL (optional, but strongly recommended)",
        help="Anchors identity to a real page instead of guessing from the "
             "name alone -- important for small or common-named companies.",
    )
    fresh_identity = st.checkbox(
        "Re-establish identity",
        value=False,
        help="By default, a company researched here before under its own "
             "domain reuses that identity if it is recent. Tick this to "
             "look it up live instead, for instance if the company has "
             "rebranded, moved or been acquired since.",
    )
    submitted = st.form_submit_button("Research")

if submitted:
    if not company_name.strip():
        st.error("Enter a company name first.")
    else:
        reset()

        # One RunState per research, created INSIDE the script run and kept
        # in session_state: this visitor's ledger, progress output and model
        # versions, reachable by no other session. It must outlive this
        # rerun, because the report is written from the review screen, which
        # is a later one.
        st.session_state["run"] = RunState()
        st.session_state["company_name"] = company_name.strip()
        st.session_state["company_url"] = company_url.strip()
        st.session_state["allow_recall"] = not fresh_identity

        # A name with no URL cannot find its own history, because runs are
        # filed under a domain. So ask the ledger by name and let the user
        # confirm; nothing is chosen for them, however few the matches.
        candidates = ([] if st.session_state["company_url"]
                      else recall.find_candidates(st.session_state["company_name"]))

        if candidates:
            st.session_state["candidates"] = candidates
            st.session_state["stage"] = "choose_url"
        else:
            research_company()

# --- Remembered websites: memory suggests, the user confirms ---
if st.session_state["stage"] == "choose_url":
    st.info(f'You have researched "{st.session_state["company_name"]}" here '
            f'before.')
    st.caption("Pick the one you mean and the run continues as if you had "
               "typed that URL. Each age is shown so you can judge how "
               "current it is; nothing is selected for you, because two "
               "unrelated companies can share a name.")

    for number, candidate in enumerate(st.session_state["candidates"]):
        if st.button(
            f"{candidate['website']}  ·  last run "
            f"{candidate['run_at'][:10]} ({candidate['age_days']:.0f} days ago)",
            key=f"candidate_{number}",
        ):
            st.session_state["company_url"] = candidate["website"]
            st.session_state["url_remembered"] = candidate
            st.session_state["candidates"] = None
            research_company()
            st.rerun()

    if st.button("None of these", key="candidate_none"):
        st.session_state["candidates"] = None
        research_company()
        st.rerun()

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
    st.caption(
        f"Location: {identity.location or 'not established'}"
        + (f" · Website: {identity.website}" if identity.website else "")
    )

    # Shown here as well as in the report: someone reviewing competitors
    # should know the identity underneath them was not checked today.
    if st.session_state["identity_recalled"]:
        st.caption(
            "Identity established on "
            f"{st.session_state['identity_recalled']['established_at'][:10]} "
            f"({st.session_state['identity_recalled']['age_days']:.0f} days "
            "ago) and reused, not re-established today."
        )

    if problems:
        st.warning("Automatic checks flagged:\n" + "\n".join(f"- {p}" for p in problems))

    if excluded:
        with st.expander(f"Automatically excluded ({len(excluded)})"):
            for name, reason in excluded:
                st.write(f"**{name}**: {reason}")

    if not verified:
        st.error("No competitors passed verification. Try a more specific name or URL.")
    else:
        st.subheader(f"Review {len(verified)} competitor(s)")
        st.caption("Uncheck any you want removed before the report is generated.")

        keep_flags = []
        for i, competitor in enumerate(verified):
            keep = st.checkbox(
                f"**{competitor.name}**: {competitor.positioning}",
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
                    sources=st.session_state["run"].sources_consulted(),
                    identity_recalled=st.session_state["identity_recalled"],
                    url_remembered=st.session_state["url_remembered"],
                )

                # One ledger entry per run. Streamlit leaves this review UI
                # on screen after the report appears, so the button can be
                # pressed again -- without the flag that would append a
                # second record for the same research. Best-effort, like the
                # CLI: the report is already built, and nothing reads the
                # ledger yet, so a write failure is logged and swallowed.
                if not st.session_state["run_logged"]:
                    try:
                        memory.record_run(
                            company_name=st.session_state["company_name"],
                            company_url=st.session_state["company_url"],
                            identity=identity,
                            competitors=final,
                            excluded_auto=excluded,
                            removed_by_human=removed_now,
                            problems=problems,
                            sources=st.session_state["run"].sources_consulted(),
                            model=MODEL,
                            model_resolved=st.session_state["run"].model_versions(),
                            retrieval_provider=getattr(
                                st.session_state["run"].provider, "name", ""),
                            url_source=(
                                "remembered"
                                if st.session_state["url_remembered"]
                                else "typed" if st.session_state["company_url"]
                                else "none"),
                            url_remembered_from=(
                                st.session_state["url_remembered"]["run_at"]
                                if st.session_state["url_remembered"] else ""),
                            # Carried forward, not restamped: an identity
                            # must not become immortal by being reused.
                            identity_established_at=(
                                st.session_state["identity_recalled"]
                                ["established_at"]
                                if st.session_state["identity_recalled"]
                                else ""),
                        )
                        st.session_state["run_logged"] = True
                    except OSError as exc:
                        print(f"[memory] run not recorded ({exc})", flush=True)

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
