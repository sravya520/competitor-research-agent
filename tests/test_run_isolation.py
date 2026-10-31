"""Two concurrent runs must not share run state.

Run: python -m unittest discover -s tests -v

Streamlit gives each browser session its own AppSession and ScriptRunner
THREAD inside ONE process, so anything held at module level is shared by
every visitor at once. tools.py and pipeline.py both hold run state that
way, and the deployed app serves every visitor from one shared API key, so
two overlapping runs are not a hypothetical.

The three cases below are the three symptoms, each with explicit
interleaving through Events so the result is deterministic rather than a
race that shows up once in fifty runs. Every wait has a timeout: a
regression here must fail the suite, never hang it.

Each test is marked expectedFailure. They describe the behaviour the next
commit introduces, and unittest treats an unexpected success as a failure,
so when the fix lands the suite goes red until the markers come off with it.
"""

import os
import threading
import unittest

os.environ.setdefault("GEMINI_API_KEY", "test-gemini-key")
os.environ.setdefault("TAVILY_API_KEY", "test-tavily-key")

import evaluate  # noqa: E402
import pipeline  # noqa: E402
import tools  # noqa: E402
from retrieval import RetrievedDoc  # noqa: E402
from schemas import Competitor  # noqa: E402

WAIT = 5  # seconds; a deadlock should fail the suite, not stall it


def a_competitor(sources):
    return Competitor(
        name="Studio Nine", why_relevant="r", product_or_service="p",
        target_customers="t", positioning="pos", pricing=None,
        strengths=["s"], weaknesses=["w"], differentiators=["d"],
        sources=list(sources))


def a_document(url):
    return RetrievedDoc(url=url, title="t", content="c", provider="tavily")


class TwoRuns:
    """Runs two callables as threads and fails the test if either stalls."""

    def __init__(self, test, first, second):
        self.test = test
        self.threads = [threading.Thread(target=first, daemon=True),
                        threading.Thread(target=second, daemon=True)]

    def __enter__(self):
        for thread in self.threads:
            thread.start()
        return self

    def __exit__(self, *_):
        for thread in self.threads:
            thread.join(timeout=WAIT)
            self.test.assertFalse(thread.is_alive(),
                                  "a run thread did not finish in time")
        return False


class SourceLedger(unittest.TestCase):
    """The ledger is evidence, so losing it corrupts the report.

    evaluate.drop_fabricated_sources treats the ledger as proof a URL was
    really fetched. If another visitor's run clears it mid-run, a genuine
    citation is stripped as fabricated and the report says the competitor
    has no sources. The anti-hallucination check becomes the thing that
    removes true evidence.
    """

    def setUp(self):
        tools.reset_sources()
        self.addCleanup(tools.reset_sources)

    @unittest.expectedFailure
    def test_one_runs_reset_must_not_empty_the_others_ledger(self):
        fetched = threading.Event()
        reset = threading.Event()
        seen = {}

        def visitor_one():
            tools._record(a_document("https://sproutdesign.in"))
            fetched.set()
            reset.wait(timeout=WAIT)
            seen["sources"] = tools.sources_consulted()

        def visitor_two():
            fetched.wait(timeout=WAIT)
            tools.reset_sources()   # app.py does this on every submit
            reset.set()

        with TwoRuns(self, visitor_one, visitor_two):
            pass

        self.assertEqual(seen.get("sources"), ["https://sproutdesign.in"])

    @unittest.expectedFailure
    def test_a_genuine_citation_must_not_be_stripped_as_fabricated(self):
        fetched = threading.Event()
        reset = threading.Event()
        seen = {}

        def visitor_one():
            tools._record(a_document("https://sproutdesign.in"))
            fetched.set()
            reset.wait(timeout=WAIT)

            competitor = a_competitor(["https://sproutdesign.in"])
            seen["dropped"] = evaluate.drop_fabricated_sources(
                [competitor], tools.sources_consulted())
            seen["left"] = list(competitor.sources)

        def visitor_two():
            fetched.wait(timeout=WAIT)
            tools.reset_sources()
            reset.set()

        with TwoRuns(self, visitor_one, visitor_two):
            pass

        self.assertEqual(seen.get("dropped"), 0,
                         "a URL this run really fetched was called fabricated")
        self.assertEqual(seen.get("left"), ["https://sproutdesign.in"])


class ModelVersions(unittest.TestCase):
    """Mixed versions make the Stage 3 diff lie in both directions.

    A run records which model answered so that a later comparison can tell
    a model rollout from a change in the market. Two visitors mid-rollout
    currently both record both versions, so neither record is true.
    """

    def setUp(self):
        pipeline.reset_model_versions()
        self.addCleanup(pipeline.reset_model_versions)

    @unittest.expectedFailure
    def test_each_run_records_only_its_own_version(self):
        one_noted = threading.Event()
        two_noted = threading.Event()
        seen = {}

        def visitor_one():
            pipeline._note_model_version(
                type("R", (), {"model_version": "gemini-3.5-flash-lite"})())
            one_noted.set()
            two_noted.wait(timeout=WAIT)
            seen["one"] = pipeline.model_versions()

        def visitor_two():
            one_noted.wait(timeout=WAIT)
            pipeline._note_model_version(
                type("R", (), {"model_version": "gemini-3.6-flash-lite"})())
            two_noted.set()
            seen["two"] = pipeline.model_versions()

        with TwoRuns(self, visitor_one, visitor_two):
            pass

        self.assertEqual(seen.get("one"), ["gemini-3.5-flash-lite"])
        self.assertEqual(seen.get("two"), ["gemini-3.6-flash-lite"])


class ProgressHook(unittest.TestCase):
    """Cross-session UI leakage, visible to users.

    app.py points the hook at its own st.status.write. With one hook per
    process, the second visitor to submit captures it, and the first
    visitor's searches then print into a stranger's status panel.
    """

    def setUp(self):
        self.addCleanup(tools.set_progress_hook, print)

    @unittest.expectedFailure
    def test_progress_goes_to_the_run_that_asked_for_it(self):
        one_ready = threading.Event()
        two_ready = threading.Event()
        one_panel, two_panel = [], []

        def visitor_one():
            tools.set_progress_hook(one_panel.append)
            one_ready.set()
            two_ready.wait(timeout=WAIT)
            tools._progress_hook("[search] sprout design")

        def visitor_two():
            one_ready.wait(timeout=WAIT)
            tools.set_progress_hook(two_panel.append)
            two_ready.set()

        with TwoRuns(self, visitor_one, visitor_two):
            pass

        self.assertEqual(one_panel, ["[search] sprout design"])
        self.assertEqual(two_panel, [], "another run's progress leaked in")


if __name__ == "__main__":
    unittest.main()
