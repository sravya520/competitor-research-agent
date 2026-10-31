"""Tools the agent can call, built per run, plus the listicle rule.

Source tracking lives on the run (see runstate.py) rather than in the
model's output, because it must be trustworthy: the model can misattribute
which page supported which claim, but the ledger is written by our own code
from the actual API responses.

The two tool functions are produced by make_tools(run), so each run writes
into its own ledger and its own progress sink. They used to be module-level
functions over module-level state, which is correct for one run per process
and wrong for the deployed app, where every visitor shares the process. The
closures keep their names, parameters, type hints and docstrings, because
all four are part of the schema the SDK sends to Gemini: the docstring is
prompt text, not a comment.

Retrieval itself is delegated to a provider (see retrieval.py), selected by
RETRIEVAL_PROVIDER and defaulting to tavily. This module deliberately keeps
ownership of the three things the rest of the pipeline depends on, so that
swapping providers cannot change them:

    - the exact string the model sees
    - the [ROUNDUP/LISTICLE CONTENT] tag
    - the source ledger behind the fabrication check

Retries live on the provider methods, at the network boundary, rather than
wrapping these functions. Same number of attempts against the same failure,
one layer closer to what actually fails.
"""

import threading

from retrieval import RetrievedDoc, get_provider

# Providers are process-wide and the runs that use them are not. One provider
# instance per name holds the HTTP clients, the disk response cache and the
# credit meter, all of which SHOULD be shared: a warm cache is the reason a
# rerun costs no credits. Built under a lock so two threads starting at once
# cannot each pay to construct one, and so neither sees a half-built object.
_providers: dict[str, object] = {}
_providers_lock = threading.Lock()


def provider_for(name: str | None = None):
    """The shared provider for a name, built once per process.

    Lazy, so importing this module needs no API key for whichever provider
    happens to be selected, and tests can pass their own provider on the run
    instead.
    """
    with _providers_lock:
        key = (name or "").strip().lower() or "__default__"
        if key not in _providers:
            _providers[key] = get_provider(name)
        return _providers[key]


def reset_providers() -> None:
    """Drop the cached providers. For tests; not used by the product."""
    with _providers_lock:
        _providers.clear()


def _provider_for_run(run):
    """The run's provider, resolving and remembering it on first use."""
    if run.provider is None:
        run.provider = provider_for(run.provider_name)
    return run.provider


# URL-path patterns typical of "best X agencies" roundup content. Domain
# blocking doesn't work here — sites like excited.agency or 925studios.co are
# real companies' own domains that also happen to publish listicles ranking
# themselves first, so the same domain can be a legitimate competitor's site
# in one context and an unreliable source in another. The path, not the
# domain, is what actually signals "roundup content".
_LISTICLE_MARKERS = ("best-", "top-", "-alternatives", "-vs-", "/resources/")


def looks_like_listicle(url: str) -> bool:
    """True if a URL's path matches typical "best agencies" roundup content.

    Public (not prefixed `_`) because evaluate.py uses the same definition to
    measure how much of a report's citations rest on this kind of source.
    """
    return any(marker in url.lower() for marker in _LISTICLE_MARKERS)


def _record(run, doc: RetrievedDoc) -> bool:
    """Add a URL to this run's ledger, but only for a successful fetch.

    This single rule is what keeps evaluate.check_sources_are_real
    meaningful. The ledger is treated downstream as proof a URL was really
    retrieved, so recording a failure here would let a model cite a page
    nobody ever read and have it pass the fabrication check.

    A cache hit still records: the URL was retrieved for this run as far as
    the report is concerned, and whether the bytes came from the network or
    from disk is a billing detail, not an evidence one.
    """
    if doc.ok:
        run.record_source(doc.url)
        return True
    return False


def make_tools(run):
    """Build this run's (search_web, extract_company_page).

    Returned as a list in the order the pipeline passes them to Gemini.
    Each closes over `run`, so the ledger, the progress sink and the
    truncation counters belong to one run and cannot be reached by another.
    """

    def search_web(query: str) -> str:
        """Search the web for current, real information.

        Use this whenever you need up-to-date facts about a company, its
        competitors, or its market. You may call this more than once with
        different queries if one search isn't enough.

        Args:
            query: The search query to look up.
        """
        run.progress(f"[search] {query}")
        docs = _provider_for_run(run).search(query, max_results=5)

        context = ""
        for doc in docs:
            if not _record(run, doc):
                # A result we could not retrieve is not shown to the model at
                # all. Rendering it would put a URL in front of the model that
                # is absent from the ledger, which the fabrication check would
                # later flag as invented — blaming the model for our own
                # failed fetch.
                continue

            # Labelled in code, not left for the model to judge from prose
            # instructions alone — a deterministic tag is a smaller, more
            # reliable ask than "please recognise marketing content".
            tag = (
                " [ROUNDUP/LISTICLE CONTENT — useful for discovering company "
                "names, but do not treat its stats or claims as verified facts. "
                "Use extract_company_page on the company's own site to confirm.]"
                if looks_like_listicle(doc.url) else ""
            )
            content = run.cap(doc.content, "search_chars", "search_results",
                              "search_truncated")

            context += f"Title: {doc.title}{tag}\n"
            context += f"URL: {doc.url}\n"
            context += f"Content: {content}\n\n"

        return context

    def extract_company_page(url: str) -> str:
        """Read the actual content of one specific page.

        Returns an explicit failure message rather than an empty string when
        the page can't be read — "the page was blank" and "we couldn't open
        the page" are different facts, and the caller needs to tell them
        apart.
        """
        run.progress(f"[extract] {url}")
        doc = _provider_for_run(run).fetch(url)

        if not _record(run, doc):
            return (f"Could not read the page at {url}. "
                    f"It may be blocked, private, or unavailable.")

        return run.cap(doc.content, "page_chars", "pages", "pages_truncated")

    return [search_web, extract_company_page]
