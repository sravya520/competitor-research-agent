"""Tests for a run where verification refuses every candidate.

Run: python -m unittest discover -s tests -v

This is the normal outcome for a small company, not an edge case. A live run
on Strider Robotics, a pre-revenue Indian quadruped startup, proposed five
candidates and the verifier refused all five as far larger. The CLI then
wrote no report at all, which is the worst possible output for a tool aimed
at startups: the founder learns nothing, not even that the search ran and
what it found.

So the report is written anyway. It opens by saying no comparable
competitors were found, then lists what was considered with the verifier's
own reason and the candidate's sources, after the same citation check as
everything else. Those candidates are never counted as competitors: the
competitor count stays zero, the eval's minimum gate is untouched, and the
ledger stores them in a field of their own so a later comparison cannot
report them as competitors arriving or leaving.

The fixture text below is the real shape of those exclusions.
"""

import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

os.environ.setdefault("GEMINI_API_KEY", "test-gemini-key")
os.environ.setdefault("TAVILY_API_KEY", "test-tavily-key")

import evaluate  # noqa: E402
import memory  # noqa: E402
import pipeline  # noqa: E402
import recall  # noqa: E402
import report as report_module  # noqa: E402
from schemas import (  # noqa: E402
    Competitor,
    CompetitorResearch,
    CompetitorVerification,
)

NOW = datetime(2026, 11, 3, 12, 0, 0, tzinfo=timezone.utc)

TARGET = SimpleNamespace(
    description="Strider Robotics builds quadruped robots for inspection in "
                "Indian industrial settings.",
    location="Bengaluru, IN", website="https://strider-robotics.in",
    scale_and_stage="Pre-revenue, founded 2024, no disclosed funding.")

# The five candidates and the verifier's reasons, as the live run produced
# them. Kept verbatim in shape so the section is tested against the real
# thing rather than against "reason 1", "reason 2".
STRIDER_EXCLUSIONS = [
    ("ANYbotics",
     "ANYbotics is a Swiss industrial robotics company with over 200 "
     "employees and more than $70M raised, selling deployed inspection "
     "robots to oil, gas and power utilities. The target is pre-revenue "
     "with no disclosed funding; these are not comparable in scale or stage.",
     ["https://www.anybotics.com/company", "https://techcrunch.com/anybotics"]),
    ("Boston Dynamics",
     "Boston Dynamics is owned by Hyundai, employs over 1,000 people and "
     "sells Spot commercially worldwide. Not comparable to an early-stage "
     "startup with no shipped product.",
     ["https://bostondynamics.com/about"]),
    ("DEEP Robotics",
     "DEEP Robotics is a Hangzhou manufacturer with multiple product "
     "generations shipping at volume and substantial institutional funding.",
     ["https://www.deeprobotics.cn/en/about"]),
    ("Unitree",
     "Unitree ships consumer and industrial quadrupeds at scale with "
     "reported revenue in the tens of millions of dollars.",
     ["https://www.unitree.com/about"]),
    ("Ghost Robotics",
     "Ghost Robotics supplies quadrupeds to the US Department of Defense and "
     "was acquired by LIG Nex1; it is an order of magnitude larger.",
     ["https://www.ghostrobotics.io/company",
      "https://www.reuters.com/ghost-robotics-lig-nex1"]),
]


def candidate(name, sources, scale="Scaled, over 200 staff"):
    return Competitor(
        name=name, why_relevant="Builds quadruped robots.",
        product_or_service="Quadruped robots", target_customers="Industry",
        positioning="Established manufacturer", pricing=None,
        scale_and_stage=scale, strengths=["shipping"], weaknesses=["costly"],
        differentiators=["scale"], sources=list(sources))


def strider_candidates():
    return [candidate(name, sources)
            for name, _reason, sources in STRIDER_EXCLUSIONS]


def strider_considered():
    """What pipeline.rejected_competitors returns for that run."""
    return [(candidate(name, sources), reason)
            for name, reason, sources in STRIDER_EXCLUSIONS]


def all_refused(competitors):
    """A verdict refusing every candidate, as the live verifier did."""
    return [CompetitorVerification(index=index, name=competitor.name,
                                   verified=False,
                                   reason=STRIDER_EXCLUSIONS[index][1])
            for index, competitor in enumerate(competitors)]


class RefusedCandidates(unittest.TestCase):
    """pipeline.rejected_competitors, which both UIs read."""

    def test_every_candidate_comes_back_with_its_reason(self):
        candidates = strider_candidates()
        refused = pipeline.rejected_competitors(candidates,
                                                all_refused(candidates))

        self.assertEqual([c.name for c, _ in refused],
                         [name for name, _, _ in STRIDER_EXCLUSIONS])
        self.assertIn("not comparable in scale or stage", refused[0][1])

    def test_it_agrees_with_apply_verifications(self):
        """Two views of one decision, so they cannot disagree."""
        candidates = strider_candidates()
        verifications = all_refused(candidates)

        kept, excluded = pipeline.apply_verifications(candidates, verifications)
        refused = pipeline.rejected_competitors(candidates, verifications)

        self.assertEqual(kept, [])
        self.assertEqual([name for name, _ in excluded],
                         [c.name for c, _ in refused])

    def test_a_candidate_with_no_verdict_is_refused(self):
        """Unchanged rule: an unchecked claim does not reach the report."""
        candidates = strider_candidates()
        refused = pipeline.rejected_competitors(candidates, [])
        self.assertEqual(len(refused), len(candidates))
        self.assertIn("No verification returned", refused[0][1])


class TheReport(unittest.TestCase):
    def report(self, competitors=(), considered=None, excluded=()):
        return report_module.build_report(
            company_name="Strider Robotics",
            company_url="https://strider-robotics.in", identity=TARGET,
            research=CompetitorResearch(company_name="Strider Robotics",
                                        competitors=[], market_trends=[],
                                        market_gaps_opportunities=[],
                                        potential_threats=[]),
            competitors=list(competitors), excluded=list(excluded),
            sources=["https://strider-robotics.in"],
            considered=strider_considered() if considered is None else considered)

    def test_a_report_is_written_at_all(self):
        """The point of the change: an empty result still produces a file."""
        self.assertTrue(self.report().strip())

    def test_it_opens_by_saying_so(self):
        content = self.report()
        heading = content.index("# Competitor Research: Strider Robotics")
        statement = content.index("No competitors of comparable scale were found.")
        company = content.index("## The company")

        self.assertLess(heading, statement)
        self.assertLess(statement, company,
                        "the answer comes before the preamble")

    def test_the_competitor_count_stays_zero(self):
        """These are not competitors and are never counted as any."""
        self.assertIn("## Competitors (0)", self.report())

    def test_each_candidate_appears_with_the_verifier_reason(self):
        content = self.report()
        self.assertIn("## Candidates considered but not comparable", content)

        for name, reason, _sources in STRIDER_EXCLUSIONS:
            with self.subTest(name=name):
                self.assertIn(f"### {name}", content)
                self.assertIn(reason, content)

    def test_their_sources_are_listed_with_the_usual_label(self):
        content = self.report()
        self.assertIn("https://www.anybotics.com/company", content)
        self.assertIn("corroborated across 2 independent sources", content)
        self.assertIn("single source: not independently corroborated", content)

    def test_a_candidate_stripped_of_its_citations_says_so(self):
        """The same citation check runs over these, so a candidate can reach
        the section with nothing left to cite."""
        stripped = [(candidate("ANYbotics", []), "Far larger.")]
        self.assertIn("no sources cited", self.report(considered=stripped))

    def test_it_says_these_are_not_competitors(self):
        content = self.report()
        self.assertIn("are not competitors of this company", content)

    def test_nothing_refused_means_no_section(self):
        content = self.report(considered=[])
        self.assertIn("No competitors of comparable scale were found.", content)
        self.assertNotIn("Candidates considered but not comparable", content)

    def test_a_normal_run_is_unchanged(self):
        """With competitors, neither the opening line nor the section
        appears, so the usual report reads exactly as before."""
        content = self.report(competitors=[candidate("Peer", ["https://peer.io"])],
                              considered=[])
        self.assertNotIn("No competitors of comparable scale were found.",
                         content)
        self.assertNotIn("Candidates considered but not comparable", content)
        self.assertIn("## Competitors (1)", content)

    def test_a_reviewer_removal_is_not_listed_as_considered(self):
        """Only what verification refused. The reviewer already knows what
        they removed, and it appears in the excluded section as before."""
        content = self.report(
            considered=[], excluded=[("Peer", "Removed by human reviewer.")])

        self.assertNotIn("Candidates considered but not comparable", content)
        self.assertIn("Removed by human reviewer.", content)


class TheLedgerRecord(unittest.TestCase):
    """Such a run DOES write a record, with the candidates kept apart."""

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = os.path.join(self.directory.name, "memory.jsonl")

    def write(self, days_ago=0):
        stamp = (NOW - timedelta(days=days_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")
        return memory.record_run(
            path=self.path, company_name="Strider Robotics",
            company_url="https://strider-robotics.in", identity=TARGET,
            competitors=[], considered=strider_considered(), run_at=stamp)

    def test_the_run_is_recorded(self):
        record = self.write()
        self.assertIsNotNone(record, "a run with no competitors is still a run")
        self.assertEqual(record["key"], "strider-robotics.in")
        self.assertTrue(record["key_is_strong"])

    def test_the_competitor_list_is_empty(self):
        self.assertEqual(self.write()["competitors"], [])

    def test_the_candidates_are_stored_in_their_own_field(self):
        record = self.write()
        considered = record["considered_not_comparable"]

        self.assertEqual([entry["name"] for entry in considered],
                         [name for name, _, _ in STRIDER_EXCLUSIONS])
        self.assertIn("not comparable in scale or stage",
                      considered[0]["reason_not_comparable"])
        self.assertEqual(considered[0]["competitor_domain"], "anybotics.com",
                         "derived the same way as a competitor's")

    def test_the_record_round_trips(self):
        self.write()
        read_back = memory.read_runs("strider-robotics.in", self.path)
        self.assertEqual(len(read_back), 1)
        self.assertEqual(len(read_back[0]["considered_not_comparable"]), 5)


class TheComparison(unittest.TestCase):
    """A refused candidate must never read as a competitor arriving or
    leaving, which is why it is stored outside the competitor list."""

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = os.path.join(self.directory.name, "memory.jsonl")

    def test_a_refused_candidate_is_not_new_next_time(self):
        """Previous run refused all five. This run finds a real peer: the
        five must not show up as competitors that went away."""
        memory.record_run(
            path=self.path, company_name="Strider Robotics", identity=TARGET,
            competitors=[], considered=strider_considered(),
            run_at=(NOW - timedelta(days=4)).strftime("%Y-%m-%dT%H:%M:%SZ"))

        result = recall.since_last_run(
            "strider-robotics.in", True,
            [candidate("Hyperlocal Robotics", ["https://hyperlocal.in"])],
            path=self.path, now=NOW)

        self.assertEqual(result["new"], ["Hyperlocal Robotics"])
        self.assertEqual(result["not_found"], [],
                         "the refused candidates were never competitors")
        self.assertEqual(result["still_present"], [])

    def test_a_refused_candidate_is_not_still_present_either(self):
        """Even when this run proposes the same company and it is refused
        again, it is absent from both sides of the comparison."""
        memory.record_run(
            path=self.path, company_name="Strider Robotics", identity=TARGET,
            competitors=[], considered=strider_considered(),
            run_at=(NOW - timedelta(days=4)).strftime("%Y-%m-%dT%H:%M:%SZ"))

        result = recall.since_last_run("strider-robotics.in", True, [],
                                       path=self.path, now=NOW)

        self.assertEqual(result["new"], [])
        self.assertEqual(result["not_found"], [])
        self.assertEqual(result["still_present"], [])


class TheEvalGateIsUnchanged(unittest.TestCase):
    """Refused candidates do not count towards the minimum."""

    def test_the_checks_see_no_competitors(self):
        failures = evaluate.run_checks([], ["https://strider-robotics.in"],
                                        minimum=2)
        self.assertTrue(failures, "zero competitors must still fail the gate")

    def test_passing_the_candidates_would_not_silence_it(self):
        """A reminder in test form: the candidates are never handed to the
        gate. If they were, five refused companies would pass a minimum of
        two, which is exactly the false pass this must not produce."""
        refused_only = [competitor for competitor, _ in strider_considered()]
        self.assertEqual(len(refused_only), 5)
        self.assertTrue(evaluate.run_checks([], [], minimum=2))


if __name__ == "__main__":
    unittest.main()
