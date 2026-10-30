"""Tests for what run_eval.py treats as a gate failure.

Run: python -m unittest discover -s tests -v

These exist because the eval and the product disagreed about fabricated
citations. main.py and app.py strip a cited URL that was never fetched and
carry on, noting it for the reviewer; run_eval.py failed the case outright.
So the suite went red whenever the fabrication check did its job, and across
a measured baseline that was the single biggest cause of failing runs. A
suite that punishes a working defence teaches you to ignore the suite.

Three things are protected here:

1. A fabricated citation alongside a real one is stripped and counted, and
   does not by itself fail the case.
2. A competitor left citing nothing after stripping DOES fail: that is what
   would actually reach the report, as a claim with no support behind it.
3. The competitor-count failure is reported once, with the case's own
   minimum. run_checks defaults to 2, which used to duplicate the message
   on cases asking for 2 and report a different number on cases asking
   for 3.
"""

import os
import unittest
from unittest.mock import patch

os.environ.setdefault("GEMINI_API_KEY", "test-gemini-key")
os.environ.setdefault("TAVILY_API_KEY", "test-tavily-key")

import run_eval  # noqa: E402
from schemas import CompanyIdentity, CompetitorResearch, Competitor  # noqa: E402

REAL = "https://realsite.example/about"
FAKE = "https://invented.example/news/never-fetched"


def competitor(name, sources):
    return Competitor(
        name=name,
        why_relevant="Comparable peer.",
        product_or_service="A product",
        target_customers="Startups",
        positioning="Positioned somewhere",
        strengths=[],
        weaknesses=[],
        differentiators=[],
        sources=sources,
    )


def run_case_with(competitors, consulted, case=None):
    """Drive run_eval.run_case over a fixed set of competitors.

    The pipeline is stubbed out: these tests are about which results the
    eval calls a failure, not about what the agent finds.
    """
    identity = CompanyIdentity(description="A target", location="L", confident_match=True)
    research = CompetitorResearch(
        company_name="Target",
        competitors=competitors,
        market_trends=[],
        market_gaps_opportunities=[],
        potential_threats=[],
    )
    case = case or {"id": "t", "company": "Target", "url": None,
                    "expect_stop": False, "min_competitors": 2}

    with patch.object(run_eval.tools, "reset_sources"), \
         patch.object(run_eval.tools, "sources_consulted", return_value=consulted), \
         patch.object(run_eval.pipeline, "identify_company", return_value=identity), \
         patch.object(run_eval.pipeline, "research_competitors", return_value=research), \
         patch.object(run_eval.pipeline, "verify_competitors", return_value=[]), \
         patch.object(run_eval.pipeline, "apply_verifications",
                      return_value=(competitors, [])):
        return run_eval.run_case(case)


class FabricatedCitations(unittest.TestCase):
    def test_stripped_rather_than_failed(self):
        """The product strips these and ships. The eval must agree."""
        competitors = [competitor("A", [REAL, FAKE]), competitor("B", [REAL])]
        failures, metrics = run_case_with(competitors, [REAL])

        self.assertEqual(failures, [])
        self.assertEqual(metrics["fabricated_sources_removed"], 1)

    def test_removal_is_counted_even_when_the_case_passes(self):
        competitors = [competitor("A", [REAL, FAKE]), competitor("B", [REAL, FAKE])]
        _, metrics = run_case_with(competitors, [REAL])

        self.assertEqual(metrics["fabricated_sources_removed"], 2)

    def test_real_citations_are_left_alone(self):
        competitors = [competitor("A", [REAL]), competitor("B", [REAL])]
        failures, metrics = run_case_with(competitors, [REAL])

        self.assertEqual(failures, [])
        self.assertEqual(metrics["fabricated_sources_removed"], 0)

    def test_competitor_left_with_no_source_still_fails(self):
        """Stripping must not quietly launder an entirely invented profile."""
        competitors = [competitor("A", [FAKE]), competitor("B", [REAL])]
        failures, _ = run_case_with(competitors, [REAL])

        self.assertTrue(
            any("cites no source at all" in f for f in failures),
            f"expected an uncited-competitor failure, got {failures}",
        )
        self.assertTrue(any("A" in f for f in failures))


class CompetitorCountReportedOnce(unittest.TestCase):
    def test_single_message_when_minimum_is_two(self):
        competitors = [competitor("A", [REAL])]
        failures, _ = run_case_with(competitors, [REAL])

        count = [f for f in failures if "Expected at least" in f]
        self.assertEqual(len(count), 1, f"duplicated: {count}")
        self.assertIn("at least 2", count[0])

    def test_uses_the_cases_own_minimum(self):
        case = {"id": "t", "company": "Target", "url": None,
                "expect_stop": False, "min_competitors": 3}
        competitors = [competitor("A", [REAL]), competitor("B", [REAL])]
        failures, _ = run_case_with(competitors, [REAL], case=case)

        count = [f for f in failures if "Expected at least" in f]
        self.assertEqual(len(count), 1, f"duplicated: {count}")
        self.assertIn("at least 3", count[0])
        self.assertIn("got 2", count[0])


if __name__ == "__main__":
    unittest.main()
