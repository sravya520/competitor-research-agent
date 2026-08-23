"""Cheap, deterministic checks on a research result.

These are not quality judgements — they don't ask whether the competitors are
*good*. They ask whether the output is internally consistent: did the model
cite URLs it was actually given, did it return real companies rather than
categories. Checks like these cost nothing to run, never disagree with
themselves, and catch things a human reviewer reads straight past.
"""

import re
from urllib.parse import urlparse

from schemas import Competitor
from tools import looks_like_listicle

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


def check_competitor_count(competitors: list[Competitor], minimum: int) -> list[str]:
    """Check that at least `minimum` competitors survived verification."""
    if len(competitors) < minimum:
        return [f"Expected at least {minimum} competitors, got {len(competitors)}."]
    return []


def source_domain(url: str) -> str:
    """The comparable domain for a URL — strips 'www.' so it isn't miscounted
    as a domain distinct from the same site without that prefix."""
    return urlparse(url).netloc.lower().removeprefix("www.")


def source_domain_count(competitor: Competitor) -> int:
    """Number of DISTINCT domains behind a competitor's citations.

    Two pages on the same domain are not independent corroboration — a
    company's own site linking to itself twice confirms nothing beyond what
    one of those pages already said. Counting domains, not URLs, is what
    actually measures whether a claim has been checked against more than one
    source.
    """
    return len({source_domain(url) for url in competitor.sources})


def check_source_corroboration(
    competitors: list[Competitor],
    minimum_domains: int = 2,
) -> list[str]:
    """Flag competitors whose entire profile rests on a single source domain.

    Not a rejection — a small, real company legitimately having only its own
    website as a source doesn't make it invalid. This is a transparency
    signal: the point is that a report should never present a single-source
    claim and a claim checked against multiple independent pages identically,
    the way a bluff and a fact would look the same without this.
    """
    problems: list[str] = []
    for competitor in competitors:
        count = source_domain_count(competitor)
        if count == 0:
            problems.append(f"{competitor.name} has no cited sources at all.")
        elif count < minimum_domains:
            problems.append(
                f"{competitor.name}'s profile rests on a single source "
                f"domain — not independently corroborated."
            )
    return problems


# Precise-sounding percentages and dollar figures — "92% implementation
# success rate", "$1,200/mo" — are exactly the shape of the uncitable
# marketing statistics found in a real self-ranking listicle during
# development. Precision alone doesn't prove invention; precision plus a
# single source is the pattern that fooled a careful human reader that time.
_PRECISE_STAT = re.compile(r"\d{1,3}\s?%|\$\s?[\d,]+(?:k\b|K\b|/mo|/month)?")


def find_uncorroborated_precise_claim(
    competitor: Competitor,
    minimum_domains: int = 2,
) -> str | None:
    """The matched figure (e.g. '92%') if the profile has one AND rests on
    a single source, else None. Shared by the check below and report.py, so
    the report's inline warning and the review-time flag never disagree."""
    text = " ".join([
        competitor.pricing or "",
        competitor.why_relevant,
        " ".join(competitor.strengths),
        " ".join(competitor.weaknesses),
    ])
    match = _PRECISE_STAT.search(text)
    if match and source_domain_count(competitor) < minimum_domains:
        return match.group()
    return None


def check_precise_claims_are_corroborated(
    competitors: list[Competitor],
    minimum_domains: int = 2,
) -> list[str]:
    """Flag oddly specific statistics that rest on a single source.

    Not proof of fabrication — a real, precise figure can genuinely come
    from one page. This is a heightened version of check_source_corroboration
    for the specific claim shape most associated, in practice, with invented
    marketing copy: something that SOUNDS measured and precise but has
    nothing independently backing it up.
    """
    problems: list[str] = []
    for competitor in competitors:
        stat = find_uncorroborated_precise_claim(competitor, minimum_domains)
        if stat:
            problems.append(
                f"{competitor.name}'s profile cites a precise figure "
                f"({stat!r}) backed by only one source — treat it as an "
                f"unverified claim, not an established fact."
            )
    return problems


def run_checks(
    competitors: list[Competitor],
    consulted_urls: list[str],
    minimum: int = 2,
) -> list[str]:
    """Run every check and return all problems found.

    The default minimum is 2: a single competitor is not a competitive
    landscape, and a report that presents one as such is misleading.
    """
    return (
        check_sources_are_real(competitors, consulted_urls)
        + check_no_generic_competitors(competitors)
        + check_competitor_count(competitors, minimum)
    )


def primary_source_ratio(competitors: list[Competitor]) -> float | None:
    """Fraction of CITED sources that are not roundup/listicle content.

    A metric, not a gate — it doesn't fail the suite, because discovering a
    candidate's name via a listicle is legitimate. What matters is whether
    listicles dominate the citations a reader is expected to trust. Returns
    None when there are no citations to measure, rather than a misleading 0.
    """
    all_sources = [url for c in competitors for url in c.sources]
    if not all_sources:
        return None

    primary = sum(1 for url in all_sources if not looks_like_listicle(url))
    return primary / len(all_sources)


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
