"""Exercise the real MCP SDK, resolver, tool callbacks and source ledger.

HTTP is deterministic here; the model caller test is scripted, not live Gemini.
Run with: python -m unittest discover -s tests -v

Only the HTTP transport is mocked. The handshake, tool discovery, dispatch and
result parsing run through the installed mcp SDK, which is what makes these
tests fail when the SDK's transport changes shape: 2.x yields two streams where
1.x yielded three and expects an httpx2 client rather than an httpx one, and
neither difference is visible until the real client runs.
"""

import json
import os
import subprocess
import sys
import unittest
from importlib.metadata import version
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import anyio
import httpx2

os.environ.setdefault("GEMINI_API_KEY", "test-gemini-key")

import config
import parallel_mcp
import pipeline
import retrieval
import tools
from retrieval import ParallelProvider, ResponseCache, get_provider

URL = "https://acme.example/about"
DOCUMENT = {"url": URL, "title": "Acme", "excerpts": ["We build widgets."]}


class MCPFixture:
    """Mock only HTTP; keep SDK handshake, discovery and dispatch real."""

    def __init__(self, response=None, error=False, text_only=False, hang=False,
                 http_status=200, missing_tool=False):
        self.response = response if response is not None else {"results": [DOCUMENT]}
        self.error = error
        self.text_only = text_only
        self.hang = hang
        self.http_status = http_status
        self.missing_tool = missing_tool
        self.requests = []
        self.clients = []
        self.client_class = httpx2.AsyncClient

    def client(self, **kwargs):
        client = self.client_class(transport=httpx2.MockTransport(self.handle), **kwargs)
        self.clients.append(client)
        return client

    async def handle(self, request):
        body = json.loads(request.content) if request.content else {}
        self.requests.append((request, body))
        if "id" not in body:
            return httpx2.Response(202)
        method = body["method"]
        if method == "initialize":
            result = {"protocolVersion": "2025-03-26", "capabilities": {"tools": {}},
                      "serverInfo": {"name": "fixture", "version": "1"}}
        elif method == "tools/list":
            result = {"tools": [] if self.missing_tool else [
                {"name": name, "inputSchema": {"type": "object"}}
                for name in ("web_search", "web_fetch")]}
        elif method == "tools/call":
            if self.hang:
                await anyio.sleep_forever()
            if self.http_status != 200:
                return httpx2.Response(self.http_status, text="unavailable")
            text = "Quota exhausted" if self.error else json.dumps(self.response)
            result = {"isError": self.error, "content": [{"type": "text", "text": text}]}
            if not self.error and not self.text_only:
                result["structuredContent"] = self.response
        else:
            raise AssertionError(method)
        return httpx2.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "result": result})


class ParallelRuntime(unittest.TestCase):
    def setUp(self):
        # Parallel is reached only by asking for it: no credential's absence
        # selects it, so the env this runs under has to say so explicitly.
        self.env = patch.dict(
            os.environ,
            {"GEMINI_API_KEY": "test", "RETRIEVAL_PROVIDER": "parallel"},
            clear=True,
        )
        self.env.start()
        tools.set_provider(None)
        tools.reset_sources()

    def tearDown(self):
        tools.set_provider(None)
        tools.reset_sources()
        self.env.stop()

    def configure(self, fixture, timeout=45):
        self.addCleanup(patch.stopall)
        patch("parallel_mcp.httpx2.AsyncClient", side_effect=fixture.client).start()
        # Normal resolver selection, not a directly injected provider.
        provider = tools.active_provider()
        self.assertIsInstance(provider, ParallelProvider)
        provider.cache = ResponseCache(enabled=False)
        provider.client.timeout = timeout
        # The pacing delay exists for a network these tests never reach.
        provider.throttle = False
        return provider

    def test_search_and_fetch_reach_consumer_with_project_headers(self):
        fixture = MCPFixture(response={"results": [{**DOCUMENT, "full_content": "Full company page."}]})
        provider = self.configure(fixture)
        rendered = tools.search_web("acme widget competitors")
        self.assertEqual(rendered, f"Title: Acme\nURL: {URL}\nContent: We build widgets.\n\n")
        self.assertEqual(tools.extract_company_page(URL), "Full company page.")
        self.assertEqual(tools.sources_consulted(), [URL])
        calls = [body["params"] for _, body in fixture.requests if body.get("method") == "tools/call"]
        self.assertEqual(calls[0]["arguments"]["search_queries"], ["acme widget competitors"])
        self.assertEqual(calls[1]["arguments"]["urls"], [URL])
        self.assertTrue(calls[1]["arguments"]["full_content"])
        self.assertEqual({c["arguments"]["session_id"] for c in calls}, {provider.client.session_id})
        self.assertEqual(provider.meter.calls, {"parallel.search": 1, "parallel.fetch": 1})
        for request, _ in fixture.requests:
            self.assertEqual(str(request.url), parallel_mcp.MCP_URL)
            self.assertEqual(request.headers["user-agent"], parallel_mcp.USER_AGENT)
            self.assertNotIn("authorization", request.headers)
        self.assertTrue(all(client.is_closed for client in fixture.clients))

    def test_scripted_gemini_chat_consumes_registered_tools(self):
        fixture = MCPFixture()
        self.configure(fixture)
        consumed = []

        def create(**kwargs):
            callbacks = {f.__name__: f for f in kwargs["config"].tools}
            self.assertEqual(set(callbacks), {"search_web", "extract_company_page"})

            def send_message(prompt):
                consumed.append(callbacks["search_web"]("acme competitors"))
                consumed.append(callbacks["extract_company_page"](URL))
                return SimpleNamespace(parsed="scripted research result")
            return SimpleNamespace(send_message=send_message)

        fake_gemini = SimpleNamespace(chats=SimpleNamespace(create=create))
        with patch.object(pipeline, "gemini_client", fake_gemini):
            identity = SimpleNamespace(description="Widget manufacturer", location="London")
            result = pipeline.research_competitors("Acme", identity)
        self.assertEqual(result, "scripted research result")
        self.assertIn(URL, consumed[0])
        self.assertEqual(consumed[1], "We build widgets.")
        self.assertEqual(tools.sources_consulted(), [URL])

    def test_empty_and_unmatched_fetches_never_enter_ledger(self):
        fixture = MCPFixture(response={"results": [], "errors": [{"url": URL, "error_type": "unavailable"}]})
        self.configure(fixture)
        self.assertIn("Could not read", tools.extract_company_page(URL))
        # Several documents, none of them the page asked for: no lone result to
        # fall back on, so nothing is attributed to the request.
        fixture.response = {"results": [{**DOCUMENT, "url": "https://other.example"},
                                        {**DOCUMENT, "url": "https://third.example"}]}
        self.assertIn("Could not read", tools.extract_company_page(URL))
        fixture.response = {"results": [{**DOCUMENT, "excerpts": []}]}
        self.assertEqual(tools.search_web("q"), "")
        self.assertEqual(tools.sources_consulted(), [])

    def test_a_redirected_page_is_read_and_ledgered_under_the_requested_url(self):
        """web_fetch answers under the destination URL, which is still the page.

        Requiring string equality with the requested URL turned every redirect
        into "no extractable content" and left the ledger empty for a page that
        had in fact been fetched.
        """
        fixture = MCPFixture()
        self.configure(fixture)
        for destination in ("https://acme.example/about/",
                            "http://www.acme.example/about",
                            "https://acme.example/company/about"):
            with self.subTest(destination=destination):
                tools.reset_sources()
                fixture.response = {"results": [
                    {**DOCUMENT, "url": destination, "full_content": "Full company page."}]}
                self.assertEqual(tools.extract_company_page(URL), "Full company page.")
                self.assertEqual(tools.sources_consulted(), [URL])

    def test_fetch_prefers_a_matching_document_over_position(self):
        """With several documents, the one answering the request wins.

        Position only decides when a single document came back, so a batch that
        happens to include the requested page must not be read off the top.
        """
        wanted = SimpleNamespace(url=URL, title="Acme", excerpts=["right"], full_content=None)
        other = SimpleNamespace(url="https://other.example", title="", excerpts=["wrong"],
                                full_content=None)
        variant = SimpleNamespace(url="https://WWW.Acme.example/about/", title="",
                                  excerpts=["near"], full_content=None)
        answer = ParallelProvider._answer_for
        self.assertIs(answer(URL, [other, wanted]), wanted)
        self.assertIs(answer(URL, [other, variant]), variant)
        self.assertIs(answer(URL, [variant, wanted]), wanted)
        self.assertIsNone(answer(URL, [other, other]))
        self.assertIsNone(answer(URL, []))
        # A query string is content, not decoration, so it still has to match.
        self.assertIsNone(answer("https://acme.example/about?lang=en", [other, variant]))

    def test_invalid_urls_and_malformed_results_fail_without_sources(self):
        fixture = MCPFixture(response={"results": [{**DOCUMENT, "url": "javascript:alert(1)"}]})
        self.configure(fixture)
        with self.assertRaises(Exception):
            tools.search_web("q")
        self.assertEqual(tools.sources_consulted(), [])
        count = len(fixture.requests)
        with self.assertRaises(ValueError):
            tools.extract_company_page("file:///etc/passwd")
        self.assertEqual(len(fixture.requests), count)
        fixture.response = {"results": [{"url": URL, "excerpts": "wrong shape"}]}
        with self.assertRaises(Exception):
            tools.search_web("q")
        self.assertEqual(tools.sources_consulted(), [])

    def test_json_text_response_supported(self):
        fixture = MCPFixture(text_only=True)
        self.configure(fixture)
        self.assertIn("We build widgets.", tools.search_web("q"))

    def test_errors_do_not_fallback_or_record_sources(self):
        fixture = MCPFixture(error=True)
        self.configure(fixture)
        for action in (lambda: tools.search_web("q"), lambda: tools.extract_company_page(URL)):
            with self.assertRaises(Exception) as error:
                action()
            self.assertIn("Quota exhausted", str(error.exception))
        self.assertEqual(tools.sources_consulted(), [])
        self.assertTrue(all(client.is_closed for client in fixture.clients))

    def test_http_error_and_missing_tool_do_not_record_sources(self):
        fixture = MCPFixture(http_status=403)
        self.configure(fixture)
        with self.assertRaises(Exception):
            tools.search_web("q")
        fixture.missing_tool = True
        with self.assertRaises(Exception):
            tools.extract_company_page(URL)
        self.assertEqual(tools.sources_consulted(), [])

    def test_timeout_closes_transport_and_does_not_record_sources(self):
        fixture = MCPFixture(hang=True)
        self.configure(fixture, timeout=0.05)
        with self.assertRaises(TimeoutError):
            tools.search_web("q")
        self.assertTrue(all(client.is_closed for client in fixture.clients))
        self.assertEqual(tools.sources_consulted(), [])

    def test_cancellation_closes_transport(self):
        fixture = MCPFixture(hang=True)
        provider = self.configure(fixture)

        async def cancel():
            with anyio.move_on_after(0.05) as scope:
                await provider.client._call("web_search", {"objective": "q", "search_queries": ["q"]})
            self.assertTrue(scope.cancel_called)
        anyio.run(cancel)
        self.assertTrue(all(client.is_closed for client in fixture.clients))
        self.assertEqual(tools.sources_consulted(), [])

    def test_parallel_is_reached_only_by_asking_for_it(self):
        """A missing Tavily key must not hand the run to a different backend.

        Choosing by which credentials happen to be set is the same silent
        substitution the warned typo fallback exists to prevent, minus the
        warning: the deployed default stays tavily whether or not a key is
        configured, and only RETRIEVAL_PROVIDER moves it.
        """
        names = ("parallel", "tavily", "firecrawl", "firecrawl_scrape", "hybrid")
        with patch("retrieval._PROVIDERS",
                   {name: lambda n=name, **kw: SimpleNamespace(name=n) for name in names}):
            os.environ.pop("RETRIEVAL_PROVIDER", None)
            self.assertNotIn("TAVILY_API_KEY", os.environ)
            self.assertEqual(get_provider().name, "tavily")
            os.environ["TAVILY_API_KEY"] = "configured-key"
            self.assertEqual(get_provider().name, "tavily")
            for name in names:
                os.environ["RETRIEVAL_PROVIDER"] = name
                self.assertEqual(get_provider().name, name)
                self.assertEqual(get_provider("parallel").name, "parallel")
            os.environ["RETRIEVAL_PROVIDER"] = "misspelt"
            with patch("builtins.print") as printed:
                self.assertEqual(get_provider().name, "tavily")
            warning = " ".join(str(call.args[0]) for call in printed.call_args_list)
            self.assertIn("misspelt", warning)
            self.assertIn("parallel", warning)

    def test_fresh_process_runs_parallel_with_no_search_credentials(self):
        """RETRIEVAL_PROVIDER=parallel is enough; no search key is needed.

        config.py builds its Tavily client at import time, so a missing
        TAVILY_API_KEY has to leave that client unset rather than raise.
        """
        result = subprocess.run([sys.executable, "-c",
            "import tools; assert tools.active_provider().name == 'parallel'"],
            env={"PATH": os.environ.get("PATH", ""), "GEMINI_API_KEY": "test",
                 "RETRIEVAL_PROVIDER": "parallel", "PYTHON_DOTENV_DISABLED": "1"},
            capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_requirements_pin_the_mcp_release_these_tests_ran_against(self):
        """The pin and the tested SDK have to be the same thing.

        Only the HTTP transport is mocked above, so the tests in this file are
        the verification that parallel_mcp.py works on the installed SDK. That
        evidence is worth nothing if requirements.txt admits another major: the
        1.x transport yields three values instead of two and wants an httpx
        client instead of an httpx2 one, and both break at runtime rather than
        at install time.
        """
        installed = version("mcp")
        requirements = (Path(__file__).resolve().parents[1] / "requirements.txt").read_text()
        self.assertEqual(installed.split(".")[0], "2", installed)
        self.assertIn(f"mcp=={installed}", requirements)
        self.assertIs(parallel_mcp.httpx2, httpx2)

    def test_live_calls_are_paced_like_the_other_providers(self):
        """Parallel publishes no anonymous rate limit, so pick one and keep it.

        Nothing here measures a documented cap; it checks that the backend
        paces itself at all, through the same _wait_turn and _MIN_INTERVAL_S
        that Tavily and Firecrawl use, at an interval no shorter than theirs.
        """
        self.assertGreaterEqual(retrieval._MIN_INTERVAL_S["parallel"],
                                retrieval._MIN_INTERVAL_S["tavily"])
        fixture = MCPFixture()
        provider = self.configure(fixture)
        provider.throttle = True
        slept = []
        with patch.dict(retrieval._last_call_at, {}, clear=True), \
                patch("retrieval.time.sleep", slept.append):
            provider.search("q")
            provider.fetch(URL)
        # The first call has no predecessor to wait behind; the second does.
        self.assertEqual(len(slept), 1)
        self.assertAlmostEqual(slept[0], retrieval._MIN_INTERVAL_S["parallel"], places=1)

    def test_a_dropped_connection_is_retried_rather_than_surfaced(self):
        """A retry decorator is only real if it recognises this transport.

        The MCP SDK brings its own HTTP client, so a Parallel connection drop
        arrives as httpx2.TransportError while is_retryable_error had only ever
        been taught about httpx.
        """
        self.assertTrue(config.is_retryable_error(httpx2.ConnectError("reset")))
        attempts = []

        def flaky(tool, arguments):
            attempts.append(tool)
            if len(attempts) < 3:
                raise httpx2.ConnectError("connection reset")
            return [parallel_mcp.MCPDocument(
                url=URL, title="Acme", excerpts=["We build widgets."],
                full_content="Full company page.")]

        provider = ParallelProvider(client=SimpleNamespace(call=flaky),
                                    cache=ResponseCache(enabled=False), throttle=False)
        with patch("config._wait_standard", lambda retry_state: 0):
            self.assertEqual(provider.fetch(URL).content, "Full company page.")
            self.assertEqual(len(attempts), 3)
            attempts.clear()
            self.assertEqual(provider.search("q")[0].content, "We build widgets.")
        self.assertEqual(len(attempts), 3)

    def test_a_service_error_is_not_retried(self):
        """Only transport failures get another attempt.

        A quota or tool error repeats identically, so retrying it just delays
        the message the caller needs to see.
        """
        attempts = []

        def refusing(tool, arguments):
            attempts.append(tool)
            raise RuntimeError("Parallel MCP web_search failed: Quota exhausted")

        provider = ParallelProvider(client=SimpleNamespace(call=refusing),
                                    cache=ResponseCache(enabled=False), throttle=False)
        with self.assertRaisesRegex(RuntimeError, "Quota exhausted"):
            provider.search("q")
        self.assertEqual(len(attempts), 1)


if __name__ == "__main__":
    unittest.main()
