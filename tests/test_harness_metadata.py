"""Tests for what a benchmark result records about the run that produced it.

Run: python -m unittest discover -s tests -v

A result file is meant to be self-describing: anyone reading it later should
be able to tell what produced those numbers without reconstructing the
conditions. Two things were missing.

Cache write failures were counted on the cache and then dropped on the
floor. A cache is allowed to fail, but a benchmark whose cache had quietly
stopped working would look identical to one whose cache was fine, and the
credit figures would be wrong with nothing to show why.

The rejected citations were counted but never named, which is why the 48
rejections in the published firecrawl_scrape runs can no longer be audited:
the counts survive and the URLs do not, so the data cannot say how many were
invented, recalled, or the same page in a different URL format. Recording
both lists means the next benchmark does not have that hole.

No benchmark is run here and no API is called: the pipeline steps are
replaced and the provider is a stand-in.
"""

import os
import sys
import unittest
from dataclasses import asdict
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("GEMINI_API_KEY", "test-gemini-key")
os.environ.setdefault("TAVILY_API_KEY", "test-tavily-key")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from benchmarks import harness  # noqa: E402


def fake_provider(write_failures=0):
    """A provider with only the attributes the harness touches."""
    return SimpleNamespace(
        name="tavily",
        cache=SimpleNamespace(write_failures=write_failures, hits=0, misses=0),
    )


class CacheWriteFailures(unittest.TestCase):
    def run_once_with(self, provider):
        """One run that stops at identity, so nothing is called live."""
        with patch.object(harness, "build_provider", return_value=provider), \
             patch.object(harness.pipeline, "identify_company",
                          return_value=None):
            return harness.run_once("tavily", "Acme")

    def test_the_field_defaults_to_zero(self):
        self.assertEqual(harness.RunResult(mode="tavily", company="Acme",
                                           url="").cache_write_failures, 0)

    def test_a_healthy_cache_reports_no_failures(self):
        result = self.run_once_with(fake_provider())
        self.assertEqual(result.cache_write_failures, 0)

    def test_failed_cache_writes_reach_the_result(self):
        result = self.run_once_with(fake_provider(write_failures=3))
        self.assertEqual(result.cache_write_failures, 3)

    def test_it_survives_serialisation_into_the_result_file(self):
        """The result is written as JSON, so a field that does not serialise
        is a field nobody will ever read."""
        result = self.run_once_with(fake_provider(write_failures=2))
        self.assertEqual(asdict(result)["cache_write_failures"], 2)

    def test_a_provider_without_a_cache_does_not_break_the_run(self):
        """Tests and the benchmark both inject providers of their own."""
        result = self.run_once_with(SimpleNamespace(name="tavily"))
        self.assertEqual(result.cache_write_failures, 0)


REAL = "https://real.example/about"
FAKE = "https://invented.example/news"


def competitor(sources):
    from schemas import Competitor

    return Competitor(
        name="Peer", why_relevant="r", product_or_service="p",
        target_customers="t", positioning="pos", pricing=None,
        strengths=["s"], weaknesses=["w"], differentiators=["d"],
        sources=list(sources))


class UnfetchedCitations(unittest.TestCase):
    """The rule itself, which lives in evaluate.py so it cannot drift from
    the one drop_fabricated_sources applies."""

    def test_a_citation_outside_the_ledger_is_named(self):
        import evaluate

        self.assertEqual(
            evaluate.unfetched_citations([competitor([REAL, FAKE])], [REAL]),
            [FAKE])

    def test_citations_in_the_ledger_are_not_named(self):
        import evaluate

        self.assertEqual(
            evaluate.unfetched_citations([competitor([REAL])], [REAL]), [])

    def test_it_uses_the_same_normalisation_as_the_stripping(self):
        """A trailing slash or different case is the same page, so it must
        not be reported as unfetched."""
        import evaluate

        self.assertEqual(
            evaluate.unfetched_citations(
                [competitor(["https://Real.example/about/"])], [REAL]),
            [])

    def test_the_same_url_cited_twice_is_reported_once(self):
        import evaluate

        self.assertEqual(
            evaluate.unfetched_citations(
                [competitor([FAKE]), competitor([FAKE])], [REAL]),
            [FAKE])


class RecordedUrls(unittest.TestCase):
    """The harness records both lists, so a later reader can check them."""

    def run_once_with(self, competitors, fetched):
        from schemas import CompanyIdentity, CompetitorResearch

        identity = CompanyIdentity(description="A target", location="L",
                                   confident_match=True)
        research = CompetitorResearch(
            company_name="Acme", competitors=competitors, market_trends=[],
            market_gaps_opportunities=[], potential_threats=[])

        def seeded_run(**kwargs):
            from runstate import RunState

            run = RunState(progress=None, **kwargs)
            for url in fetched:
                run.record_source(url)
            return run

        with patch.object(harness, "build_provider",
                          return_value=fake_provider()), \
             patch.object(harness, "RunState", seeded_run), \
             patch.object(harness.pipeline, "identify_company",
                          return_value=identity), \
             patch.object(harness.pipeline, "research_competitors",
                          return_value=research), \
             patch.object(harness.pipeline, "verify_competitors",
                          return_value=[]), \
             patch.object(harness.pipeline, "apply_verifications",
                          return_value=(competitors, [])):
            return harness.run_once("tavily", "Acme")

    def test_the_rejected_urls_are_recorded_not_just_counted(self):
        result = self.run_once_with([competitor([REAL, FAKE])], [REAL])

        self.assertEqual(result.rejected_citations, [FAKE])
        self.assertEqual(result.fabricated_urls_dropped, 1,
                         "the count must still agree with the list")

    def test_everything_fetched_is_recorded(self):
        result = self.run_once_with([competitor([REAL])], [REAL, FAKE])

        self.assertEqual(result.fetched_urls, sorted([REAL, FAKE]))
        self.assertEqual(result.sources_consulted, 2,
                         "the count is derived from the list, so they agree")

    def test_a_clean_run_records_an_empty_rejection_list(self):
        result = self.run_once_with([competitor([REAL])], [REAL])
        self.assertEqual(result.rejected_citations, [])

    def test_both_lists_survive_serialisation(self):
        result = self.run_once_with([competitor([REAL, FAKE])], [REAL])
        serialised = asdict(result)

        self.assertEqual(serialised["rejected_citations"], [FAKE])
        self.assertEqual(serialised["fetched_urls"], [REAL])


if __name__ == "__main__":
    unittest.main()
