"""Memory must not hand the verifier an identity with no scale recorded.

Run: python -m unittest discover -s tests -v

verification_prompt compares a candidate's scale and stage against the
target's. CompanyIdentity gained scale_and_stage because without it the
verifier was guessing and its verdicts on identical input flipped between
runs: 4 of 5 on one fixed case.

That creates a trap where the two features meet. Every ledger line written
before the field existed has no scale, and the prompt reads a missing target
scale as "NOT ESTABLISHED", which it is explicitly told to treat as
early-stage and small. Reusing an old record for a large target would
therefore reinstate exactly the guessing the field removed, silently, and
only on companies researched before the upgrade.

So an identity with no scale is never reused, however fresh it is. One extra
identify call is cheaper than a wrong verification pass.
"""

import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("GEMINI_API_KEY", "test-gemini-key")
os.environ.setdefault("TAVILY_API_KEY", "test-tavily-key")

import memory  # noqa: E402
import prompts  # noqa: E402
import recall  # noqa: E402
import report as report_module  # noqa: E402
from runstate import RunState  # noqa: E402
from schemas import Competitor, CompetitorResearch  # noqa: E402

SCALE = "about 120 staff, Series B, scaled"
NOW = datetime.now(timezone.utc)


def stamp(days_ago):
    return (NOW - timedelta(days=days_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")


def identity(scale=SCALE, website="https://notion.so"):
    return SimpleNamespace(description="Workspace and notes tool",
                           location="San Francisco, US", website=website,
                           scale_and_stage=scale)


def a_competitor(name="Coda", scale="about 60 staff, Series B"):
    return Competitor(
        name=name, why_relevant="Same category", product_or_service="Docs",
        target_customers="Teams", positioning="All-in-one", pricing=None,
        strengths=["flexible"], weaknesses=["slower"],
        differentiators=["formulas"], sources=["https://coda.io"],
        scale_and_stage=scale)


class StoredScale(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = os.path.join(self.directory.name, "memory.jsonl")

    def test_a_new_record_stores_the_scale_inside_the_identity(self):
        record = memory.record_run(path=self.path, company_name="Notion",
                                   identity=identity())
        self.assertEqual(record["identity"]["scale_and_stage"], SCALE)

    def test_an_identity_without_a_scale_stores_none(self):
        record = memory.record_run(path=self.path, company_name="Notion",
                                   identity=identity(scale=None))
        self.assertIsNone(record["identity"]["scale_and_stage"])


class RecallRefusesAnUnscaledIdentity(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = os.path.join(self.directory.name, "memory.jsonl")

    def write(self, scale, days_ago=1):
        return memory.record_run(path=self.path, company_name="Notion",
                                 run_at=stamp(days_ago),
                                 identity=identity(scale=scale))

    def old_format_record(self, days_ago=1):
        """A ledger line from before scale_and_stage existed."""
        record = memory.build_record(company_name="Notion",
                                     run_at=stamp(days_ago),
                                     identity=identity())
        del record["identity"]["scale_and_stage"]
        memory.append_record(record, self.path)
        return record

    def test_an_old_format_record_is_refused(self):
        self.old_format_record()
        self.assertIsNone(memory.recall_identity("notion.so", self.path,
                                                 now=NOW))

    def test_an_empty_scale_is_refused(self):
        for scale in (None, "", "   "):
            with self.subTest(scale=scale):
                directory = tempfile.TemporaryDirectory()
                self.addCleanup(directory.cleanup)
                path = os.path.join(directory.name, "memory.jsonl")
                memory.record_run(path=path, company_name="Notion",
                                  run_at=stamp(1),
                                  identity=identity(scale=scale))
                self.assertIsNone(memory.recall_identity("notion.so", path,
                                                         now=NOW))

    def test_a_new_format_record_is_reused(self):
        self.write(SCALE)
        recalled = memory.recall_identity("notion.so", self.path, now=NOW)
        self.assertIsNotNone(recalled)
        self.assertEqual(recalled["scale_and_stage"], SCALE)

    def test_a_scaled_record_is_preferred_over_a_newer_unscaled_one(self):
        """The scan continues past an unusable record rather than stopping,
        so one old line does not hide the history behind it."""
        self.write(SCALE, days_ago=5)
        self.old_format_record(days_ago=1)

        recalled = memory.recall_identity("notion.so", self.path, now=NOW)
        self.assertIsNotNone(recalled)
        self.assertEqual(recalled["run_at"], stamp(5))


class ReusedIdentityReachesTheVerifier(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = os.path.join(self.directory.name, "memory.jsonl")
        memory.record_run(path=self.path, company_name="Notion",
                          run_at=stamp(2), identity=identity())

    def test_the_rebuilt_identity_carries_the_scale(self):
        with patch.object(recall.pipeline, "identify_company") as live:
            rebuilt, recalled = recall.establish_identity(
                "Notion", "https://notion.so", RunState(progress=None),
                path=self.path)

        self.assertEqual(live.call_count, 0, "this should come from memory")
        self.assertEqual(rebuilt.scale_and_stage, SCALE)
        self.assertTrue(rebuilt.confident_match)
        self.assertIsNotNone(recalled)

    def test_the_scale_reaches_the_verification_prompt(self):
        """The whole point: a reused identity must be as useful to the
        verifier as a freshly established one."""
        rebuilt, _ = recall.establish_identity(
            "Notion", "https://notion.so", RunState(progress=None),
            path=self.path)

        prompt = prompts.verification_prompt("Notion", rebuilt,
                                             [a_competitor()])

        # The phrase NOT ESTABLISHED also appears in the prompt's standing
        # instructions, so the assertion is on the target's own line.
        self.assertIn(f"Scale and stage: {SCALE}", prompt)
        self.assertNotIn("Scale and stage: NOT ESTABLISHED", prompt)

    def test_an_unscaled_identity_would_have_reached_it_as_not_established(self):
        """Why the refusal exists, stated as a test: this is what the
        verifier would have been given had the old record been reused."""
        unscaled = identity(scale=None)
        prompt = prompts.verification_prompt("Notion", unscaled,
                                             [a_competitor()])
        self.assertIn("Scale and stage: NOT ESTABLISHED", prompt)


class DisclosureUnchanged(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = os.path.join(self.directory.name, "memory.jsonl")
        memory.record_run(path=self.path, company_name="Notion",
                          run_at=stamp(3), identity=identity())

    def test_the_from_memory_line_is_unchanged(self):
        """Scale is for the verifier, not the reader. The report's wording
        about reuse must not drift because of it."""
        rebuilt, recalled = recall.establish_identity(
            "Notion", "https://notion.so", RunState(progress=None),
            path=self.path)

        content = report_module.build_report(
            company_name="Notion", company_url="https://notion.so",
            identity=rebuilt,
            research=CompetitorResearch(company_name="Notion", competitors=[],
                                        market_trends=[],
                                        market_gaps_opportunities=[],
                                        potential_threats=[]),
            competitors=[a_competitor()], excluded=[],
            sources=["https://coda.io"], identity_recalled=recalled)

        lines = [line for line in content.splitlines()
                 if "From memory:" in line]
        self.assertEqual(len(lines), 1)
        self.assertIn("identity established on", lines[0])
        self.assertIn("and reused, not re-established for this report",
                      lines[0])
        self.assertNotIn(SCALE, lines[0], "scale is not a reader-facing note")


if __name__ == "__main__":
    unittest.main()
