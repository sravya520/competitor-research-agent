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


if __name__ == "__main__":
    unittest.main()
