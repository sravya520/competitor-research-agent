"""Tests for the web UI's memory flow, driven through Streamlit's AppTest.

Run: python -m unittest discover -s tests -v

Everything else about memory is tested against plain functions, but the
suggest-and-confirm flow only exists as Streamlit wiring: a form, a set of
buttons built from a list, and a rerun. Reading it is not evidence that
clicking it works, and this is the one part a user touches directly.

No API call is made. recall.establish_identity and the two research calls
are replaced, and what each test actually asserts is the arguments the app
passed them, not the text on the screen: that a candidate button leads to a
run with the remembered URL is the claim, and the label is decoration.

The API key variables are dummies, and MEMORY_PATH points at a temporary
ledger seeded per test, so nothing here reads or writes real history.
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
import pipeline  # noqa: E402
import recall  # noqa: E402
from schemas import (  # noqa: E402
    Competitor,
    CompetitorResearch,
    CompetitorVerification,
)
from streamlit.testing.v1 import AppTest  # noqa: E402

APP = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "app.py")
TIMEOUT = 30

NOW = datetime.now(timezone.utc)

# Index of each widget in app.py's form, in declaration order.
NAME, URL = 0, 1
RESEARCH_BUTTON = 0
FIRST_CANDIDATE = 1


def stamp(days_ago):
    return (NOW - timedelta(days=days_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")


def an_identity(description="A design agency", website="https://sproutdesign.in"):
    return SimpleNamespace(description=description, location="IN",
                           website=website, confident_match=True,
                           ambiguity_note=None)


class MemoryFlow(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = os.path.join(self.directory.name, "memory.jsonl")

        previous = os.environ.get(memory.LEDGER_PATH_ENV)
        os.environ[memory.LEDGER_PATH_ENV] = self.path
        self.addCleanup(self._restore_env, previous)

        self.establish_calls = []
        self.patch(recall, "establish_identity", self.fake_establish)
        self.patch(pipeline, "research_competitors", self.fake_research)
        self.patch(pipeline, "verify_competitors", self.fake_verify)

    def _restore_env(self, previous):
        if previous is None:
            os.environ.pop(memory.LEDGER_PATH_ENV, None)
        else:
            os.environ[memory.LEDGER_PATH_ENV] = previous

    def patch(self, module, name, replacement):
        patcher = patch.object(module, name, side_effect=replacement)
        patcher.start()
        self.addCleanup(patcher.stop)

    # --- stand-ins for the expensive steps --------------------------------

    def fake_establish(self, company_name, company_url, allow_recall=True,
                       **kwargs):
        self.establish_calls.append({"name": company_name, "url": company_url,
                                     "allow_recall": allow_recall})
        return an_identity(), None

    def fake_research(self, company_name, identity):
        return CompetitorResearch(
            company_name=company_name,
            competitors=[Competitor(
                name="Studio Nine", why_relevant="Same category",
                product_or_service="Branding", target_customers="Startups",
                positioning="Boutique", pricing=None, strengths=["focus"],
                weaknesses=["small"], differentiators=["craft"], sources=[])],
            market_trends=[], market_gaps_opportunities=[],
            potential_threats=[])

    def fake_verify(self, company_name, identity, competitors):
        return [CompetitorVerification(index=0, name="Studio Nine",
                                       verified=True, reason="Checked.")]

    # --- helpers ----------------------------------------------------------

    def remember(self, name, website, days_ago=3):
        memory.record_run(
            path=self.path, company_name=name, company_url=website,
            identity=SimpleNamespace(description=f"{name} the company",
                                     location="IN", website=website),
            run_at=stamp(days_ago))

    def started(self):
        app = AppTest.from_file(APP, default_timeout=TIMEOUT)
        app.run()
        self.assertEqual(len(app.exception), 0,
                         f"the app should load cleanly: {app.exception}")
        return app

    def submit(self, app, name, url="", fresh_identity=False):
        app.text_input[NAME].set_value(name)
        app.text_input[URL].set_value(url)
        app.checkbox[0].set_value(fresh_identity)
        app.button[RESEARCH_BUTTON].click()
        app.run()
        return app

    # --- the flow ---------------------------------------------------------

    def test_a_name_only_run_offers_the_remembered_websites(self):
        self.remember("Sprout Design", "https://sproutdesign.in", days_ago=3)
        self.remember("Sprout Design", "https://sprout-design.co.uk",
                      days_ago=40)

        app = self.submit(self.started(), "Sprout Design")

        self.assertEqual(app.session_state["stage"], "choose_url")
        self.assertEqual(self.establish_calls, [],
                         "nothing should run until the user confirms")

        labels = [button.label for button in app.button]
        self.assertTrue(any("sproutdesign.in" in label for label in labels))
        self.assertTrue(any("sprout-design.co.uk" in label for label in labels))
        self.assertTrue(any("3 days ago" in label for label in labels),
                        "each candidate shows its age")
        self.assertTrue(any(label == "None of these" for label in labels))

    def test_no_history_goes_straight_to_research(self):
        app = self.submit(self.started(), "Sprout Design")

        self.assertEqual(len(self.establish_calls), 1)
        self.assertEqual(self.establish_calls[0]["url"], "")
        self.assertEqual(app.session_state["stage"], "review")

    def test_clicking_a_candidate_runs_with_that_url(self):
        self.remember("Sprout Design", "https://sproutdesign.in", days_ago=3)
        app = self.submit(self.started(), "Sprout Design")

        app.button[FIRST_CANDIDATE].click()
        app.run()

        self.assertEqual(len(self.establish_calls), 1)
        self.assertEqual(self.establish_calls[0]["url"],
                         "https://sproutdesign.in")
        self.assertEqual(app.session_state["stage"], "review")
        self.assertEqual(app.session_state["url_remembered"]["key"],
                         "sproutdesign.in")

    def test_none_of_these_continues_as_a_name_only_run(self):
        self.remember("Sprout Design", "https://sproutdesign.in", days_ago=3)
        app = self.submit(self.started(), "Sprout Design")

        none_of_these = next(index for index, button in enumerate(app.button)
                             if button.label == "None of these")
        app.button[none_of_these].click()
        app.run()

        self.assertEqual(len(self.establish_calls), 1)
        self.assertEqual(self.establish_calls[0]["url"], "",
                         "declining must not quietly use a remembered URL")
        self.assertIsNone(app.session_state["url_remembered"])
        self.assertEqual(app.session_state["stage"], "review")

    def test_a_typed_url_skips_the_offer_entirely(self):
        self.remember("Sprout Design", "https://sprout-design.co.uk")
        app = self.submit(self.started(), "Sprout Design",
                          url="https://sproutdesign.in")

        self.assertEqual(app.session_state["stage"], "review")
        self.assertEqual(self.establish_calls[0]["url"],
                         "https://sproutdesign.in")

    # --- the override -----------------------------------------------------

    def test_the_checkbox_forces_a_live_identify(self):
        self.remember("Sprout Design", "https://sproutdesign.in")
        self.submit(self.started(), "Sprout Design",
                    url="https://sproutdesign.in", fresh_identity=True)

        self.assertFalse(self.establish_calls[0]["allow_recall"])

    def test_unchecked_allows_reuse(self):
        self.remember("Sprout Design", "https://sproutdesign.in")
        self.submit(self.started(), "Sprout Design",
                    url="https://sproutdesign.in", fresh_identity=False)

        self.assertTrue(self.establish_calls[0]["allow_recall"])

    def test_the_override_survives_a_candidate_click(self):
        """The checkbox is on the form, the click happens a rerun later, so
        the choice has to be carried in session state rather than read from
        the widget."""
        self.remember("Sprout Design", "https://sproutdesign.in")
        app = self.submit(self.started(), "Sprout Design", fresh_identity=True)

        app.button[FIRST_CANDIDATE].click()
        app.run()

        self.assertFalse(self.establish_calls[0]["allow_recall"])

    # --- housekeeping -----------------------------------------------------

    def test_an_empty_name_is_rejected_before_anything_runs(self):
        app = self.submit(self.started(), "   ")

        self.assertEqual(self.establish_calls, [])
        self.assertTrue(any("Enter a company name" in error.value
                            for error in app.error))

    def test_the_daily_limit_shows_the_example_report(self):
        """A visitor arriving after the shared key is spent should still see
        what the tool produces, not just an apology."""
        from google.genai import errors

        quota = errors.APIError(429, {"error": {
            "code": 429, "status": "RESOURCE_EXHAUSTED", "message": "spent"}})

        with patch.object(recall, "establish_identity", side_effect=quota):
            app = self.submit(self.started(), "Sprout Design",
                              url="https://sproutdesign.in")

        self.assertTrue(any("daily usage limit" in error.value
                            for error in app.error))
        self.assertTrue(any("saved example" in info.value for info in app.info))
        self.assertTrue(
            any("Competitor Research" in block.value for block in app.markdown),
            "the example report itself should be on the page")
        self.assertEqual(app.session_state["stage"], "input",
                         "the form stays usable for a later try")

    def test_the_example_is_labelled_as_not_the_visitors_result(self):
        """A full report appearing after a failure could be mistaken for the
        visitor's own output, which would be worse than showing nothing. The
        page has to say so before the report and again beside it."""
        from google.genai import errors

        quota = errors.APIError(429, {"error": {
            "code": 429, "status": "RESOURCE_EXHAUSTED", "message": "spent"}})

        with patch.object(recall, "establish_identity", side_effect=quota):
            app = self.submit(self.started(), "Sprout Design",
                              url="https://sproutdesign.in")

        notice = " ".join(info.value for info in app.info).casefold()
        self.assertIn("saved example", notice)
        self.assertIn("nothing was researched for you", notice)
        self.assertIn("not a report about the company you entered", notice)

        beside = " ".join(caption.value for caption in app.caption).casefold()
        self.assertIn("saved example", beside)
        self.assertIn("not your result", beside)

    def test_another_failure_does_not_show_the_example(self):
        """Only the shared-quota case. An upstream blip is worth retrying in
        a minute, and a wall of example text would just be in the way."""
        from google.genai import errors

        blip = errors.APIError(503, {"error": {
            "code": 503, "status": "UNAVAILABLE", "message": "busy"}})

        with patch.object(recall, "establish_identity", side_effect=blip):
            app = self.submit(self.started(), "Sprout Design",
                              url="https://sproutdesign.in")

        self.assertTrue(any("503" in error.value for error in app.error))
        self.assertFalse(any("real report" in info.value for info in app.info))

    def test_memory_off_offers_nothing(self):
        """The hosted demo: MEMORY_PATH unset, so no history is consulted
        even though this ledger file exists."""
        self.remember("Sprout Design", "https://sproutdesign.in")
        os.environ.pop(memory.LEDGER_PATH_ENV, None)

        app = self.submit(self.started(), "Sprout Design")

        self.assertEqual(app.session_state["stage"], "review")
        self.assertEqual(self.establish_calls[0]["url"], "")


if __name__ == "__main__":
    unittest.main()
