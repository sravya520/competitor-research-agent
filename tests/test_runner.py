"""The web job runner against the pipeline's real signatures (run state passed explicitly).

No network: the three LLM steps are replaced. Skips with the install command if the web packages
are missing. Uses a throwaway SQLite file (tests/web_setup.py); never touches data/cra.db.
"""

import sys
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE.parent), str(HERE)]

import web_setup  # noqa: E402  (sets the environment; must come before backend)

web_setup.require_web_packages()

from google.genai import errors  # noqa: E402

import pipeline  # noqa: E402
import runner  # noqa: E402
from backend import jobs, users  # noqa: E402
from schemas import CompanyIdentity, Competitor, CompetitorResearch, CompetitorVerification  # noqa: E402

IDENTITY = CompanyIdentity(description="Acme makes anvils.", location="Nowhere", confident_match=True)
COMPETITOR = Competitor(
    name="Birch", why_relevant="Same buyers.", product_or_service="Anvils.", target_customers="Smiths.",
    positioning="Cheap.", strengths=["Price"], weaknesses=["Weight"], differentiators=["Cast iron"],
    sources=["https://birch.example/a", "https://other.example/b"],
)


def _job(key_mode="house"):
    user = users.upsert_login("sub-runner", "runner@example.com", "Runner")
    return jobs.create(user.id, "Acme", "https://acme.example", key_mode)



class RunnerTests(unittest.TestCase):
    def test_a_run_reaches_review_and_keeps_its_sources(self):
        def identify(name, url, run):
            run.record_source("https://acme.example")  # what tools.make_tools(run) does on a real fetch
            run.progress("[search] acme anvils")
            return IDENTITY

        research = CompetitorResearch(company_name="Acme", competitors=[COMPETITOR], market_trends=["t"],
                                      market_gaps_opportunities=["g"], potential_threats=["p"])
        verdicts = [CompetitorVerification(index=0, name="Birch", verified=True, reason="ok")]
        job_id = _job()
        with patch.object(pipeline, "identify_company", identify), \
             patch.object(pipeline, "research_competitors", lambda name, ident, run: research), \
             patch.object(pipeline, "verify_competitors", lambda name, ident, comps, run: verdicts):
            runner._run(job_id)

        job = jobs.get(job_id)
        assert job.status == "review", (job.status, job.fail_reason)
        assert [c["name"] for c in job.state["verified"]] == ["Birch"]
        assert job.state["sources"] == ["https://acme.example"]
        assert any("[search]" in line for line in job.log)


    def _spent_free_run(self, sub):
        user = users.upsert_login(sub, f"{sub}@example.com", None)
        assert users.consume_free_run(user.id)
        return user, jobs.get(jobs.create(user.id, "Acme", "", "house"))

    def test_a_service_failure_refunds_the_free_run_only_once(self):
        user, job = self._spent_free_run("sub-refund")
        runner._fail(job, "api_error")
        assert users.get_info(user.id).free_runs_left == 1
        users.consume_free_run(user.id)  # the user spends it again on a new run
        runner._fail(job, "api_error")   # a second worker on the OLD job must not hand out another
        assert users.get_info(user.id).free_runs_left == 0

    def test_a_real_api_error_during_a_run_fails_it_and_refunds_it(self):
        user, job = self._spent_free_run("sub-api")
        quota = errors.APIError(429, {"error": {"code": 429, "status": "RESOURCE_EXHAUSTED", "message": "spent"}})
        with patch.object(pipeline, "identify_company", side_effect=quota):
            runner._run(job.id)
        done = jobs.get(job.id)
        assert (done.status, done.fail_reason) == ("failed", "quota")
        assert users.get_info(user.id).free_runs_left == 1

    def test_a_company_that_cannot_be_identified_is_not_refunded(self):
        user, job = self._spent_free_run("sub-noid")
        with patch.object(pipeline, "identify_company", return_value=None):
            runner._run(job.id)
        assert jobs.get(job.id).fail_reason == "identity_failed"
        assert users.get_info(user.id).free_runs_left == 0

    def test_an_allow_listed_account_is_never_refunded_a_run_it_did_not_spend(self):
        user, job = self._spent_free_run("sub-listed")
        with patch.object(runner.users, "get_info", return_value=replace(users.get_info(user.id), unlimited=True)):
            runner._fail(job, "error")
        assert users.get_info(user.id).free_runs_left == 0

    def test_own_keys_are_refused_not_run_on_the_house_keys(self):
        job_id = _job("own")
        with patch.object(pipeline, "identify_company", side_effect=AssertionError("must not run")):
            runner._run(job_id)
        job = jobs.get(job_id)
        assert (job.status, job.fail_reason) == ("failed", "own_keys_unsupported")


if __name__ == "__main__":
    unittest.main()
