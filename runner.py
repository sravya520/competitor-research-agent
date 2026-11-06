"""Runs one research job in a background thread and saves each stage to the database.

Why a thread and a database: on Vercel a Streamlit WebSocket lasts under a minute, then the browser
reconnects as a NEW session, but a run takes 30-90 s. Doing the run inside the page therefore lost
it. Here the page only starts the job and reads backend.jobs; this thread does the work, so a
dropped connection costs nothing. It writes after every stage, so a thread that dies with its server
instance is restarted by the next page load and resumes from the last saved stage (jobs.claim_stale).

Knows nothing about Streamlit (CLAUDE.md): same pipeline modules as main.py and the CLI.
"""

import threading
import traceback

from google.genai import errors

import evaluate
import pipeline
from backend import jobs, users
from runstate import RunState
from schemas import CompanyIdentity, Competitor, CompetitorResearch

HEARTBEAT_EVERY_S = 20  # a single Gemini call can be silent for a while; keep the job looking alive


def start(job_id: str) -> None:
    """Run (or resume) the job in the background and return immediately."""
    threading.Thread(target=_run, args=(job_id,), daemon=True, name=f"job-{job_id[:8]}").start()


def _run(job_id: str) -> None:
    job = jobs.get(job_id)
    if job is None:
        return

    done = threading.Event()

    def beat() -> None:
        while not done.wait(HEARTBEAT_EVERY_S):
            jobs.touch(job_id)

    threading.Thread(target=beat, daemon=True, name=f"beat-{job_id[:8]}").start()
    try:
        if job.key_mode == "own":
            # Moat no longer creates these, but a row from before own keys were hidden can still be open
            # (kept up to 24 h). Say so instead of spending the house keys on a run nobody asked them to pay for.
            jobs.update_job(job_id, status="failed", fail_reason="own_keys_unsupported")
            return
        _stages(job_id, job)
    except errors.APIError as exc:
        _fail(job, "quota" if exc.code == 429 else "api_error")
    except Exception:  # never let a bug leave the page spinning forever
        traceback.print_exc()
        _fail(job, "error")
    finally:
        done.set()


def _fail(job: jobs.Job, reason: str) -> None:
    """Mark the job failed after a service problem, and give back its free run, at most once per job.

    Only the caller that actually moves the job to failed refunds, so a second worker on the same job (a
    paused instance waking up) cannot refund again. A run that fails on the company itself (identity or
    research came up empty) is not refunded, and the daily count is never refunded (backend/usage.py).
    An allow-listed account never spent a free run, so it has nothing to give back.
    """
    if not jobs.fail_once(job.id, reason) or job.key_mode != "house":
        return
    owner = users.get_info(job.user_id)
    if owner is not None and not owner.unlimited:
        users.refund_free_run(job.user_id)


def _stages(job_id: str, job: jobs.Job) -> None:
    state = job.state
    run = RunState(progress=lambda message: jobs.log(job_id, message))  # one ledger per job, never shared
    for url in state.get("sources", []):  # a resumed job keeps the evidence its earlier stages gathered
        run.record_source(url)

    def save(**parts) -> None:
        state.update(parts)
        jobs.merge_state(job_id, **parts)

    if "identity" not in state:
        jobs.update_job(job_id, stage="identify")
        jobs.log(job_id, "Identifying the company...")
        identity = pipeline.identify_company(job.company_name, job.company_url, run)
        if identity is None:
            jobs.update_job(job_id, status="failed", fail_reason="identity_failed")
            return
        save(identity=identity.model_dump(), sources=run.sources_consulted())
        if not identity.confident_match:
            jobs.update_job(job_id, status="failed", fail_reason="identity_ambiguous")
            return
    identity = CompanyIdentity.model_validate(state["identity"])

    if "research" not in state:
        jobs.update_job(job_id, stage="research")
        jobs.log(job_id, f"Confirmed: {identity.description[:80]}...")
        jobs.log(job_id, "Researching competitors...")
        research = pipeline.research_competitors(job.company_name, identity, run)
        if research is None:
            jobs.update_job(job_id, status="failed", fail_reason="research_failed")
            return
        save(research=research.model_dump(), sources=run.sources_consulted())
    research = CompetitorResearch.model_validate(state["research"])

    if "verified" not in state:
        jobs.update_job(job_id, stage="verify")
        jobs.log(job_id, "Independently verifying each competitor...")
        verifications = pipeline.verify_competitors(job.company_name, identity, research.competitors, run)
        verified, excluded = pipeline.apply_verifications(research.competitors, verifications)

        problems = evaluate.run_checks(verified, run.sources_consulted())
        removed = evaluate.drop_fabricated_sources(verified, run.sources_consulted())
        if removed:
            problems.append(f"Removed {removed} fabricated source URL(s).")
        # After stripping fabricated URLs above, not before: a fake source shouldn't count toward corroboration.
        problems += evaluate.check_source_corroboration(verified)
        problems += evaluate.check_precise_claims_are_corroborated(verified)

        save(
            verified=[c.model_dump() for c in verified],
            excluded=[list(pair) for pair in excluded],
            problems=problems,
            sources=run.sources_consulted(),
        )
    jobs.log(job_id, f"Found {len(state['verified'])} verified competitor(s)")
    jobs.update_job(job_id, status="review", stage="review")


def competitors_from(state: dict) -> list[Competitor]:
    return [Competitor.model_validate(c) for c in state.get("verified", [])]
