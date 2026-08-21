"""Turn the finished research into a Markdown document on disk.

The report deliberately includes what was rejected and what the system
cannot do. A document that shows its own reasoning and admits its weaknesses
is more useful to a founder than one that projects false confidence.
"""

from datetime import date

from schemas import CompanyIdentity, Competitor, CompetitorResearch

LIMITATIONS = [
    'Competitor discovery depends on web search, which favours '
    'search-optimised content. "Best agencies" listicles are often published '
    'by a company that ranks itself highly; figures quoted in them are '
    'frequently unverifiable.',
    'Details attributed to a single promotional source should be treated as '
    'claims, not established facts.',
    'Competitor selection was checked automatically for scale and '
    'specificity, then reviewed by a human, but neither check guarantees '
    'completeness.',
]


def _bullets(lines: list[str], heading: str, items: list[str]) -> None:
    lines.append(f"**{heading}:**")
    lines.append("")
    lines.extend(f"- {item}" for item in items)
    lines.append("")


def build_report(
    company_name: str,
    company_url: str,
    identity: CompanyIdentity,
    research: CompetitorResearch,
    competitors: list[Competitor],
    excluded: list[tuple[str, str]],
    sources: list[str],
) -> str:
    lines: list[str] = [
        f"# Competitor Research: {company_name}",
        "",
        f"*Generated {date.today().isoformat()}*",
        "",
        "## The company",
        "",
        identity.description,
        "",
        f"- **Location:** {identity.location or 'not established'}",
    ]
    if company_url:
        lines.append(f"- **Identity anchored to:** {company_url}")
    lines += ["", f"## Competitors ({len(competitors)})", ""]

    for competitor in competitors:
        lines += [
            f"### {competitor.name}",
            "",
            f"**Why relevant:** {competitor.why_relevant}",
            "",
            f"**Product / service:** {competitor.product_or_service}",
            "",
            f"**Target customers:** {competitor.target_customers}",
            "",
            f"**Positioning:** {competitor.positioning}",
            "",
            f"**Pricing:** {competitor.pricing or 'Not publicly available'}",
            "",
        ]
        _bullets(lines, "Strengths", competitor.strengths)
        _bullets(lines, "Weaknesses", competitor.weaknesses)
        _bullets(lines, "Differentiators", competitor.differentiators)
        _bullets(lines, "Sources", competitor.sources)

    for heading, items in (
        ("Market trends", research.market_trends),
        ("Gaps and opportunities", research.market_gaps_opportunities),
        ("Potential threats", research.potential_threats),
    ):
        lines += [f"## {heading}", ""]
        lines.extend(f"- {item}" for item in items)
        lines.append("")

    if excluded:
        lines += [
            "## Excluded from this report",
            "",
            "Candidates that were considered and rejected, and why:",
            "",
        ]
        lines.extend(f"- **{name}** — {reason}" for name, reason in excluded)
        lines.append("")

    lines += ["## All sources consulted", ""]
    lines.extend(f"- {url}" for url in sources)
    lines.append("")

    lines += ["## Limitations", ""]
    lines.extend(f"- {item}" for item in LIMITATIONS)
    lines.append("")

    return "\n".join(lines)


def save_report(company_name: str, content: str) -> str:
    """Write the report next to the script and return the filename."""
    slug = "-".join(
        "".join(ch if ch.isalnum() else " " for ch in company_name).split()
    ).lower()
    filename = f"report-{slug or 'company'}.md"

    with open(filename, "w", encoding="utf-8") as f:
        f.write(content)

    return filename
