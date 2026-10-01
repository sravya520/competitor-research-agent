"""Tests for the pluggable retrieval layer.

Run: python -m unittest discover -s tests -v

Two things these tests exist to protect:

1. Switching providers must not change what the model sees in tavily mode.
   The expected strings below are written out literally, copied from the
   pre-refactor implementation, so a formatting drift fails loudly instead of
   quietly changing agent behaviour.

2. A failed fetch must never reach the source ledger. evaluate.py treats the
   ledger as proof a URL was really retrieved; a provider that recorded
   failures would turn the fabrication check into a rubber stamp.
"""

import os
import unittest
from unittest.mock import MagicMock

# config.py reads API keys from os.environ at import time, and importing
# retrieval/tools pulls it in. Dummies keep the tests hermetic — no real keys,
# no network.
os.environ.setdefault("GEMINI_API_KEY", "test-gemini-key")
os.environ.setdefault("TAVILY_API_KEY", "test-tavily-key")
os.environ.setdefault("FIRECRAWL_API_KEY", "test-firecrawl-key")

import tools  # noqa: E402
from retrieval import (  # noqa: E402
    CreditMeter,
    FirecrawlProvider,
    HybridProvider,
    ResponseCache,
    RetrievedDoc,
    TavilyProvider,
    get_provider,
)

NO_CACHE = lambda: ResponseCache(enabled=False)  # noqa: E731


def tavily_search_payload(results):
    return {"results": results}


def make_tavily(search_results=None, extract_results=None):
    client = MagicMock()
    client.search.return_value = tavily_search_payload(search_results or [])
    client.extract.return_value = {"results": extract_results or []}
    return client


def make_firecrawl(web=None, markdown="content", raises=None):
    client = MagicMock()
    client.search.return_value = {"web": web or []}
    if raises is not None:
        client.scrape.side_effect = raises
    else:
        client.scrape.return_value = {
            "markdown": markdown,
            "metadata": {"title": "Scraped Title"},
        }
    return client


class TavilyOutputUnchanged(unittest.TestCase):
    """The format the model sees must be identical to the pre-refactor code."""

    def setUp(self):
        tools.reset_sources()

    def tearDown(self):
        tools.set_provider(None)
        tools.reset_sources()

    def test_search_output_is_byte_identical(self):
        client = make_tavily(search_results=[
            {"title": "Acme", "url": "https://acme.com", "content": "We make things."},
            {"title": "Beta", "url": "https://beta.io/about", "content": "Beta does X."},
        ])
        tools.set_provider(TavilyProvider(client=client, cache=NO_CACHE(), throttle=False))

        expected = (
            "Title: Acme\n"
            "URL: https://acme.com\n"
            "Content: We make things.\n"
            "\n"
            "Title: Beta\n"
            "URL: https://beta.io/about\n"
            "Content: Beta does X.\n"
            "\n"
        )
        self.assertEqual(tools.search_web("acme"), expected)

    def test_listicle_tag_still_applied(self):
        client = make_tavily(search_results=[
            {"title": "Top 10 CRMs", "url": "https://x.com/blog/best-crms",
             "content": "A roundup."},
        ])
        tools.set_provider(TavilyProvider(client=client, cache=NO_CACHE(), throttle=False))

        out = tools.search_web("crm")
        self.assertIn("Title: Top 10 CRMs [ROUNDUP/LISTICLE CONTENT", out)
        self.assertIn("do not treat its stats or claims as verified facts", out)

    def test_extract_returns_raw_content(self):
        client = make_tavily(extract_results=[{"raw_content": "Full page text."}])
        tools.set_provider(TavilyProvider(client=client, cache=NO_CACHE(), throttle=False))

        self.assertEqual(
            tools.extract_company_page("https://acme.com"), "Full page text."
        )

    def test_extract_failure_message_unchanged(self):
        client = make_tavily(extract_results=[])
        tools.set_provider(TavilyProvider(client=client, cache=NO_CACHE(), throttle=False))

        self.assertEqual(
            tools.extract_company_page("https://acme.com"),
            "Could not read the page at https://acme.com. "
            "It may be blocked, private, or unavailable.",
        )


class LedgerInvariant(unittest.TestCase):
    """A failed fetch records nothing. Tested per provider, as required."""

    def setUp(self):
        tools.reset_sources()

    def tearDown(self):
        tools.set_provider(None)
        tools.reset_sources()

    # ---- failed fetch records nothing -------------------------------------

    def test_tavily_failed_fetch_records_nothing(self):
        tools.set_provider(TavilyProvider(
            client=make_tavily(extract_results=[]), cache=NO_CACHE(), throttle=False))

        tools.extract_company_page("https://unreachable.example")
        self.assertEqual(tools.sources_consulted(), [])

    def test_firecrawl_failed_fetch_records_nothing(self):
        tools.set_provider(FirecrawlProvider(
            client=make_firecrawl(raises=RuntimeError("502 upstream")),
            cache=NO_CACHE(), throttle=False))

        tools.extract_company_page("https://unreachable.example")
        self.assertEqual(tools.sources_consulted(), [])

    def test_firecrawl_empty_content_records_nothing(self):
        """Empty markdown is a failure, not an empty-but-valid page."""
        tools.set_provider(FirecrawlProvider(
            client=make_firecrawl(markdown=""), cache=NO_CACHE(), throttle=False))

        tools.extract_company_page("https://blank.example")
        self.assertEqual(tools.sources_consulted(), [])

    def test_hybrid_failed_fetch_records_nothing(self):
        hybrid = HybridProvider(
            tavily=TavilyProvider(client=make_tavily(), cache=NO_CACHE(), throttle=False),
            firecrawl=FirecrawlProvider(
                client=make_firecrawl(raises=TimeoutError("timed out")),
                cache=NO_CACHE(), throttle=False),
        )
        tools.set_provider(hybrid)

        tools.extract_company_page("https://unreachable.example")
        self.assertEqual(tools.sources_consulted(), [])

    # ---- partial batch records only successes -----------------------------

    def test_tavily_partial_batch_records_only_successes(self):
        client = make_tavily(search_results=[
            {"title": "Good", "url": "https://good.com", "content": "real"},
            {"title": "Bad", "url": "https://bad.com", "content": ""},
            {"title": "Also good", "url": "https://also-good.com", "content": "real"},
        ])
        tools.set_provider(TavilyProvider(client=client, cache=NO_CACHE(), throttle=False))

        out = tools.search_web("q")
        self.assertEqual(
            tools.sources_consulted(), ["https://also-good.com", "https://good.com"])
        # The unusable result is not shown to the model either, or it would be
        # a URL in context that is absent from the ledger.
        self.assertNotIn("https://bad.com", out)

    def test_firecrawl_partial_batch_records_only_successes(self):
        client = make_firecrawl(web=[
            {"url": "https://good.com", "title": "Good", "description": "snippet"},
            {"url": "https://empty.com", "title": "Empty", "description": ""},
        ])
        tools.set_provider(FirecrawlProvider(client=client, cache=NO_CACHE(), throttle=False))

        out = tools.search_web("q")
        self.assertEqual(tools.sources_consulted(), ["https://good.com"])
        self.assertNotIn("https://empty.com", out)

    def test_hybrid_partial_batch_records_only_successes(self):
        hybrid = HybridProvider(
            tavily=TavilyProvider(client=make_tavily(search_results=[
                {"title": "Good", "url": "https://good.com", "content": "real"},
                {"title": "Bad", "url": "https://bad.com", "content": ""},
            ]), cache=NO_CACHE(), throttle=False),
            firecrawl=FirecrawlProvider(client=make_firecrawl(), cache=NO_CACHE(), throttle=False),
        )
        tools.set_provider(hybrid)

        tools.search_web("q")
        self.assertEqual(tools.sources_consulted(), ["https://good.com"])


class DocInvariant(unittest.TestCase):
    def test_error_doc_is_not_ok(self):
        doc = RetrievedDoc(url="https://x.com", provider="tavily", error="boom")
        self.assertFalse(doc.ok)

    def test_empty_content_is_not_ok(self):
        doc = RetrievedDoc(url="https://x.com", provider="tavily", content="")
        self.assertFalse(doc.ok)

    def test_good_doc_is_ok(self):
        doc = RetrievedDoc(url="https://x.com", provider="tavily", content="text")
        self.assertTrue(doc.ok)


class HybridRouting(unittest.TestCase):
    def test_search_goes_to_tavily_fetch_goes_to_firecrawl(self):
        tav = TavilyProvider(client=make_tavily(search_results=[
            {"title": "T", "url": "https://t.com", "content": "c"}]), cache=NO_CACHE(), throttle=False)
        fire = FirecrawlProvider(client=make_firecrawl(markdown="fc content"),
                                 cache=NO_CACHE(), throttle=False)
        hybrid = HybridProvider(tavily=tav, firecrawl=fire)

        self.assertEqual(hybrid.search("q")[0].provider, "tavily")
        self.assertEqual(hybrid.fetch("https://x.com").provider, "firecrawl")


class CreditAccounting(unittest.TestCase):
    def test_tavily_batched_is_cheaper_than_as_implemented(self):
        """Tavily bills extract per 5 URLs; we send one per call."""
        meter = CreditMeter()
        for i in range(5):
            meter.record("tavily", "fetch", 1.0, urls=1)

        self.assertEqual(meter.as_implemented, 5.0)
        self.assertEqual(meter.theoretical_batched, 1.0)

    def test_firecrawl_batched_equals_as_implemented(self):
        """Firecrawl scrape bills per page regardless of batching."""
        meter = CreditMeter()
        for _ in range(5):
            meter.record("firecrawl", "fetch", 1.0)

        self.assertEqual(meter.as_implemented, 5.0)
        self.assertEqual(meter.theoretical_batched, 5.0)

    def test_firecrawl_search_costs_two_credits(self):
        client = make_firecrawl(web=[])
        provider = FirecrawlProvider(client=client, cache=NO_CACHE(), throttle=False)
        provider.search("q", max_results=5)
        self.assertEqual(provider.meter.as_implemented, 2.0)

    def test_tavily_search_costs_one_credit(self):
        provider = TavilyProvider(client=make_tavily(), cache=NO_CACHE(), throttle=False)
        provider.search("q", max_results=5)
        self.assertEqual(provider.meter.as_implemented, 1.0)


class ProviderSelection(unittest.TestCase):
    def tearDown(self):
        os.environ.pop("RETRIEVAL_PROVIDER", None)

    def test_defaults_to_tavily(self):
        os.environ.pop("RETRIEVAL_PROVIDER", None)
        self.assertEqual(get_provider(cache=NO_CACHE(), throttle=False).name, "tavily")

    def test_unknown_value_falls_back_to_tavily(self):
        os.environ["RETRIEVAL_PROVIDER"] = "nonsense"
        self.assertEqual(get_provider(cache=NO_CACHE(), throttle=False).name, "tavily")

    def test_explicit_name_wins(self):
        self.assertEqual(
            get_provider("firecrawl", cache=NO_CACHE(), throttle=False).name, "firecrawl")


if __name__ == "__main__":
    unittest.main(verbosity=2)
