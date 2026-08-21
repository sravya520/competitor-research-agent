"""Cheap, deterministic checks on a research result.

These are not quality judgements — they don't ask whether the competitors are
*good*. They ask whether the output is internally consistent: did the model
cite URLs it was actually given, did it return real companies rather than
categories. Checks like these cost nothing to run, never disagree with
themselves, and catch things a human reviewer reads straight past.
"""

from schemas import Competitor

# Words that signal a category rather than a company. Deliberately narrow:
# plenty of real companies are called "... Studios" or "... Design", so only
# qualifiers that cannot belong to a specific name are listed here.
GENERIC_MARKERS = (
    "local ",
    "freelance ",
    "independent ",
    "various ",
    "other ",
    "similar ",
    "small agencies",
    "boutique agencies",
    "design agencies",
    "design studios",
    "marketing agencies",
)


def normalise_url(url: str) -> str:
    """Make URLs comparable.

    The same page routinely appears both with and without a trailing slash,
    which would otherwise look like two different sources — or make a real
    citation look fabricated.
    """
    return url.strip().rstrip("/").lower()


def check_sources_are_real(
    competitors: list[Competitor],
    consulted_urls: list[str],
) -> list[str]:
    """Find any cited URL that was never actually fetched.

    This is the strongest check in the file. `consulted_urls` is recorded by
    our own code from real API responses, so a citation missing from it was
    invented or altered by the model.
    """
    consulted = {normalise_url(url) for url in consulted_urls}

    problems: list[str] = []
    for competitor in competitors:
        for source in competitor.sources:
            if normalise_url(source) not in consulted:
                problems.append(
                    f"{competitor.name} cites {source}, which was never fetched."
                )
    return problems


def check_no_generic_competitors(competitors: list[Competitor]) -> list[str]:
    """Flag competitors that are categories rather than named companies.

    A heuristic, not a proof: it will miss creative phrasings and could in
    principle flag an oddly-named real company. It is a safety net behind the
    prompt and the verification step, not a replacement for them.
    """
    problems: list[str] = []
    for competitor in competitors:
        name = competitor.name.lower()
        for marker in GENERIC_MARKERS:
            if marker in name:
                problems.append(
                    f'"{competitor.name}" looks like a category, not a specific company.'
                )
                break
    return problems


def run_checks(competitors: list[Competitor], consulted_urls: list[str]) -> list[str]:
    """Run every check and return all problems found."""
    return (
        check_sources_are_real(competitors, consulted_urls)
        + check_no_generic_competitors(competitors)
    )


def drop_fabricated_sources(
    competitors: list[Competitor],
    consulted_urls: list[str],
) -> int:
    """Remove citations that were never fetched. Returns how many were removed.

    Detecting a fabricated URL is not enough — a report that ships a link
    which 404s is worse than one that cites nothing, because the broken link
    still looks like evidence.
    """
    consulted = {normalise_url(url) for url in consulted_urls}

    removed = 0
    for competitor in competitors:
        kept = [s for s in competitor.sources if normalise_url(s) in consulted]
        removed += len(competitor.sources) - len(kept)
        competitor.sources = kept

    return removed


def check_competitor_cou