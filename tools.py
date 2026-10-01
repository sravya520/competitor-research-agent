"""Tools the agent can call, and the record of every source they touched.

Source tracking lives here rather than in the model's output because it must
be trustworthy: the model can misattribute which page supported which claim,
but this list is written by our own code from the actual API responses.

Retrieval itself is delegated to a provider (see retrieval.py), selected by
RETRIEVAL_PROVIDER and defaulting to tavily. This module deliberately keeps
ownership of the three things the rest of the pipeline depends on, so that
swapping providers cannot change them:

    - the exact string the model sees
    - the [ROUNDUP/LISTICLE CONTENT] tag
    - the source ledger behind the fabrication check

Retries now live on the provider methods, at the network boundary, rather than
wrapping these functions. Same number of attempts against the same failure,
one layer closer to what actually fails.
"""

from retrieval import RetrievedDoc, get_provider

_sources_consulted: set[str] = set()

# Defaults to print(), which is what the CLI wants. A UI overrides this with
# set_progress_hook so the same tool functions can report progress into a
# web page instead of a terminal, without either caller knowing about the
# other.
_progress_hook = print

_provider = None


def active_provider():
    """The retrieval provider, built on first use.

    Lazy so that importing this module does not require API keys for whichever
    provider happens to be selected — tests inject their own.
    """
    global _provider
    if _provider is None:
        _provider = get_provider()
    return _provider


def set_provider(provider) -> None:
    """Override the provider. Used by tests and the benchmark harness."""
    global _provider
    _provider = provider


def sources_consulted() -> list[str]:
    """Every URL actually fetched during this run, sorted."""
    return sorted(_sources_consulted)


def reset_sources() -> None:
    """Clear the record. Needed when several companies run in one process,
    so one run's sources don't leak into the next one's checks."""
    _sources_consulted.clear()


def set_progress_hook(hook) -> None:
    """Redirect progress messages somewhere other than the terminal."""
    global _progress_hook
    _progress_hook = hook


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


def _record(doc: RetrievedDoc) -> bool:
    """Add a URL to the ledger, but only for a genuinely successful fetch.

    This single rule is what keeps evaluate.check_sources_are_real meaningful.
    The ledger is treated downstream as proof a URL was really retrieved, so
    recording a failure here would let a model cite a page nobody ever read
    and have it pass the fabrication check.
    """
    if doc.ok:
        _sources_consulted.add(doc.url)
        return True
    return False


def search_web(query: str) -> str:
    """Search the web for current, real information.

    Use this whenever you need up-to-date facts about a company, its
    competitors, or its market. You may call this more than once with
    different queries if one search isn't enough.

    Args:
        query: The search query to look up.
    """
    _progress_hook(f"[search] {query}")
    docs = active_provider().search(query, max_results=5)

    context = ""
    for doc in docs:
        if not _record(doc):
            # A result we could not retrieve is not shown to the model at all.
            # Rendering it would put a URL in front of the model that is absent
            # from the ledger, which the fabrication check would later flag as
            # invented — blaming the model for our own failed fetch.
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
        context += f"Title: {doc.title}{tag}\n"
        context += f"URL: {doc.url}\n"
        context += f"Content: {doc.content}\n\n"

    return context


def extract_company_page(url: str) -> str:
    """Read the actual content of one specific page.

    Returns an explicit failure message rather than an empty string when the
    page can't be read — "the page was blank" and "we couldn't open the page"
    are different facts, and the caller needs to tell them apart.
    """
    _progress_hook(f"[extract] {url}")
    doc = active_provider().fetch(url)

    if not _record(doc):
        return (f"Could not read the page at {url}. "
                f"It may be blocked, private, or unavailable.")

    return doc.content
