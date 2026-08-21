"""Tools the agent can call, and the record of every source they touched.

Source tracking lives here rather than in the model's output because it must
be trustworthy: the model can misattribute which page supported which claim,
but this list is written by our own code from the actual API responses.
"""

from tenacity import retry

from config import RETRY_SETTINGS, tavily_client

_sources_consulted: set[str] = set()

# Defaults to print(), which is what the CLI wants. A UI overrides this with
# set_progress_hook so the same tool functions can report progress into a
# web page instead of a terminal, without either caller knowing about the
# other.
_progress_hook = print


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


@retry(**RETRY_SETTINGS)
def search_web(query: str) -> str:
    """Search the web for current, real information.

    Use this whenever you need up-to-date facts about a company, its
    competitors, or its market. You may call this more than once with
    different queries if one search isn't enough.

    Args:
        query: The search query to look up.
    """
    _progress_hook(f"[search] {query}")
    response = tavily_client.search(query, max_results=5)

    context = ""
    for result in response["results"]:
        # Labelled in code, not left for the model to judge from prose
        # instructions alone — a deterministic tag is a smaller, more
        # reliable ask than "please recognise marketing content".
        tag = (
            " [ROUNDUP/LISTICLE CONTENT — useful for discovering company "
            "names, but do not treat its stats or claims as verified facts. "
            "Use extract_company_page on the company's own site to confirm.]"
            if looks_like_listicle(result["url"]) else ""
        )
        context += f"Title: {result['title']}{tag}\n"
        context += f"URL: {result['url']}\n"
        context += f"Content: {result['content']}\n\n"
        _sources_consulted.add(result["url"])

    return context


@retry(**RETRY_SETTINGS)
def extract_company_page(url: str) -> str:
    """Read the actual content of one specific page.

    Returns an explicit failure message rather than an empty string when the
    page can't be read — "the page was blank" and "we couldn't open the page"
    are different facts, and the caller needs to tell them apart.
    """
    _progress_hook(f"[extract] {url}")
    response = tavily_client.extract(url)

    if not response["results"]:
        return (f"Could not read the page at {url}. "
                f"It may be blocked, private, or unavailable.")

    _sources_consulted.add(url)
    return response["results"][0].get("raw_content", "")
