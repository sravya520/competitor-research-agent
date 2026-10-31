"""Tests for when a stored identity may replace the identify step.

Run: python -m unittest discover -s tests -v

This is the first place memory changes what the agent does, so the rules are
pinned down here rather than left to a reading of the code.

Three things these tests exist to protect:

1. The live identify step is SKIPPED only for a strong key with a recent
   record. pipeline.identify_company is replaced by a counter in every test
   below, so "did the agent make the call" is asserted directly rather than
   inferred.

2. A weak key gets no memory at all, not even as a hint. A name-based key
   can name a different company next month, and feeding the model a past
   guess would bias it toward repeating a misidentification on exactly the
   ambiguous names this pipeline is supposed to stop on.

3. A reused identity is handed back with its date, so the terminal, the web
   UI and the report can say the fact was not established today.
"""

import ast
import io
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

# recall imports pipeline, which imports config, which reads these at import
# time. Dummies keep the tests hermetic: no real keys, no network.
os.environ.setdefault("GEMINI_API_KEY", "test-gemini-key")
os.environ.setdefault("TAVILY_API_KEY", "test-tavily-key")

import memory  # noqa: E402
import recall  # noqa: E402
from runstate import RunState  # noqa: E402

NOW = datetime.now(timezone.utc)


def stamp(days_ago):
    return (NOW - timedelta(days=days_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")


class Establish(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = os.path.join(self.directory.name, "memory.jsonl")

        self.live_calls = []
        self.runs_seen = []
        patcher = patch.object(recall.pipeline, "identify_company",
                               side_effect=self.fake_identify)
        patcher.start()
        self.addCleanup(patcher.stop)

    def fake_identify(self, company_name, company_url, run):
        """Stand-in for the LLM step: records that it was reached.

        `run` is positional and required, matching the real signature: a
        pipeline step that could fall back to shared state is the bug this
        argument exists to prevent.
        """
        self.live_calls.append((company_name, company_url))
        self.runs_seen.append(run)
        return SimpleNamespace(description="freshly identified",
                               location=None, website=None,
                               confident_match=True, ambiguity_note=None)

    def remember(self, days_ago=2, name="Notion", website="https://notion.so",
                 description="Workspace and notes tool", location="US"):
        memory.record_run(
            path=self.path, company_name=name, run_at=stamp(days_ago),
            identity=SimpleNamespace(description=description, location=location,
                                     website=website),
        )

    def establish(self, name="Notion", url="https://notion.so"):
        return recall.establish_identity(name, url, RunState(progress=None),
                                         path=self.path)

    # --- the shortcut -----------------------------------------------------

    def test_a_recent_run_replaces_the_live_step(self):
        self.remember(days_ago=2)
        identity, recalled = self.establish()

        self.assertEqual(self.live_calls, [], "the LLM step should be skipped")
        self.assertEqual(identity.description, "Workspace and notes tool")
        self.assertEqual(identity.location, "US")
        self.assertEqual(identity.website, "https://notion.so")
        self.assertIsNotNone(recalled)

    def test_a_reused_identity_is_confident(self):
        """Only confident runs reach the ledger: both UIs stop before writing
        a report when identity is ambiguous."""
        self.remember()
        identity, _ = self.establish()
        self.assertTrue(identity.confident_match)
        self.assertIsNone(identity.ambiguity_note)

    def test_the_date_comes_back_so_it_can_be_labelled(self):
        self.remember(days_ago=5)
        _, recalled = self.establish()
        self.assertEqual(recalled["run_at"], stamp(5))
        self.assertAlmostEqual(recalled["age_days"], 5.0, places=1)

    def test_a_bare_domain_still_finds_the_history(self):
        """The key is canonical, so the URL need not be typed the same way."""
        self.remember()
        for url in ("notion.so", "https://www.notion.so/product",
                    "HTTPS://NOTION.SO/?utm=x"):
            with self.subTest(url=url):
                _, recalled = self.establish(url=url)
                self.assertIsNotNone(recalled)
        self.assertEqual(self.live_calls, [])

    # --- when the shortcut must not be taken ------------------------------

    def test_nothing_remembered_means_the_live_step_runs(self):
        identity, recalled = self.establish()
        self.assertEqual(len(self.live_calls), 1)
        self.assertIsNone(recalled)
        self.assertEqual(identity.description, "freshly identified")

    def test_a_stale_record_is_re_established(self):
        self.remember(days_ago=memory.RECALL_MAX_AGE_DAYS + 1)
        _, recalled = self.establish()
        self.assertEqual(len(self.live_calls), 1)
        self.assertIsNone(recalled)

    def test_a_weak_key_never_uses_memory(self):
        """No URL: the key is the name, which can mean a different company
        next month. This repo holds two different "Sprout Design" reports."""
        memory.record_run(path=self.path, company_name="Sprout Design",
                          run_at=stamp(1),
                          identity=SimpleNamespace(
                              description="A design agency", location="IN",
                              website=None))

        identity, recalled = recall.establish_identity(
            "Sprout Design", "", RunState(progress=None), path=self.path)

        self.assertEqual(len(self.live_calls), 1)
        self.assertIsNone(recalled)
        self.assertEqual(identity.description, "freshly identified")

    def test_a_directory_url_never_uses_memory(self):
        """A LinkedIn URL cannot key a company, so it cannot recall one."""
        self.remember()
        _, recalled = self.establish(
            url="https://www.linkedin.com/company/notion")
        self.assertEqual(len(self.live_calls), 1)
        self.assertIsNone(recalled)

    def test_another_companys_history_is_not_reused(self):
        self.remember(name="Duolingo", website="https://duolingo.com")
        _, recalled = self.establish(name="Notion", url="https://notion.so")
        self.assertEqual(len(self.live_calls), 1)
        self.assertIsNone(recalled)

    def test_an_unreadable_ledger_costs_the_shortcut_not_the_run(self):
        with patch.object(recall.memory, "recall_identity",
                          side_effect=OSError("permission denied")):
            identity, recalled = self.establish()

        self.assertEqual(len(self.live_calls), 1)
        self.assertIsNone(recalled)
        self.assertEqual(identity.description, "freshly identified")

    def test_a_failed_live_step_still_returns_none(self):
        """Unchanged behaviour: the UIs stop when identity cannot be
        established, and memory must not paper over that."""
        with patch.object(recall.pipeline, "identify_company",
                          return_value=None):
            identity, recalled = self.establish()
        self.assertIsNone(identity)
        self.assertIsNone(recalled)


class Candidates(unittest.TestCase):
    """Websites offered for a name-only run.

    The clock is injected, so none of this depends on when it runs.
    """

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = os.path.join(self.directory.name, "memory.jsonl")

        previous = os.environ.pop(memory.LEDGER_PATH_ENV, None)
        if previous is not None:
            self.addCleanup(os.environ.__setitem__, memory.LEDGER_PATH_ENV,
                            previous)

    def remember(self, name, website, days_ago=1):
        memory.record_run(
            path=self.path, company_name=name, run_at=stamp(days_ago),
            identity=SimpleNamespace(description=f"{name} the company",
                                     location=None, website=website),
        )

    def find(self, name="Notion"):
        return recall.find_candidates(name, self.path, now=NOW)

    def test_no_history_offers_nothing(self):
        self.assertEqual(self.find(), [])

    def test_memory_off_offers_nothing(self):
        """No path and no environment variable: nothing is read."""
        self.remember("Notion", "https://notion.so")
        self.assertEqual(recall.find_candidates("Notion", now=NOW), [])

    def test_one_past_run_is_offered_with_its_age(self):
        self.remember("Notion", "https://notion.so", days_ago=4)
        candidates = self.find()
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["key"], "notion.so")
        self.assertEqual(candidates[0]["website"], "https://notion.so")
        self.assertEqual(candidates[0]["run_at"], stamp(4))
        self.assertAlmostEqual(candidates[0]["age_days"], 4.0, places=3)

    def test_two_companies_sharing_a_name_are_both_offered(self):
        """The case this whole feature exists for. Both are returned and
        neither is chosen: which one is meant is the user's to say."""
        self.remember("Sprout Design", "https://sproutdesign.in", days_ago=9)
        self.remember("Sprout Design", "https://sprout-design.co.uk", days_ago=2)

        candidates = recall.find_candidates("Sprout Design", self.path, now=NOW)
        self.assertEqual([c["key"] for c in candidates],
                         ["sprout-design.co.uk", "sproutdesign.in"],
                         "newest first")

    def test_repeat_runs_of_one_company_collapse_to_one_candidate(self):
        self.remember("Notion", "https://notion.so", days_ago=30)
        self.remember("Notion", "https://notion.so", days_ago=1)
        candidates = self.find()
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["run_at"], stamp(1), "the newest run")

    def test_the_name_match_ignores_case_and_punctuation(self):
        self.remember("Sprout Design Pvt. Ltd", "https://sproutdesign.in")
        for typed in ("sprout design pvt ltd", "SPROUT DESIGN PVT. LTD.",
                      "Sprout-Design  Pvt Ltd"):
            with self.subTest(typed=typed):
                self.assertEqual(
                    len(recall.find_candidates(typed, self.path, now=NOW)), 1)

    def test_a_different_company_is_not_offered(self):
        self.remember("Duolingo", "https://duolingo.com")
        self.assertEqual(self.find("Notion"), [])

    def test_an_old_candidate_is_still_offered(self):
        """Age is shown, not used as a filter. A two-year-old URL is still
        probably the right company, and the user can see how old it is."""
        self.remember("Notion", "https://notion.so", days_ago=700)
        candidates = self.find()
        self.assertEqual(len(candidates), 1)
        self.assertAlmostEqual(candidates[0]["age_days"], 700.0, places=3)

    def test_a_record_with_an_unreadable_timestamp_is_skipped(self):
        """A candidate shown without a date is a suggestion with no evidence
        attached, so it is not shown at all."""
        memory.append_record(
            memory.build_record(company_name="Notion", run_at="last Tuesday",
                                identity=SimpleNamespace(
                                    description="Notion", location=None,
                                    website="https://notion.so")),
            self.path)
        self.assertEqual(self.find(), [])

    def test_weakly_keyed_history_is_skipped(self):
        """A past run that could not establish a domain has no website to
        offer, so there is nothing to suggest."""
        memory.record_run(path=self.path, company_name="Notion",
                          run_at=stamp(1),
                          identity=SimpleNamespace(description="Notion",
                                                   location=None, website=None))
        self.assertEqual(self.find(), [])

    def test_the_list_is_capped(self):
        for number in range(recall.MAX_CANDIDATES + 3):
            self.remember("Acme", f"https://acme{number}.com", days_ago=number + 1)
        self.assertEqual(len(recall.find_candidates("Acme", self.path, now=NOW)),
                         recall.MAX_CANDIDATES)

    def test_an_empty_name_offers_nothing(self):
        self.remember("Notion", "https://notion.so")
        for name in ("", "   ", "!!!", None):
            with self.subTest(name=name):
                self.assertEqual(recall.find_candidates(name, self.path, now=NOW),
                                 [])


class ForceLiveIdentity(unittest.TestCase):
    """The user must always be able to overrule a reused identity.

    No age limit can know that a company rebranded, moved or was acquired
    last week. The person asking usually does.
    """

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = os.path.join(self.directory.name, "memory.jsonl")
        memory.record_run(
            path=self.path, company_name="Notion", run_at=stamp(1),
            identity=SimpleNamespace(description="remembered description",
                                     location=None,
                                     website="https://notion.so"))

    def test_allow_recall_false_forces_the_live_step(self):
        with patch.object(recall.pipeline, "identify_company",
                          return_value=SimpleNamespace(
                              description="freshly identified", location=None,
                              website=None, confident_match=True,
                              ambiguity_note=None)) as live:
            identity, recalled = recall.establish_identity(
                "Notion", "https://notion.so", RunState(progress=None),
                path=self.path, allow_recall=False)

        self.assertEqual(live.call_count, 1)
        self.assertIsNone(recalled)
        self.assertEqual(identity.description, "freshly identified")

    def test_the_default_still_reuses(self):
        with patch.object(recall.pipeline, "identify_company") as live:
            identity, recalled = recall.establish_identity(
                "Notion", "https://notion.so", RunState(progress=None),
                path=self.path)

        self.assertEqual(live.call_count, 0)
        self.assertIsNotNone(recalled)
        self.assertEqual(identity.description, "remembered description")

    def cli_allow_recall(self, argv):
        """What main() passes to recall after reading argv."""
        import main

        seen = {}

        def fake_establish(name, url, run, allow_recall=True, **kwargs):
            seen["allow_recall"] = allow_recall
            return None, None  # main exits immediately after this

        with patch.object(main.recall, "establish_identity",
                          side_effect=fake_establish), \
             patch.object(main, "clean_input",
                          side_effect=["Notion", "https://notion.so"]), \
             patch.object(main.sys, "argv", argv):
            with self.assertRaises(SystemExit):
                main.main()
        return seen["allow_recall"]

    def test_the_cli_flag_turns_recall_off(self):
        import main
        self.assertFalse(self.cli_allow_recall(
            ["main.py", main.FRESH_IDENTITY_FLAG]))

    def test_the_cli_reuses_by_default(self):
        self.assertTrue(self.cli_allow_recall(["main.py"]))


class CliOffer(unittest.TestCase):
    """The numbered list, and every way of declining it."""

    CANDIDATES = [
        {"key": "sproutdesign.in", "website": "https://sproutdesign.in",
         "run_at": "2026-10-20T09:00:00Z", "age_days": 10.0},
        {"key": "sprout-design.co.uk", "website": "https://sprout-design.co.uk",
         "run_at": "2026-09-01T09:00:00Z", "age_days": 59.0},
    ]

    def offer(self, answer, candidates=None):
        import main

        with patch.object(main.recall, "find_candidates",
                          return_value=self.CANDIDATES
                          if candidates is None else candidates), \
             patch.object(main, "clean_input", return_value=answer):
            return main.offer_remembered_urls("Sprout Design")

    def test_no_history_asks_nothing(self):
        self.assertEqual(self.offer("1", candidates=[]), ("", None))

    def test_a_number_picks_that_candidate(self):
        url, picked = self.offer("1")
        self.assertEqual(url, "https://sproutdesign.in")
        self.assertEqual(picked, self.CANDIDATES[0])

        url, picked = self.offer("2")
        self.assertEqual(url, "https://sprout-design.co.uk")

    def test_zero_means_none_of_these(self):
        self.assertEqual(self.offer("0"), ("", None))

    def test_pressing_enter_skips(self):
        self.assertEqual(self.offer(""), ("", None))

    def test_an_out_of_range_number_skips(self):
        self.assertEqual(self.offer("9"), ("", None))

    def test_unreadable_input_skips_rather_than_crashing(self):
        self.assertEqual(self.offer("the first one"), ("", None))


class Disclosure(unittest.TestCase):
    """What the report says when a run leaned on memory."""

    def report(self, **kwargs):
        import report as report_module
        from schemas import Competitor, CompetitorResearch

        return report_module.build_report(
            company_name="Notion", company_url="notion.so",
            identity=SimpleNamespace(description="Workspace tool",
                                     location="US", website="https://notion.so"),
            research=CompetitorResearch(company_name="Notion", competitors=[],
                                        market_trends=[],
                                        market_gaps_opportunities=[],
                                        potential_threats=[]),
            competitors=[Competitor(
                name="Coda", why_relevant="Same category",
                product_or_service="Docs", target_customers="Teams",
                positioning="All-in-one", pricing=None, strengths=["a"],
                weaknesses=["b"], differentiators=["c"],
                sources=["https://coda.io"])],
            excluded=[], sources=["https://coda.io"], **kwargs)

    def test_a_fresh_run_says_nothing_about_memory(self):
        self.assertNotIn("From memory:", self.report())

    def test_a_reused_identity_is_dated(self):
        content = self.report(identity_recalled={
            "established_at": "2026-10-24T09:00:00Z",
            "run_at": "2026-10-29T09:00:00Z", "age_days": 6.0})
        self.assertIn("From memory:", content)
        self.assertIn("identity established on 2026-10-24", content)
        self.assertIn("6 days before this report", content)

    def test_the_report_dates_the_identity_not_the_last_reuse(self):
        """The record that supplied it may be days old while the identity in
        it is months old. The report must name the older date."""
        content = self.report(identity_recalled={
            "established_at": "2026-05-01T09:00:00Z",
            "run_at": "2026-10-29T09:00:00Z", "age_days": 182.0})
        self.assertIn("2026-05-01", content)
        self.assertNotIn("2026-10-29", content)

    def test_both_kinds_of_reuse_share_one_line(self):
        content = self.report(
            url_remembered={"run_at": "2026-09-01T09:00:00Z"},
            identity_recalled={"run_at": "2026-10-24T09:00:00Z"})
        memory_lines = [line for line in content.splitlines()
                        if "From memory:" in line]
        self.assertEqual(len(memory_lines), 1)
        self.assertIn("2026-09-01", memory_lines[0])
        self.assertIn("2026-10-24", memory_lines[0])

    def test_a_remembered_url_alone_is_disclosed(self):
        content = self.report(url_remembered={"run_at": "2026-09-01T09:00:00Z"})
        self.assertIn("website remembered from the run on 2026-09-01", content)
        self.assertNotIn("identity reused", content)


class Layering(unittest.TestCase):
    """The pipeline must never learn that memory exists.

    run_eval.py calls pipeline.identify_company directly, so as long as the
    pipeline knows nothing about the ledger, a benchmark cannot be
    influenced by stored history. That is worth more than a feature flag,
    which someone has to remember to set. This test keeps the property
    structural instead of merely habitual.
    """

    FORBIDDEN = {"memory", "recall"}
    ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    def imports_of(self, filename):
        source = io.open(os.path.join(self.ROOT, filename),
                         encoding="utf-8").read()
        tree = ast.parse(source, filename)

        names = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                names.add(node.module.split(".")[0])
        return names

    def test_the_pipeline_and_the_evals_stay_memory_free(self):
        for filename in ("pipeline.py", "prompts.py", "evaluate.py",
                         "run_eval.py"):
            with self.subTest(filename=filename):
                found = self.imports_of(filename) & self.FORBIDDEN
                self.assertEqual(found, set(),
                                 f"{filename} must not import {found}")

    def test_the_detector_can_actually_see_an_import(self):
        """A structural test that cannot fail proves nothing. recall.py does
        import memory, so the detector must report it."""
        self.assertIn("memory", self.imports_of("recall.py"))


if __name__ == "__main__":
    unittest.main()
