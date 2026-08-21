"""Tools the agent can call, and the record of every source they touched.

Source tracking lives here rather than in the model's output because it must
be trustworthy: the model can misattribute which page supported which claim,
but this list is written by our own code from the actual API responses.
"""

from config import tavily_client

_sources_consulted: set[str] = set()


def sources_consulted() -> list[str]:
    """Every URL actually fetched during this run, sorted."""
    return sorted(_sources_consulted)


def search_web(query: str) -> str:
    """Search the web for current, real information.

    Use this whenever you need up-to-date facts about a company, its
    competitors, or its market. You may call this more than once with
    different queries if one search isn't enough.

    Args:
        query: The search query to look up.
    """
    print(f"[search] {query}")
    response = tavily_client.search(query, max_results=5)

    context = ""
    for result in response["results"]:
        context += f"Title: {result['title']}\n"
        context += f"URL: {result['url']}\n"
        context += f"Content: {result['content']}\n\n"
        _sources_consulted.add(result["url"])

    return context


def extract_company_page(url: str) -> str:
    """Read the actual content of one specific page.

    Returns an explicit failure message rather than an empty string when the
    page can't be read — "the page was blank" and "we couldn't open the page"
    are different facts, and the caller needs to tell them apart.
    """
    print(f"[extract] {url}")
    response = tavily_client.extract(url)

    if not response["results"]:
        return (f"Could not read the page at {url}. "
                f"It may be blocked, private, or unavailable.")

    _sources_consulted.add(url)
    return response["results"][0].get("raw_content", "")
