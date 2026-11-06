"""The Moat workspace (served at /app): a composer to start a research, and each research as a page.

The research does NOT run inside this page. On Vercel a Streamlit session lasts under a minute and a
run takes 30-90 s, so a run started here was lost when the browser reconnected. Instead this page
starts a job (runner.py, a background thread) and reads its progress and results from the database
(backend/jobs.py). The open research is named in the URL (?job=...), so a reload or reconnect
finds the same one again.

The pipeline modules know nothing about Streamlit; this file and views/ are the only ones that do.
"""

import base64
import html
import os
from pathlib import Path
from datetime import datetime, timezone
from urllib.parse import urlparse

import streamlit as st

import report as report_module
import runner
from backend import jobs, usage, users
from schemas import CompanyIdentity, CompetitorResearch
from views import auth, chrome, session

user = auth.require_user()  # sign-in, consent and onboarding gates: stops here until all are done

# The rail sets this flag to open a research (or a blank new one); apply it before anything draws.
if "open_job" in st.session_state:
    _target = st.session_state.pop("open_job")
    if _target:
        st.query_params["job"] = _target
    else:
        st.query_params.pop("job", None)

job = jobs.get_for_user(user.id, st.query_params.get("job"))
chrome.sidebar(user, job.id if job else None)

# (id, name, one line, ready). Ten more ways to look at competitors, after HubSpot's competitive
# analysis templates. Only "general" (the full default analysis) is built; the rest are listed, not faked.
METHODS = [
    ("general", "General", "The full analysis: who the competitors are and how they compare, with sources.", True),
    ("positioning", "Positioning map", "Plot you and your rivals on the two features that matter most.", False),
    ("strategy", "Strategic overview", "Each rival's goals, strengths and recent moves on one page.", False),
    ("content", "Content marketing", "How rivals use content and channels to win attention.", False),
    ("side-by-side", "Side by side", "You against one rival, point by point.", False),
    ("battle-card", "Battle card", "A cheat sheet for selling against one rival.", False),
    ("features", "Feature comparison", "Features across many rivals in a single grid.", False),
    ("scorecard", "Scorecard", "Score rivals on the criteria you choose.", False),
    ("swot", "SWOT", "Strengths, weaknesses, opportunities and threats.", False),
    ("categories", "Category comparison", "Compare rivals feature category by feature category.", False),
    ("reviews", "Review tracker", "What customers praise and complain about.", False),
]
METHOD_NAMES = {m[0]: m[1] for m in METHODS}


def _start(name: str, url: str, method: str) -> None:
    """Pick whose keys pay for this run, reserve it, and start the job. Reruns the page on success."""
    if user.has_own_keys:
        mode = "own"
    elif user.unlimited:
        if not (os.environ.get("GEMINI_API_KEY") and os.environ.get("TAVILY_API_KEY")):
            st.error("Our research keys aren't set on this server right now.")
            return
        mode = "house"  # allow-listed: no free-run count, no daily or global cap
    elif user.free_runs_left > 0:
        if not (os.environ.get("GEMINI_API_KEY") and os.environ.get("TAVILY_API_KEY")):
            st.error("The free run isn't available on this server right now. You can add your own API keys on the Account page.")
            return
        quota = usage.try_consume(user.id)
        if not quota.ok:
            st.warning(
                "Our shared credits are used up for today. Please try again after 00:00 UTC, "
                "or add your own API keys on the Account page to continue now."
            )
            return
        if not users.consume_free_run(user.id):
            st.warning("You've used your free run. Add your own API keys to run more research.")
            return
        mode = "house"
    else:
        st.warning("You've used your free run. Add your own API keys to run more research.")
        return
    job_id = jobs.create(user.id, name, url, mode, method)
    runner.start(job_id)
    session.refresh()  # free runs left changed
    chrome.forget_recent()
    for key in ("method", "cmp_name", "cmp_url"):
        st.session_state.pop(key, None)
    st.query_params["job"] = job_id
    st.rerun()


def _method_card(method_id: str, title: str, blurb: str, ready: bool, selected: bool) -> None:
    """One method card. The card is HTML; a transparent button laid over it carries the click."""
    state = "is-selected" if selected else "" if ready else "is-soon"
    tag = '<span class="ws-tag">Soon</span>' if not ready else ""
    check = '<span class="ws-card__check i i-check" aria-hidden="true"></span>' if selected else ""
    with st.container(key=f"mcard_{method_id}"):
        st.html(
            f'<div class="ws-card {state}"><span class="ws-card__top"><span class="ws-card__t">{html.escape(title)}</span>'
            f"{tag}{check}</span><span class=\"ws-card__d\">{html.escape(blurb)}</span></div>"
        )
        if ready and st.button(f"Use {title}", key=f"pick_{method_id}"):
            if selected:
                st.session_state.pop("method", None)
            else:
                st.session_state["method"] = method_id
            st.rerun()


def _composer() -> None:
    method = st.session_state.get("method")
    st.html('<div class="ws-hero"><h1>Who are we researching?</h1></div>')
    with st.container(key="composer"):
        left, right = st.columns(2, gap="small")
        name = left.text_input("Company name", key="cmp_name", placeholder="Company name",
                               label_visibility="collapsed")
        url = right.text_input("Company website", key="cmp_url", placeholder="Website or LinkedIn URL",
                               label_visibility="collapsed")
        with st.container(key="composer_bar", horizontal=True, vertical_alignment="center",
                          horizontal_alignment="distribute"):
            if method:
                if st.button(f"{METHOD_NAMES[method]}  ×", key="chip", help="Remove this method"):
                    st.session_state.pop("method", None)
                    st.rerun()
            else:
                st.html('<span class="ws-hint">Choose a method below</span>')
            # All three are needed: a method, the company name and its website.
            run = st.button("Start research", type="primary", key="run",
                            disabled=not (name.strip() and url.strip() and method))
    if run:
        _start(name.strip(), url.strip(), method)

    if not (user.has_own_keys or user.unlimited) and user.free_runs_left <= 0:
        st.warning("You've used your free run. Add your own API keys to run more research.")
        st.page_link("views/account.py", label="Add your API keys")

    st.html('<p class="ws-label ws-label--methods">Methods</p>')
    for i in range(0, len(METHODS), 3):
        for col, (mid, title, blurb, ready) in zip(st.columns(3, gap="small"), METHODS[i:i + 3]):
            with col:
                _method_card(mid, title, blurb, ready, selected=(mid == method))


_FAILURES = {
    "identity_failed": "Could not confirm the company's identity within the allowed tool calls.",
    "research_failed": "The agent didn't finish researching within its allowed tool calls.",
    "quota": "The research API has hit its usage limit. Please try again in a while, or check the plan on your own API keys.",
    "api_error": "Something went wrong talking to the research API (a temporary issue, not a bug in the report). Please try again in a moment. If you use your own keys, check them on the Account page.",
    "own_keys_unsupported": "Running on your own API keys is not available in this build yet. It needs the research pipeline to accept per-run keys.",
    "keys_unreadable": "We couldn't read your saved API keys. Please enter them again on the Account page.",
    "error": "Something went wrong on our side. Please try again.",
}


STEPS = ["Identify the company", "Find competitors", "Verify and check sources"]
STAGE_INDEX = {"identify": 0, "research": 1, "verify": 2}


def _say(line: str) -> str:
    """Turn a raw pipeline log line into one plain sentence for the loading screen."""
    if line.startswith("[search] "):
        return f"Searching the web for “{line[9:].strip()}”"
    if line.startswith("[extract] "):
        host = urlparse(line[10:].strip()).netloc or line[10:].strip()
        return f"Reading {host.removeprefix('www.')}"
    if line.startswith("Identifying"):
        return "Working out which company this is"
    if line.startswith("Confirmed"):
        return "Company confirmed"
    if line.startswith("Researching competitors"):
        return "Looking for competitors"
    if line.startswith("Independently verifying"):
        return "Checking each competitor on its own"
    if line.startswith("Found "):
        return line.replace("verified competitor(s)", "competitors worth reviewing")
    return line


def _steps_html(active: int) -> str:
    rows = []
    for i, name in enumerate(STEPS):
        if i < active:
            rows.append(f'<li class="is-done"><span class="i i-check ld-done" aria-hidden="true"></span>{name}<span class="ld-sr"> (done)</span></li>')
        elif i == active:
            rows.append(f'<li class="is-active" aria-current="step"><span class="ld-dot" aria-hidden="true"></span>{name}</li>')
        else:
            rows.append(f'<li><span class="ld-dot ld-dot--idle" aria-hidden="true"></span>{name}</li>')
    return f'<ol class="ld-steps">{"".join(rows)}</ol>'


@st.fragment(run_every=2)
def _progress(job_id: str) -> None:
    """The loading screen. Polls the job every 2 s; when it stops running the whole page reruns.

    The animated header never changes, so its pulse is not restarted by the polling; only the parts
    that carry new information are re-rendered."""
    current = jobs.get(job_id)
    if current is None or current.status != "running":
        chrome.forget_recent()
        st.rerun()
        return
    if jobs.claim_stale(job_id):  # the worker died with its server instance: resume from the last saved stage
        runner.start(job_id)
    said = [_say(line) for line in current.log]
    now = said[-1] if said else "Getting started"
    recent = "".join(f"<p>› {html.escape(line)}</p>" for line in said[-6:])
    started = jobs.created_at(job_id)
    elapsed = int((datetime.now(timezone.utc) - started).total_seconds()) if started else 0
    with st.container(key="ld"):
        st.html('<div class="ld-head"><span class="ld-mark" aria-hidden="true"></span><span class="ld-label">Researching</span></div>')
        st.html(f'<p class="ld-now" role="status"><span class="ld-shimmer">{html.escape(now)}</span></p>')
        st.html(_steps_html(STAGE_INDEX.get(current.stage, 0)))
        st.html(f'<div class="ld-log" aria-label="Activity">{recent}</div>')
        st.html(f'<p class="ld-time">Elapsed {elapsed // 60:02d}:{elapsed % 60:02d}</p>')
    st.caption("You can leave this page open. If your connection drops, the research carries on and picks up here.")


def _review(current: jobs.Job) -> None:
    state = current.state
    identity = CompanyIdentity.model_validate(state["identity"])
    verified = runner.competitors_from(state)
    excluded = [tuple(pair) for pair in state.get("excluded", [])]
    problems = state.get("problems", [])

    if problems:
        st.warning("Automatic checks flagged:\n" + "\n".join(f"- {p}" for p in problems))
    if state.get("report_text"):
        return _report(current)  # the report has its own company and exclusions tabs

    st.subheader("The company")
    st.write(identity.description)
    st.caption(
        f"Location: {identity.location or 'not established'}"
        + (f" · Website: {identity.website}" if identity.website else "")
    )
    if excluded:
        with st.expander(f"Automatically excluded ({len(excluded)})"):
            for name, reason in excluded:
                st.write(f"**{name}** — {reason}")

    if not verified:
        st.error("No competitors passed verification. Try a more specific name or URL.")
        return

    st.subheader(f"Review {len(verified)} competitor(s)")
    st.caption("Uncheck any you want removed before the report is generated.")
    keep_flags = []
    for i, competitor in enumerate(verified):
        keep = st.checkbox(f"**{competitor.name}** — {competitor.positioning}", value=True, key=f"keep_{i}")
        keep_flags.append(keep)
        with st.expander("Details", expanded=False):
            st.write(f"**Why relevant:** {competitor.why_relevant}")
            st.write(f"**Target customers:** {competitor.target_customers}")
            st.write(f"**Pricing:** {competitor.pricing or 'Not publicly available'}")
            st.write(f"**Sources:** {', '.join(competitor.sources) or 'none cited'}")

    if st.button("Generate report", type="primary"):
        final = [c for c, keep in zip(verified, keep_flags) if keep]
        removed_now = [c.name for c, keep in zip(verified, keep_flags) if not keep]
        if not final:
            st.error("Every competitor was removed — nothing to report.")
            return
        text = report_module.build_report(
            company_name=current.company_name,
            company_url=current.company_url,
            identity=identity,
            research=CompetitorResearch.model_validate(state["research"]),
            competitors=final,
            excluded=excluded + [(name, "Removed by human reviewer.") for name in removed_now],
            sources=state.get("sources", []),
        )
        jobs.merge_state(current.id, report_text=text)  # kept only until deleted or 24 h (privacy policy)
        st.rerun()


# Downloads are made in the browser (static/download.js), not by st.download_button. That button serves
# the file from the server's memory, and on Vercel the request for it can land on a different instance
# than the one that made it ("file not available on site"). A Blob built from text on the page cannot go missing.
_DOWNLOAD_JS = Path(__file__).resolve().parent.parent / "static" / "download.js"


def _download_button(company_name: str, text: str) -> str:
    slug = "".join(ch if ch.isalnum() else "-" for ch in company_name.lower()).strip("-") or "report"
    data = base64.b64encode(text.encode("utf-8")).decode("ascii")
    return (
        f'<button type="button" class="rp-dl" data-name="report-{html.escape(slug)}.md" data-b64="{data}">'
        '<span class="i i-download" aria-hidden="true"></span>'
        '<span class="rp-dl__t">Download as Markdown</span><span class="rp-dl__ok" aria-live="polite">Saved</span></button>'
    )


# The report's "## " sections become tabs. The first is about the company that was researched, which is
# not always the user's own, so it is "Overview" rather than "My company". The rest are named for what
# they hold; any heading not listed keeps its own text.
_TAB_NAMES = {
    "The company": "Overview",
    "Gaps and opportunities": "Opportunities",
    "Potential threats": "Threats",
    "Excluded from this report": "Excluded",
    "All sources consulted": "Sources",
}


def _sections(text: str) -> list[tuple[str, str]]:
    """Split the report Markdown at its "## " headings into (tab name, body). The "# " title and the
    date line before the first heading are dropped: the page already shows the company's name."""
    parts: list[list] = []
    for line in text.splitlines():
        if line.startswith("## "):
            parts.append([line[3:].strip(), []])
        elif parts:
            parts[-1][1].append(line)
    return [(_TAB_NAMES.get(head, head), "\n".join(body).strip()) for head, body in parts]


def _report(current: jobs.Job) -> None:
    text = current.state["report_text"]
    st.html(_download_button(current.company_name, text))  # outside the tabs: it saves the whole report
    st.html(f'<script src="/app/static/download.js?v={int(_DOWNLOAD_JS.stat().st_mtime)}"></script>', unsafe_allow_javascript=True)
    sections = _sections(text)
    with st.container(key="report"):
        if not sections:
            st.markdown(text)
            return
        for tab, (_, body) in zip(st.tabs([name for name, _ in sections]), sections):
            with tab:
                st.markdown(body)


def _research_page(current: jobs.Job) -> None:
    st.html(
        f'<div class="ws-jobhead"><h1>{html.escape(current.company_name)}</h1>'
        f'<span class="ws-chip">{html.escape(METHOD_NAMES.get(current.method, "General"))}</span></div>'
    )
    if current.status == "running":
        if jobs.claim_stale(current.id):
            runner.start(current.id)
        _progress(current.id)
    elif current.status == "failed":
        if current.fail_reason == "identity_ambiguous":
            identity = CompanyIdentity.model_validate(current.state["identity"])
            st.warning(f'Could not confidently identify a single company for "{current.company_name}".')
            st.write(f"**What was found:** {identity.description}")
            st.write(f"**Location:** {identity.location or 'unknown'}")
            st.write(f"**Why it's ambiguous:** {identity.ambiguity_note}")
            st.info(
                "Stopping rather than guessing which company you meant. Try again with a more specific name, "
                "or paste the company's URL; it outranks search and resolves this directly."
            )
        else:
            st.error(_FAILURES.get(current.fail_reason or "error", _FAILURES["error"]))
    else:
        _review(current)
    if current.status != "running" and st.button("Delete this research", type="tertiary", key="delete_job"):
        jobs.delete_job(current.id)
        chrome.forget_recent()
        st.query_params.pop("job", None)
        st.rerun()


if job is None:
    _composer()
else:
    _research_page(job)
