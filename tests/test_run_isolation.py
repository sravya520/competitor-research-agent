"""Two concurrent runs must not share run state.

Run: python -m unittest discover -s tests -v

Streamlit gives each browser session its own AppSession and ScriptRunner
THREAD inside ONE process, so anything held at module level is shared by
every visitor at once. tools.py used to hold the source ledger, the progress
hook and the truncation counters that way, and pipeline.py the model
versions. The deployed app serves every visitor from one shared API key, so
two overlapping runs were never hypothetical.

The three symptoms are each a deterministic two-thread case with explicit
interleaving through Events, rather than a race that shows up once in fifty
runs. Every wait has a timeout: a regression here must fail the suite, never
hang it.

The worst symptom was the ledger. evaluate.drop_fabricated_sources treats it
as proof a URL was really fetched, so when another visitor submitted and
cleared it mid-run, a genuine citation was stripped as fabricated and the
report said the competitor had no sources. The anti-hallucination check was
deleting true evidence.

Also pinned here: the schema the SDK sends to Gemini for each tool. The
tools are now closures built per run, and a closure that lost its name,
parameters or docstring would change the prompt without changing any
behaviour a test would otherwise notice.
"""

import os
import tempfile
import threading
import unittest
from pathlib import Path

os.environ.setdefault("GEMINI_API_KEY", "test-gemini-key")
os.environ.setdefault("TAVILY_API_KEY", "test-tavily-key")

import evaluate  # noqa: E402
import pipeline  # noqa: E402
import tools  # noqa: E402
from config import gemini_client  # noqa: E402
from google.genai import types  # noqa: E402
from retrieval import ResponseCache, RetrievedDoc, TavilyProvider  # noqa: E402
from runstate import RunState  # noqa: E402
from schemas import Competitor  # noqa: E402

WAIT = 5  # seconds; a deadlock should fail the suite, not stall it


def a_competitor(sources):
    return Competitor(
        name="Studio Nine", why_relevant="r", product_or_service="p",
        target_customers="t", positioning="pos", pricing=None,
        strengths=["s"], weaknesses=["w"], differentiators=["d"],
        sources=list(sources))


def tavily_client(search_results=None, extract_results=None):
    """A stub Tavily client that answers from canned payloads."""

    class Client:
        def search(self, *_args, **_kwargs):
            return {"results": search_results or []}

        def extract(self, *_args, **_kwargs):
            return {"results": extract_results or []}

    return Client()


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
    def test_one_runs_work_is_invisible_to_the_other(self):
        one_fetched = threading.Event()
        two_fetched = threading.Event()
        seen = {}

        def visitor_one():
            run = RunState(progress=None)
            run.record_source("https://sproutdesign.in")
            one_fetched.set()
            two_fetched.wait(timeout=WAIT)
            seen["one"] = run.sources_consulted()

        def visitor_two():
            one_fetched.wait(timeout=WAIT)
            run = RunState(progress=None)
            run.record_source("https://sprout-design.co.uk")
            two_fetched.set()
            seen["two"] = run.sources_consulted()

        with TwoRuns(self, visitor_one, visitor_two):
            pass

        self.assertEqual(seen.get("one"), ["https://sproutdesign.in"])
        self.assertEqual(seen.get("two"), ["https://sprout-design.co.uk"])

    def test_a_genuine_citation_is_not_stripped_as_fabricated(self):
        """The symptom that made this worth fixing: another run starting
        mid-flight used to empty the ledger this check reads as proof."""
        one_fetched = threading.Event()
        two_started = threading.Event()
        seen = {}

        def visitor_one():
            run = RunState(progress=None)
            run.record_source("https://sproutdesign.in")
            one_fetched.set()
            two_started.wait(timeout=WAIT)

            competitor = a_competitor(["https://sproutdesign.in"])
            seen["dropped"] = evaluate.drop_fabricated_sources(
                [competitor], run.sources_consulted())
            seen["left"] = list(competitor.sources)

        def visitor_two():
            one_fetched.wait(timeout=WAIT)
            RunState(progress=None).record_source("https://elsewhere.example")
            two_started.set()

        with TwoRuns(self, visitor_one, visitor_two):
            pass

        self.assertEqual(seen.get("dropped"), 0,
                         "a URL this run really fetched was called fabricated")
        self.assertEqual(seen.get("left"), ["https://sproutdesign.in"])


class ModelVersions(unittest.TestCase):
    """Mixed versions would make the Stage 3 diff lie in both directions."""

    def test_each_run_records_only_its_own_version(self):
        one_noted = threading.Event()
        two_noted = threading.Event()
        seen = {}

        def response(version):
            return type("R", (), {"model_version": version})()

        def visitor_one():
            run = RunState(progress=None)
            pipeline._note_model_version(run, response("gemini-3.5-flash-lite"))
            one_noted.set()
            two_noted.wait(timeout=WAIT)
            seen["one"] = run.model_versions()

        def visitor_two():
            one_noted.wait(timeout=WAIT)
            run = RunState(progress=None)
            pipeline._note_model_version(run, response("gemini-3.6-flash-lite"))
            two_noted.set()
            seen["two"] = run.model_versions()

        with TwoRuns(self, visitor_one, visitor_two):
            pass

        self.assertEqual(seen.get("one"), ["gemini-3.5-flash-lite"])
        self.assertEqual(seen.get("two"), ["gemini-3.6-flash-lite"])


class ProgressOutput(unittest.TestCase):
    """Cross-session UI leakage, which was visible to users.

    app.py points the progress sink at its own st.status.write. With one
    hook per process, the second visitor to submit captured it and the
    first visitor's searches printed into a stranger's status panel.
    """

    def test_progress_goes_to_the_run_that_asked_for_it(self):
        one_ready = threading.Event()
        two_ready = threading.Event()
        one_panel, two_panel = [], []

        def visitor_one():
            run = RunState(progress=one_panel.append)
            one_ready.set()
            two_ready.wait(timeout=WAIT)
            run.progress("[search] sprout design")

        def visitor_two():
            one_ready.wait(timeout=WAIT)
            RunState(progress=two_panel.append)
            two_ready.set()

        with TwoRuns(self, visitor_one, visitor_two):
            pass

        self.assertEqual(one_panel, ["[search] sprout design"])
        self.assertEqual(two_panel, [], "another run's progress leaked in")

    def test_a_run_nobody_watches_is_silent(self):
        """app.py builds its run before it has a status panel to write to."""
        RunState(progress=None).progress("[search] nobody is listening")


class SharedCaches(unittest.TestCase):
    """The caches SHOULD be shared. The ledgers must not be.

    A provider instance holds the HTTP clients, the disk response cache and
    the credit meter, and sharing those is the point: a warm cache is why a
    rerun costs no credits. None of that may blur two runs' evidence.
    """

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.cache = ResponseCache(directory=Path(self.directory.name),
                                   enabled=True)

    def provider(self):
        return TavilyProvider(
            client=tavily_client(search_results=[
                {"title": "T", "url": "https://good.example", "content": "c"}]),
            cache=self.cache, throttle=False)

    def test_a_cache_hit_still_records_the_url_in_this_runs_ledger(self):
        """Second run, warm cache, no network: the URL is still evidence.

        Whether the bytes came from the network or from disk is a billing
        detail. The report's claim is that this run consulted the page, and
        it did.
        """
        shared = self.provider()

        first = RunState(progress=None, provider=shared)
        tools.make_tools(first)[0]("acme")
        self.assertEqual(first.sources_consulted(), ["https://good.example"])
        self.assertEqual(self.cache.misses, 1)

        second = RunState(progress=None, provider=shared)
        tools.make_tools(second)[0]("acme")
        self.assertEqual(self.cache.hits, 1, "the second run should hit cache")
        self.assertEqual(second.sources_consulted(), ["https://good.example"])

    def test_two_runs_on_one_provider_keep_separate_ledgers(self):
        shared = self.provider()

        first = RunState(progress=None, provider=shared)
        second = RunState(progress=None, provider=shared)

        tools.make_tools(first)[0]("acme")
        second.record_source("https://only-the-second.example")

        self.assertEqual(first.sources_consulted(), ["https://good.example"])
        self.assertEqual(second.sources_consulted(),
                         ["https://only-the-second.example"])

    def test_the_process_wide_provider_is_built_once(self):
        tools.reset_providers()
        self.addCleanup(tools.reset_providers)
        self.assertIs(tools.provider_for("tavily"), tools.provider_for("tavily"))


class ToolSchema(unittest.TestCase):
    """The declared schema is prompt text, so pin it.

    make_tools returns closures. A closure that lost its __name__, its
    annotations or its docstring would still run, still pass every other
    test, and quietly change what Gemini is told the tools are.
    """

    def declarations(self):
        run = RunState(progress=None)
        return {
            function.__name__: types.FunctionDeclaration.from_callable(
                client=gemini_client, callable=function)
            for function in tools.make_tools(run)
        }

    def test_both_tools_are_declared_under_their_own_names(self):
        self.assertEqual(sorted(self.declarations()),
                         ["extract_company_page", "search_web"])

    def test_search_web_takes_one_required_string_query(self):
        parameters = self.declarations()["search_web"].parameters
        self.assertEqual(parameters.type, types.Type.OBJECT)
        self.assertEqual(list(parameters.properties), ["query"])
        self.assertEqual(parameters.properties["query"].type, types.Type.STRING)
        self.assertEqual(parameters.required, ["query"])

    def test_extract_company_page_takes_one_required_string_url(self):
        parameters = self.declarations()["extract_company_page"].parameters
        self.assertEqual(parameters.type, types.Type.OBJECT)
        self.assertEqual(list(parameters.properties), ["url"])
        self.assertEqual(parameters.properties["url"].type, types.Type.STRING)
        self.assertEqual(parameters.required, ["url"])

    def test_the_descriptions_are_the_docstrings_the_model_relies_on(self):
        """These sentences are instructions to the model. Losing them would
        not fail anything else, and the agent would get quietly worse."""
        declarations = self.declarations()

        search = declarations["search_web"].description
        self.assertIn("Search the web for current, real information", search)
        self.assertIn("more than once with", search)

        extract = declarations["extract_company_page"].description
        self.assertIn("Read the actual content of one specific page", extract)

    def test_two_runs_declare_identical_schemas(self):
        """Per-run tools must not mean per-run prompts."""
        first, second = self.declarations(), self.declarations()
        for name in first:
            with self.subTest(tool=name):
                self.assertEqual(first[name].parameters,
                                 second[name].parameters)
                self.assertEqual(first[name].description,
                                 second[name].description)


class LedgerRule(unittest.TestCase):
    """A failed fetch still records nothing, now per run."""

    def test_a_failed_fetch_is_not_recorded(self):
        run = RunState(progress=None)
        self.assertFalse(tools._record(
            run, RetrievedDoc(url="https://nope.example", provider="tavily",
                              error="timeout")))
        self.assertEqual(run.sources_consulted(), [])

    def test_a_successful_fetch_is_recorded(self):
        run = RunState(progress=None)
        self.assertTrue(tools._record(
            run, RetrievedDoc(url="https://yes.example", provider="tavily",
                              content="text")))
        self.assertEqual(run.sources_consulted(), ["https://yes.example"])


if __name__ == "__main__":
    unittest.main()
