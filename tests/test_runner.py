"""The web job runner against the pipeline's real signatures (run state passed explicitly).

Runs with pytest or plainly: python tests/test_runner.py. No network: the three LLM steps are replaced.
Uses a throwaway SQLite file; never touches data/cra.db.
"""

import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ["DATABASE_URL"] = f"sqlite:///{Path(tempfile.mkdtemp(), 'runner.db').as_posix()}"
os.environ["KEY_VAULT_SECRET"] = "test-secret-not-for-production"
os.environ.setdefault("GEMINI_API_KEY", "test-gemini-key")
os.environ.setdefault("TAVILY_API_KEY", "test-tavily-key")

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


def test_a_run_reaches_review_and_keeps_its_sources():
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


def test_own_keys_are_refused_not_run_on_the_house_keys():
    job_id = _job("own")
    with patch.object(pipeline, "identify_company", side_effect=AssertionError("must not run")):
        runner._run(job_id)
    job = jobs.get(job_id)
    assert (job.status, job.fail_reason) == ("failed", "own_keys_unsupported")


if __name__ == "__main__":
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_") and callable(f)]
    for name, fn in tests:
        fn()
        print("ok ", name)
    print(f"{len(tests)} passed")
