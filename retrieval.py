"""Pluggable retrieval backends: Tavily, Firecrawl, or a hybrid of both.

The pipeline never imports this module directly. `tools.py` owns the two
functions the agent actually calls, and asks a provider from here to do the
fetching. That keeps three things in one place regardless of provider:

    - the exact string format the model sees
    - the [ROUNDUP/LISTICLE CONTENT] tag
    - the source ledger that the fabrication check depends on

THE INVARIANT THAT MATTERS: a failed fetch sets `error` and returns empty
content. Nothing downstream may record a URL that was not successfully
retrieved. `evaluate.check_sources_are_real` treats "in the ledger" as proof a
URL was really fetched, so a provider that recorded failures would silently
turn the strongest guarantee in this project into a rubber stamp.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel, Field
from tenacity import retry

from config import RETRY_SETTINGS

# Firecrawl free tier allows 10 requests/minute on scrape/search. 6.5s between
# live calls keeps us under it with margin. Tavily publishes no free-tier RPM,
# so it gets a smaller self-imposed delay purely to be a good citizen.
_MIN_INTERVAL_S = {"firecrawl": 6.5, "tavily": 1.0}

DEFAULT_TIMEOUT_S = 45

CACHE_DIR = Path("benchmarks/cache")


class RetrievedDoc(BaseModel):
    """One fetched document, or one failure, from any provider."""

    url: str
    title: str = ""
    content: str = ""
    provider: str
    fetched_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    latency_ms: int = 0
    error: str | None = None

    @property
    def ok(self) -> bool:
        """True only when this is a usable document.

        Checked rather than assumed everywhere a doc reaches the ledger.
        """
        return self.error is None and bool(self.content)


class RetrievalProvider(Protocol):
    name: str

    def search(self, query: str, max_results: int = 5) -> list[RetrievedDoc]: ...
    def fetch(self, url: str) -> RetrievedDoc: ...


# --------------------------------------------------------------------------
# Credit accounting
# --------------------------------------------------------------------------


class CreditMeter:
    """Counts credits using each provider's documented billing rule.

    Reported two ways, because they differ and the difference favours Tavily:

      as_implemented  - what this codebase actually spends, fetching one URL
                        per call.
      theoretical_batched
                      - what Tavily WOULD spend if page fetches were batched,
                        since basic extract bills per 5 URLs rather than per
                        URL. We do not implement batching; this is computed so
                        the writeup cannot overstate Firecrawl's cost position.

    For Firecrawl the two are identical: scrape bills per page either way.
    """

    def __init__(self) -> None:
        self.as_implemented: float = 0.0
        self.calls: dict[str, int] = {}
        # Credits per provider, kept alongside the call counts. Without it,
        # anything needing a single provider's spend has to re-derive it from
        # call counts and a second copy of the pricing rules, which is how the
        # credit cross-check came to score firecrawl_scrape as 0 credits: its
        # provider name is not literally "firecrawl".
        self.credits_by_provider: dict[str, float] = {}
        self._tavily_urls_fetched = 0

    def record(self, provider: str, operation: str, credits: float, urls: int = 0) -> None:
        self.as_implemented += credits
        key = f"{provider}.{operation}"
        self.calls[key] = self.calls.get(key, 0) + 1
        self.credits_by_provider[provider] = (
            self.credits_by_provider.get(provider, 0.0) + credits)
        if provider == "tavily" and operation == "fetch":
            self._tavily_urls_fetched += urls

    @property
    def theoretical_batched(self) -> float:
        """Tavily basic extract bills 1 credit per 5 URLs. Fetching one at a
        time wastes 4/5 of each credit. This is what batching would have cost.
        """
        unbatched = float(self._tavily_urls_fetched)
        batched = math.ceil(self._tavily_urls_fetched / 5) if self._tavily_urls_fetched else 0
        return self.as_implemented - unbatched + batched

    def snapshot(self) -> dict:
        return {
            "as_implemented": round(self.as_implemented, 2),
            "theoretical_tavily_batched": round(self.theoretical_batched, 2),
            "calls": dict(self.calls),
        }


# --------------------------------------------------------------------------
# Disk cache
# --------------------------------------------------------------------------


class ResponseCache:
    """Caches raw provider responses so a rerun costs zero credits.

    Benchmarks run with use_cache=False for the measured passes: a cached read
    would report a fake latency and hide run-to-run variance. The cache exists
    so metrics can be recomputed afterwards, and so development iteration does
    not burn the free tier.
    """

    def __init__(self, directory: Path = CACHE_DIR, enabled: bool = True) -> None:
        self.dir = directory
        self.enabled = enabled
        self.hits = 0
        self.misses = 0
        if enabled:
            self.dir.mkdir(parents=True, exist_ok=True)

    def _path(self, provider: str, operation: str, payload: str) -> Path:
        digest = hashlib.sha256(f"{provider}:{operation}:{payload}".encode()).hexdigest()[:40]
        return self.dir / f"{provider}_{operation}_{digest}.json"

    def get(self, provider: str, operation: str, payload: str) -> list[dict] | None:
        if not self.enabled:
            return None
        path = self._path(provider, operation, payload)
        if not path.exists():
            self.misses += 1
            return None
        self.hits += 1
        return json.loads(path.read_text(encoding="utf-8"))["docs"]

    def put(self, provider: str, operation: str, payload: str, docs: list[RetrievedDoc]) -> None:
        if not self.enabled:
            return
        path = self._path(provider, operation, payload)
        path.write_text(
            json.dumps(
                {
                    "provider": provider,
                    "operation": operation,
                    "payload": payload,
                    "cached_at": datetime.now(timezone.utc).isoformat(),
                    "docs": [d.model_dump(mode="json") for d in docs],
                },
                indent=2,
            ),
            encoding="utf-8",
        )


_last_call_at: dict[str, float] = {}


def _throttle(provider: str) -> None:
    """Keep live calls under the provider's documented rate limit."""
    interval = _MIN_INTERVAL_S.get(provider, 1.0)
    last = _last_call_at.get(provider)
    if last is not None:
        wait = interval - (time.monotonic() - last)
        if wait > 0:
            time.sleep(wait)
    _last_call_at[provider] = time.monotonic()


# --------------------------------------------------------------------------
# Providers
# --------------------------------------------------------------------------


class _BaseProvider:
    def __init__(self, meter: CreditMeter | None = None,
                 cache: ResponseCache | None = None,
                 throttle: bool = True):
        self.meter = meter or CreditMeter()
        self.cache = cache if cache is not None else ResponseCache()
        # Tests drive mocked clients and must not sleep through a rate limit
        # that exists for a network they never touch.
        self.throttle = throttle

    def _wait_turn(self) -> None:
        if self.throttle:
            _throttle(self.name)

    def _cached(self, operation: str, payload: str) -> list[RetrievedDoc] | None:
        raw = self.cache.get(self.name, operation, payload)
        if raw is None:
            return None
        return [RetrievedDoc(**d) for d in raw]


class TavilyProvider(_BaseProvider):
    """Today's behaviour, unchanged. search -> snippets, fetch -> full page."""

    name = "tavily"

    def __init__(self, client=None, extract_depth: str = "basic", **kw):
        super().__init__(**kw)
        if client is None:
            from config import tavily_client
            client = tavily_client
        self.client = client
        # "basic" is Tavily's default and what production has always used, so it
        # stays the default here. "advanced" exists because comparing Firecrawl's
        # full scrape against Tavily's cheaper tier would flatter Firecrawl; the
        # benchmark runs it as a separate arm rather than quietly handicapping
        # one side. advanced costs 2 credits per 5 URLs instead of 1.
        self.extract_depth = extract_depth

    @retry(**RETRY_SETTINGS)
    def search(self, query: str, max_results: int = 5) -> list[RetrievedDoc]:
        cached = self._cached("search", f"{query}|{max_results}")
        if cached is not None:
            return cached

        self._wait_turn()
        started = time.monotonic()
        response = self.client.search(query, max_results=max_results)
        latency = int((time.monotonic() - started) * 1000)

        # Basic search: 1 credit per request regardless of result count.
        self.meter.record(self.name, "search", 1.0)

        docs = [
            RetrievedDoc(
                url=r["url"],
                title=r.get("title", ""),
                content=r.get("content", ""),
                provider=self.name,
                latency_ms=latency,
            )
            for r in response.get("results", [])
        ]
        self.cache.put(self.name, "search", f"{query}|{max_results}", docs)
        return docs

    @retry(**RETRY_SETTINGS)
    def fetch(self, url: str) -> RetrievedDoc:
        # The cache key only gains a suffix for non-default depths, so existing
        # cached basic responses stay valid and the two depths cannot collide.
        payload = url if self.extract_depth == "basic" else f"{url}|{self.extract_depth}"
        cached = self._cached("fetch", payload)
        if cached is not None:
            return cached[0]

        self._wait_turn()
        started = time.monotonic()
        extra = {} if self.extract_depth == "basic" else {"extract_depth": self.extract_depth}
        response = self.client.extract(url, **extra)
        latency = int((time.monotonic() - started) * 1000)

        # Basic extract bills per 5 successful URLs; we send one per call.
        # Advanced bills double that.
        self.meter.record(
            self.name, "fetch", 1.0 if self.extract_depth == "basic" else 2.0, urls=1)

        results = response.get("results") or []
        if not results:
            doc = RetrievedDoc(
                url=url, provider=self.name, latency_ms=latency,
                error="Tavily returned no extractable content",
            )
        else:
            doc = RetrievedDoc(
                url=url,
                title=results[0].get("title", ""),
                content=results[0].get("raw_content", "") or "",
                provider=self.name,
                latency_ms=latency,
            )
            if not doc.content:
                doc.error = "Tavily returned empty content"

        self.cache.put(self.name, "fetch", payload, [doc])
        return doc


class FirecrawlProvider(_BaseProvider):
    """Firecrawl search + scrape.

    `only_main_content=True` is passed explicitly rather than left to the API
    default, and is logged in benchmark metadata. It materially affects the
    boilerplate metric, so it must not be an invisible setting.

    The `json` format is deliberately not used: it costs +4 credits/page and
    would duplicate extraction work the pipeline already does downstream.
    """

    name = "firecrawl"
    only_main_content = True
    formats = ("markdown",)

    def __init__(self, client=None, **kw):
        super().__init__(**kw)
        if client is None:
            from firecrawl import Firecrawl
            client = Firecrawl(api_key=os.environ["FIRECRAWL_API_KEY"])
        self.client = client

    @staticmethod
    def _field(obj, name: str, default=""):
        """Read a field whether the SDK hands back objects or dicts.

        Verified against firecrawl-py 4.45.1, but written defensively: this SDK
        has changed response shapes across majors, and a silent AttributeError
        here would look like a retrieval failure rather than a parsing bug.
        """
        if isinstance(obj, dict):
            return obj.get(name, default)
        return getattr(obj, name, default) or default

    @retry(**RETRY_SETTINGS)
    def search(self, query: str, max_results: int = 5) -> list[RetrievedDoc]:
        cached = self._cached("search", f"{query}|{max_results}")
        if cached is not None:
            return cached

        self._wait_turn()
        started = time.monotonic()
        response = self.client.search(
            query, limit=max_results, timeout=DEFAULT_TIMEOUT_S * 1000,
        )
        latency = int((time.monotonic() - started) * 1000)

        # 2 credits per 10 results, rounded up.
        self.meter.record(self.name, "search", 2.0 * math.ceil(max_results / 10))

        web = self._field(response, "web", []) or []
        docs = [
            RetrievedDoc(
                url=self._field(r, "url"),
                title=self._field(r, "title"),
                # Search returns a snippet in `description`; the equivalent of
                # Tavily's `content`. Full text requires a scrape.
                content=self._field(r, "description"),
                provider=self.name,
                latency_ms=latency,
            )
            for r in web
        ]
        self.cache.put(self.name, "search", f"{query}|{max_results}", docs)
        return docs

    @retry(**RETRY_SETTINGS)
    def fetch(self, url: str) -> RetrievedDoc:
        cached = self._cached("fetch", url)
        if cached is not None:
            return cached[0]

        self._wait_turn()
        started = time.monotonic()
        try:
            response = self.client.scrape(
                url,
                formats=list(self.formats),
                only_main_content=self.only_main_content,
                timeout=DEFAULT_TIMEOUT_S * 1000,
            )
            latency = int((time.monotonic() - started) * 1000)
            self.meter.record(self.name, "fetch", 1.0)

            markdown = self._field(response, "markdown")
            metadata = self._field(response, "metadata", {}) or {}
            doc = RetrievedDoc(
                url=url,
                title=self._field(metadata, "title"),
                content=markdown,
                provider=self.name,
                latency_ms=latency,
            )
            if not doc.content:
                doc.error = "Firecrawl returned empty content"
        except Exception as exc:
            # A scrape that raises still consumed an attempt; bill it, because
            # pretending it was free would understate real-world cost.
            latency = int((time.monotonic() - started) * 1000)
            self.meter.record(self.name, "fetch", 1.0)
            doc = RetrievedDoc(
                url=url, provider=self.name, latency_ms=latency,
                error=f"{type(exc).__name__}: {exc}",
            )

        self.cache.put(self.name, "fetch", url, [doc])
        return doc

    def live_credit_usage(self) -> dict | None:
        """Firecrawl's own view of credits spent, for cross-checking the meter.

        Our counter applies the documented rule; this is ground truth. Any gap
        between them is itself worth reporting.

        The SDK returns an object, not a dict, so attributes are read by name
        and the raw repr is kept alongside. Stringifying the whole thing (an
        earlier version of this) silently defeated the cross-check: the caller
        found no numeric field and skipped the comparison without complaining.
        """
        try:
            usage = self.client.get_credit_usage()
        except Exception as exc:
            return {"error": f"{type(exc).__name__}: {exc}"}

        if isinstance(usage, dict):
            return usage

        parsed = {
            field: getattr(usage, field)
            for field in ("remaining_credits", "plan_credits")
            if isinstance(getattr(usage, field, None), (int, float))
        }
        parsed["raw"] = str(usage)
        return parsed


class FirecrawlScrapeSearchProvider(FirecrawlProvider):
    """Firecrawl search WITH scrape_options, which is how its docs intend it.

    Bare `search` returns only short snippets (measured: median 162 chars
    against Tavily's 1,144 on the same query). The agent learns little per
    search, searches more, and exhausts its tool budget. Passing
    scrape_options returns full page content per result instead.

    The trade is cost: 2 credits for the search plus 1 per scraped result, so
    5 at limit=3 rather than 2. Benchmarked separately from bare search so the
    comparison reports a configuration difference rather than attributing a
    configuration choice to the provider.
    """

    name = "firecrawl_scrape"
    search_result_limit = 3

    @retry(**RETRY_SETTINGS)
    def search(self, query: str, max_results: int = 5) -> list[RetrievedDoc]:
        limit = min(max_results, self.search_result_limit)
        cached = self._cached("search_scrape", f"{query}|{limit}")
        if cached is not None:
            return cached

        from firecrawl.v2.types import ScrapeOptions

        self._wait_turn()
        started = time.monotonic()
        response = self.client.search(
            query,
            limit=limit,
            scrape_options=ScrapeOptions(
                formats=list(self.formats),
                only_main_content=self.only_main_content,
            ),
            timeout=DEFAULT_TIMEOUT_S * 1000,
        )
        latency = int((time.monotonic() - started) * 1000)

        web = self._field(response, "web", []) or []
        # 2 credits per 10 results, plus 1 per result actually scraped.
        self.meter.record(
            self.name, "search", 2.0 * math.ceil(limit / 10) + float(len(web)))

        docs = []
        for r in web:
            # Prefer scraped markdown; fall back to the snippet so a single
            # failed scrape inside the batch degrades to bare-search quality
            # rather than dropping the result entirely.
            content = self._field(r, "markdown") or self._field(r, "description")
            docs.append(RetrievedDoc(
                url=self._field(r, "url"),
                title=self._field(r, "title"),
                content=content,
                provider=self.name,
                latency_ms=latency,
            ))

        self.cache.put(self.name, "search_scrape", f"{query}|{limit}", docs)
        return docs


class HybridProvider:
    """Tavily for discovery, Firecrawl for page content.

    The hypothesis worth testing: Tavily's search ranking is competitive and
    cheaper, while Firecrawl's headless rendering handles JS-heavy pages that a
    plain fetch cannot. If true, the cheapest good configuration is neither
    provider alone.
    """

    name = "hybrid"

    def __init__(self, tavily: TavilyProvider | None = None,
                 firecrawl: FirecrawlProvider | None = None,
                 meter: CreditMeter | None = None,
                 cache: ResponseCache | None = None,
                 throttle: bool = True):
        self.meter = meter or CreditMeter()
        shared_cache = cache if cache is not None else ResponseCache()
        self.tavily = tavily or TavilyProvider(
            meter=self.meter, cache=shared_cache, throttle=throttle)
        self.firecrawl = firecrawl or FirecrawlProvider(
            meter=self.meter, cache=shared_cache, throttle=throttle)

    def search(self, query: str, max_results: int = 5) -> list[RetrievedDoc]:
        return self.tavily.search(query, max_results=max_results)

    def fetch(self, url: str) -> RetrievedDoc:
        return self.firecrawl.fetch(url)


# --------------------------------------------------------------------------
# Selection
# --------------------------------------------------------------------------

_PROVIDERS = {
    "tavily": TavilyProvider,
    "firecrawl": FirecrawlProvider,
    "firecrawl_scrape": FirecrawlScrapeSearchProvider,
    "hybrid": HybridProvider,
}

DEFAULT_PROVIDER = "tavily"


def get_provider(name: str | None = None, **kw):
    """Build a provider. Falls back to tavily loudly, never silently.

    An unrecognised RETRIEVAL_PROVIDER value changing retrieval without saying
    so would be worse than the typo it came from.
    """
    requested = (name or os.environ.get("RETRIEVAL_PROVIDER") or DEFAULT_PROVIDER).strip().lower()

    if requested not in _PROVIDERS:
        print(
            f"[retrieval] WARNING: unknown RETRIEVAL_PROVIDER={requested!r}; "
            f"falling back to {DEFAULT_PROVIDER!r}. "
            f"Valid values: {', '.join(sorted(_PROVIDERS))}."
        )
        requested = DEFAULT_PROVIDER

    return _PROVIDERS[requested](**kw)
