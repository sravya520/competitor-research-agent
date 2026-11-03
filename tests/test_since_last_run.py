"""Tests for the "Since your last run" comparison.

Run: python -m unittest discover -s tests -v

The section is arithmetic over two stored lists. No model is asked to
summarise anything, because a delta a model invented would be worse than no
delta at all: a founder reading "Miro is new this month" will act on it.

Two things decide whether it can be trusted.

Matching. Companies are matched by the domain derived from their own cited
sources, never by model-written prose beyond a name fallback. A name match
is allowed only when one side has no domain, and is labelled when used, so
"Adobe Inc. (Creative Cloud)" and "Adobe Creative Cloud / Express" can be
recognised as one company without pretending that is certain.

Honesty about absence. Retrieval varies between runs, so a competitor the
search did not surface this time is evidence about this run, not about the
company. The section says so in fixed wording and never says a competitor
was dropped.

The clock is injected throughout, so none of this depends on when it runs.
"""

import ast
import io
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

os.environ.setdefault("GEMINI_API_KEY", "test-gemini-key")
os.environ.setdefault("TAVILY_API_KEY", "test-tavily-key")

import memory  # noqa: E402
import recall  # noqa: E402
import report as report_module  # noqa: E402
from schemas import Competitor, CompetitorResearch  # noqa: E402

NOW = datetime(2026, 11, 3, 12, 0, 0, tzinfo=timezone.utc)
SCALE = "about 120 staff, Series B"


def stamp(days_ago):
    return (NOW - timedelta(days=days_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")


def rival(name, sources=(), pricing=None, positioning="Positioned somewhere"):
    """A stand-in competitor. memory reads these with getattr."""
    return SimpleNamespace(name=name, positioning=positioning, pricing=pricing,
                           sources=list(sources), scale_and_stage=SCALE)


def identity(website="https://notion.so"):
    return SimpleNamespace(description="Workspace tool", location="US",
                           website=website, scale_and_stage=SCALE)


class DerivedDomain(unittest.TestCase):
    """S0: the domain comes from the sources, by whole-token equality."""

    def test_the_five_real_linear_competitors(self):
        """Taken from the live Part B run: four resolve, ClickUp does not,
        because neither of its cited sources is its own site."""
        cases = [
            ("Jira (Atlassian)",
             ["https://www.cbinsights.com/company/linear-1",
              "https://www.atlassian.com/software/jira"], "atlassian.com"),
            ("monday dev", ["https://monday.com/pricing"], "monday.com"),
            ("ClickUp", ["https://starthubasia.com/clickup-review",
                         "https://www.techrepublic.com/article/clickup-review"], ""),
            ("GitHub Issues & Projects", ["https://github.com/github"],
             "github.com"),
            ("Plane", ["https://plane.so/pricing",
                       "https://www.ideaplan.io/alternatives/linear"], "plane.so"),
        ]
        for name, sources, expected in cases:
            with self.subTest(name=name):
                self.assertEqual(memory.competitor_domain(rival(name, sources)),
                                 expected)

    def test_a_substring_is_not_a_match(self):
        """planet.com is not Plane's site. Containment would claim it is,
        and neither the token rule nor the whole-name rule admits it."""
        self.assertEqual(
            memory.competitor_domain(rival("Plane", ["https://planet.com/x"])),
            "")

    def test_a_hyphenated_domain_matches_the_whole_name(self):
        """How a two-word name is usually registered. The hyphen is gone by
        the time the label is read, so it compares against the name with
        its spaces closed up."""
        self.assertEqual(
            memory.competitor_domain(
                rival("Sprout Design", ["https://sprout-design.co.uk/work"])),
            "sprout-design.co.uk")

    def test_the_whole_name_rule_is_still_equality(self):
        """"sproutdesigns" and "sproutdesignstudio" are other companies."""
        for host in ("https://sproutdesigns.com", "https://sproutdesignstudio.com"):
            with self.subTest(host=host):
                self.assertEqual(
                    memory.competitor_domain(rival("Sprout Design", [host])), "")

    def test_two_matching_hosts_give_no_domain(self):
        """Ambiguous is worse than empty: the caller falls back to the name."""
        self.assertEqual(
            memory.competitor_domain(
                rival("Acme", ["https://acme.com", "https://acme.io"])),
            "")

    def test_a_directory_host_is_allowed_through_the_token_match(self):
        """DIRECTORY_HOSTS stops github.com being a company KEY. Here it is
        admissible, but only for a company whose name holds that token."""
        self.assertIn("github.com", memory.DIRECTORY_HOSTS)
        self.assertEqual(
            memory.competitor_domain(rival("GitHub Issues & Projects",
                                           ["https://github.com/x"])),
            "github.com")
        self.assertEqual(
            memory.competitor_domain(rival("Linear",
                                           ["https://github.com/linear"])),
            "", "no other competitor may claim a platform host")

    def test_a_subdomain_reduces_to_the_company_domain(self):
        """Two runs citing different pages must still match as one company."""
        self.assertEqual(
            memory.competitor_domain(rival("Notion",
                                           ["https://blog.notion.so/post"])),
            "notion.so")

    def test_it_is_stored_in_the_record(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "memory.jsonl")
            record = memory.record_run(
                path=path, company_name="Linear", identity=identity(),
                competitors=[rival("Plane", ["https://plane.so"])])
        self.assertEqual(record["schema_version"], 5)
        self.assertEqual(record["competitors"][0]["competitor_domain"],
                         "plane.so")


class Comparison(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = os.path.join(self.directory.name, "memory.jsonl")

    def previous(self, competitors, days_ago=3, **kwargs):
        return memory.record_run(
            path=self.path, company_name="Notion", identity=identity(),
            competitors=competitors, run_at=stamp(days_ago), **kwargs)

    def compare(self, competitors, key="notion.so", strong=True, **kwargs):
        return recall.since_last_run(key, strong, competitors, path=self.path,
                                     now=NOW, **kwargs)

    # --- when there is nothing to say ------------------------------------

    def test_no_prior_record_means_no_section(self):
        self.assertIsNone(self.compare([rival("Coda")]))

    def test_memory_off_means_no_section(self):
        """No path and no MEMORY_PATH: nothing is read, so nothing to compare."""
        previous = os.environ.pop(memory.LEDGER_PATH_ENV, None)
        if previous is not None:
            self.addCleanup(os.environ.__setitem__, memory.LEDGER_PATH_ENV,
                            previous)

        self.previous([rival("Coda", ["https://coda.io"])])
        self.assertIsNone(recall.since_last_run(
            "notion.so", True, [rival("Coda")], now=NOW))

    def test_a_weak_key_is_skipped(self):
        """Two runs under a name-based key may be two different companies.
        Comparing them would invent a trend out of an ambiguity."""
        memory.record_run(path=self.path, company_name="Sprout Design",
                          identity=identity(website=None), run_at=stamp(2),
                          competitors=[rival("Studio Nine")])
        self.assertIsNone(self.compare([rival("Studio Nine")],
                                       key="name:sprout-design", strong=False))

    # --- the three lists --------------------------------------------------

    def test_an_unchanged_set_is_all_still_present(self):
        self.previous([rival("Coda", ["https://coda.io"]),
                       rival("Miro", ["https://miro.com"])])

        result = self.compare([rival("Coda", ["https://coda.io"]),
                               rival("Miro", ["https://miro.com"])])

        self.assertEqual(result["new"], [])
        self.assertEqual(result["not_found"], [])
        self.assertEqual([e["name"] for e in result["still_present"]],
                         ["Coda", "Miro"])
        self.assertEqual(result["previous_run_at"], stamp(3))
        self.assertAlmostEqual(result["age_days"], 3.0, places=3)

    def test_one_new_competitor(self):
        self.previous([rival("Coda", ["https://coda.io"])])

        result = self.compare([rival("Coda", ["https://coda.io"]),
                               rival("Canva", ["https://canva.com"])])

        self.assertEqual(result["new"], ["Canva"])
        self.assertEqual(result["not_found"], [])

    def test_one_not_found_this_time(self):
        self.previous([rival("Coda", ["https://coda.io"]),
                       rival("Miro", ["https://miro.com"])])

        result = self.compare([rival("Coda", ["https://coda.io"])])

        self.assertEqual(result["not_found"], ["Miro"])
        self.assertEqual(result["new"], [])

    def test_an_excluded_competitor_is_not_called_not_found(self):
        """It was found this run and then rejected, which is a different
        fact from the search not surfacing it."""
        self.previous([rival("Coda", ["https://coda.io"]),
                       rival("Acme", ["https://acme.com"])])

        result = self.compare([rival("Coda", ["https://coda.io"])],
                              excluded_names=["Acme"])

        self.assertEqual(result["not_found"], [])

    # --- matching ---------------------------------------------------------

    def test_a_domain_match_survives_a_different_name(self):
        """The real case: Adobe was named two ways across two live runs."""
        self.previous([rival("Adobe Creative Cloud / Express",
                             ["https://adobe.com/express"])])

        result = self.compare([rival("Adobe Inc. (Creative Cloud)",
                                     ["https://adobe.com/creativecloud"])])

        self.assertEqual(result["new"], [])
        self.assertEqual([e["name"] for e in result["still_present"]],
                         ["Adobe Inc. (Creative Cloud)"])
        self.assertFalse(result["still_present"][0]["matched_by_name"])

    def test_a_name_match_is_used_and_labelled_when_a_domain_is_missing(self):
        self.previous([rival("ClickUp", ["https://techrepublic.com/review"])])

        result = self.compare([rival("ClickUp", ["https://g2.com/clickup"])])

        self.assertEqual(result["new"], [])
        self.assertTrue(result["still_present"][0]["matched_by_name"])

    def test_a_trailing_parenthetical_does_not_split_one_company(self):
        """The real pair from two live Linear runs: the model wrote "Jira
        (Atlassian)" once and "Jira" the next time, and the comparison read
        that as one company leaving and another arriving."""
        self.previous([rival(
            "Jira (Atlassian)",
            ["https://www.cbinsights.com/company/linear-1/alternatives-competitors",
             "https://www.atlassian.com/software/jira/product-discovery/enterprise"])])

        result = self.compare([rival(
            "Jira",
            ["https://en.wikipedia.org/wiki/Jira_(software)",
             "https://www.atlassian.com/software/jira/guides/getting-started",
             "https://clickup.com/blog/linear-alternatives"])])

        self.assertEqual(result["new"], [])
        self.assertEqual(result["not_found"], [])
        self.assertEqual([e["name"] for e in result["still_present"]], ["Jira"],
                         "display keeps the name this run used")
        self.assertTrue(result["still_present"][0]["matched_by_name"])

    def test_a_parenthetical_is_only_stripped_from_the_end(self):
        """A name that is only a parenthetical still compares as itself."""
        self.previous([rival("(Stealth)", ["https://example.com"])])
        result = self.compare([rival("(Stealth)", ["https://example.com"])])
        self.assertEqual(result["not_found"], [])

    def test_two_different_domains_are_two_different_companies(self):
        """A name match must not override conflicting domains."""
        self.previous([rival("Acme", ["https://acme.com"])])

        result = self.compare([rival("Acme", ["https://acme.io"])])

        self.assertEqual(result["new"], ["Acme"])
        self.assertEqual(result["not_found"], ["Acme"])

    def test_an_old_record_without_domains_still_compares(self):
        """Schema 4 and earlier have no competitor_domain. Those records
        fall back to the name rather than reading as all-new."""
        record = memory.build_record(
            company_name="Notion", identity=identity(), run_at=stamp(5),
            competitors=[rival("Coda", ["https://coda.io"])])
        for entry in record["competitors"]:
            del entry["competitor_domain"]
        memory.append_record(record, self.path)

        result = self.compare([rival("Coda", ["https://coda.io"])])

        self.assertEqual(result["new"], [])
        self.assertTrue(result["still_present"][0]["matched_by_name"])

    # --- pricing and provenance ------------------------------------------

    def test_pricing_is_reported_only_when_both_runs_have_a_value(self):
        self.previous([rival("Coda", ["https://coda.io"], pricing="$10/mo"),
                       rival("Miro", ["https://miro.com"], pricing=None)])

        result = self.compare([
            rival("Coda", ["https://coda.io"], pricing="$12/mo"),
            rival("Miro", ["https://miro.com"], pricing="$8/mo")])

        by_name = {e["name"]: e for e in result["still_present"]}
        self.assertEqual(by_name["Coda"]["pricing_before"], "$10/mo")
        self.assertEqual(by_name["Coda"]["pricing_after"], "$12/mo")
        self.assertIsNone(by_name["Miro"]["pricing_before"],
                          "one side unknown is missing data, not a price move")

    def test_an_unchanged_price_is_not_reported_as_a_change(self):
        self.previous([rival("Coda", ["https://coda.io"], pricing="$10/mo")])
        result = self.compare([rival("Coda", ["https://coda.io"],
                                     pricing="$10/mo")])
        self.assertIsNone(result["still_present"][0]["pricing_before"])

    def test_the_same_figures_reworded_are_not_a_price_change(self):
        """Both strings are real, from two live runs forty seconds apart.
        The figures are identical; only the prose moved."""
        before = ("Free forever plan; Unlimited plan at $7/user/month; "
                  "Business plan at $12/user/month.")
        after = ("Free Forever plan; Unlimited plan from $7/user/month; "
                 "Business plan from $12/user/month (billed annually).")
        self.previous([rival("ClickUp", ["https://clickup.com"],
                             pricing=before)])

        result = self.compare([rival("ClickUp", ["https://clickup.com"],
                                     pricing=after)])

        self.assertIsNone(result["still_present"][0]["pricing_before"])

    def test_a_figure_on_only_one_side_is_not_a_price_change(self):
        """One run quoting a price and the other not is missing data. Also
        stops a version number such as AGPL-3.0 reading as a figure."""
        self.previous([rival("Plane", ["https://plane.so"],
                             pricing="cloud tiers from $6/seat/month.")])

        result = self.compare([rival("Plane", ["https://plane.so"],
                                     pricing="Free Community Edition "
                                             "(AGPL-3.0), cloud available.")])

        self.assertIsNone(result["still_present"][0]["pricing_before"])

    def test_a_real_figure_change_is_still_reported(self):
        self.previous([rival("Coda", ["https://coda.io"],
                             pricing="Team plan at $10/user/month")])

        result = self.compare([rival("Coda", ["https://coda.io"],
                                     pricing="Team plan at $12/user/month")])

        entry = result["still_present"][0]
        self.assertEqual(entry["pricing_before"], "Team plan at $10/user/month")
        self.assertEqual(entry["pricing_after"], "Team plan at $12/user/month")

    def test_a_model_change_is_reported(self):
        self.previous([rival("Coda", ["https://coda.io"])],
                      model_resolved=["gemini-3.5-flash-lite"],
                      retrieval_provider="tavily")

        result = self.compare([rival("Coda", ["https://coda.io"])],
                              current_model_resolved=["gemini-3.6-flash-lite"],
                              current_retrieval_provider="tavily")

        self.assertIsNotNone(result["provenance_changed"])
        self.assertEqual(result["provenance_changed"]["previous_model"],
                         ["gemini-3.5-flash-lite"])

    def test_the_same_setup_reports_no_provenance_change(self):
        self.previous([rival("Coda", ["https://coda.io"])],
                      model_resolved=["gemini-3.5-flash-lite"],
                      retrieval_provider="tavily")

        result = self.compare([rival("Coda", ["https://coda.io"])],
                              current_model_resolved=["gemini-3.5-flash-lite"],
                              current_retrieval_provider="tavily")

        self.assertIsNone(result["provenance_changed"])

    def test_a_retrieval_change_is_reported(self):
        self.previous([rival("Coda", ["https://coda.io"])],
                      model_resolved=["gemini-3.5-flash-lite"],
                      retrieval_provider="tavily")

        result = self.compare([rival("Coda", ["https://coda.io"])],
                              current_model_resolved=["gemini-3.5-flash-lite"],
                              current_retrieval_provider="firecrawl")

        self.assertIsNotNone(result["provenance_changed"])


class RenderedSection(unittest.TestCase):
    """What a reader actually sees."""

    def report(self, comparison):
        return report_module.build_report(
            company_name="Notion", company_url="https://notion.so",
            identity=identity(),
            research=CompetitorResearch(company_name="Notion", competitors=[],
                                        market_trends=[],
                                        market_gaps_opportunities=[],
                                        potential_threats=[]),
            competitors=[Competitor(
                name="Coda", why_relevant="r", product_or_service="p",
                target_customers="t", positioning="pos", pricing=None,
                strengths=["s"], weaknesses=["w"], differentiators=["d"],
                sources=["https://coda.io"])],
            excluded=[], sources=["https://coda.io"],
            since_last_run=comparison)

    def base(self, **overrides):
        comparison = {"previous_run_at": "2026-10-31T09:00:00Z",
                      "age_days": 3.0, "provenance_changed": None,
                      "new": [], "not_found": [], "still_present": []}
        comparison.update(overrides)
        return comparison

    def test_no_comparison_means_no_section(self):
        self.assertNotIn("Since your last run", self.report(None))

    def test_the_heading_carries_the_date_and_the_age(self):
        content = self.report(self.base(new=["Canva"]))
        self.assertIn("## Since your last run on 2026-10-31 (3 days ago)",
                      content)

    def test_a_same_day_rerun_reads_sensibly(self):
        content = self.report(self.base(age_days=0.2, new=["Canva"]))
        self.assertIn("(earlier today)", content)

    def test_absence_is_never_called_a_drop(self):
        content = self.report(self.base(not_found=["Miro"]))
        self.assertIn("**Not found this time:**", content)
        self.assertIn("Live search varies between runs, so this does not mean "
                      "the company stopped competing.", content)
        for forbidden in ("dropped", "disappeared", "no longer competes"):
            self.assertNotIn(forbidden, content.casefold())

    def test_a_name_match_is_visible_to_the_reader(self):
        content = self.report(self.base(still_present=[
            {"name": "ClickUp", "matched_by_name": True,
             "pricing_before": None, "pricing_after": None}]))
        self.assertIn("ClickUp _(matched by name)_", content)

    def test_a_price_change_is_shown_with_both_values(self):
        content = self.report(self.base(still_present=[
            {"name": "Coda", "matched_by_name": False,
             "pricing_before": "$10/mo", "pricing_after": "$12/mo"}]))
        self.assertIn("pricing changed: $10/mo to $12/mo", content)

    def test_a_setup_change_is_stated_before_the_lists(self):
        content = self.report(self.base(
            new=["Canva"],
            provenance_changed={"previous_model": ["gemini-3.5-flash-lite"],
                                "current_model": ["gemini-3.6-flash-lite"],
                                "previous_provider": "tavily",
                                "current_provider": "firecrawl"}))

        warning = content.index("did not use the same setup")
        self.assertLess(warning, content.index("**New this run:**"))
        self.assertIn("gemini-3.5-flash-lite previously", content)
        self.assertIn("tavily previously", content)

    def test_the_section_precedes_the_competitor_list(self):
        content = self.report(self.base(new=["Canva"]))
        self.assertLess(content.index("Since your last run"),
                        content.index("## Competitors"))


class Layering(unittest.TestCase):
    """The pipeline still knows nothing about memory.

    Asserted again at this stage, overlapping test_run_isolation.Layering on
    purpose: this stage added imports to recall.py and a parameter to
    report.py, which is exactly when a shortcut into pipeline.py would be
    tempting. report.py is included because it must stay a formatter: it
    receives a plain dict and never reaches into the ledger itself.
    """

    FORBIDDEN = {"memory", "recall"}
    ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    def imports_of(self, filename):
        source = io.open(os.path.join(self.ROOT, filename),
                         encoding="utf-8").read()
        names = set()
        for node in ast.walk(ast.parse(source, filename)):
            if isinstance(node, ast.Import):
                names.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                names.add(node.module.split(".")[0])
        return names

    def test_the_pipeline_the_evals_and_the_report_stay_memory_free(self):
        for filename in ("pipeline.py", "prompts.py", "evaluate.py",
                         "run_eval.py", "report.py"):
            with self.subTest(filename=filename):
                found = self.imports_of(filename) & self.FORBIDDEN
                self.assertEqual(found, set(),
                                 f"{filename} must not import {found}")

    def test_the_detector_can_see_an_import(self):
        self.assertIn("memory", self.imports_of("recall.py"))


if __name__ == "__main__":
    unittest.main()
