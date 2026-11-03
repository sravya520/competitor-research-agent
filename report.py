"""Turn the finished research into a Markdown document on disk.

The report deliberately includes what was rejected and what the system
cannot do. A document that shows its own reasoning and admits its weaknesses
is more useful to a founder than one that projects false confidence.
"""

from datetime import date

from evaluate import find_uncorroborated_precise_claim, source_domain_count
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
    'Each competitor\'s source count reflects DISTINCT DOMAINS, not distinct '
    'pages: a company\'s own site cited twice still counts as one source. '
    '"Single source" does not mean a competitor is wrong, only that its '
    'profile has not yet been checked against independent evidence.',
]


def _bullets(lines: list[str], heading: str, items: list[str]) -> None:
    lines.append(f"**{heading}:**")
    lines.append("")
    lines.extend(f"- {item}" for item in items)
    lines.append("")


def _sources_section(lines: list[str], competitor: Competitor) -> None:
    """Sources, with an honest label on how corroborated they are.

    This label has to live in the saved report itself, not just the
    interactive review screen — a founder reading the file later, or anyone
    who downloaded it without stepping through review, should still see it.
    """
    domains = source_domain_count(competitor)
    stat = find_uncorroborated_precise_claim(competitor)

    if stat:
        note = (f" _(⚠ single source: the figure {stat!r} in this profile "
                 f"is unverified, not an established fact)_")
    elif domains == 0:
        note = " _(no sources cited)_"
    elif domains == 1:
        note = " _(single source: not independently corroborated)_"
    else:
        note = f" _(corroborated across {domains} independent sources)_"

    lines.append(f"**Sources:**{note}")
    lines.append("")
    lines.extend(f"- {url}" for url in competitor.sources)
    lines.append("")


def _since_last_run_section(lines: list[str], comparison: dict) -> None:
    """Compare this run with the previous one, in plain arithmetic.

    Nothing here is model-written. The section exists because a founder
    running this monthly wants the delta, and a delta invented by a model
    would be worse than none.

    The wording avoids saying a competitor was dropped or disappeared.
    Retrieval varies between runs, so an absence is evidence about this
    run's search, not about the company.
    """
    established = (comparison.get("previous_run_at") or "")[:10]
    age = comparison.get("age_days")
    if age is None:
        when = ""
    elif age < 1:
        when = " (earlier today)"
    else:
        when = f" ({age:.0f} days ago)"

    lines += [f"## Since your last run on {established}{when}", ""]

    provenance = comparison.get("provenance_changed")
    if provenance:
        previous_model = ", ".join(provenance["previous_model"]) or "not recorded"
        current_model = ", ".join(provenance["current_model"]) or "not recorded"
        lines += [
            "**Read the differences below with care:** this run and the "
            "previous one did not use the same setup, so a change here may "
            "come from the model or the retrieval backend rather than from "
            "the market.",
            "",
            f"- Model: {previous_model} previously, {current_model} this run",
            f"- Retrieval: {provenance['previous_provider'] or 'not recorded'} "
            f"previously, {provenance['current_provider'] or 'not recorded'} "
            f"this run",
            "",
        ]

    if comparison["new"]:
        lines += ["**New this run:**", ""]
        lines += [f"- {name}" for name in comparison["new"]]
        lines.append("")

    if comparison["not_found"]:
        lines += ["**Not found this time:**", ""]
        lines += [f"- {name}" for name in comparison["not_found"]]
        lines += [
            "",
            "Live search varies between runs, so this does not mean the "
            "company stopped competing.",
            "",
        ]

    if comparison["still_present"]:
        lines += ["**Still present:**", ""]
        for entry in comparison["still_present"]:
            notes = []
            if entry["matched_by_name"]:
                notes.append("matched by name")
            if entry["pricing_before"]:
                notes.append(f"pricing changed: {entry['pricing_before']} "
                             f"to {entry['pricing_after']}")
            suffix = f" _({'; '.join(notes)})_" if notes else ""
            lines.append(f"- {entry['name']}{suffix}")
        lines.append("")

    if not (comparison["new"] or comparison["not_found"]
            or comparison["still_present"]):
        lines += ["Nothing to compare: the previous run recorded no "
                  "competitors.", ""]


NO_COMPARABLE_COMPETITORS = "No competitors of comparable scale were found."


def _considered_section(lines: list[str], considered: list) -> None:
    """What was found and then refused as not comparable.

    A run that verifies nothing used to write no report at all, which is
    the worst possible output for a tool aimed at startups: the founder
    learns nothing, not even that the search ran. These candidates are NOT
    competitors and are never counted as any, but showing them with the
    verifier's own reason turns an empty result into an auditable one.

    Only candidates the verification step refused. Anything the reviewer
    removed by hand stays out: they already know, and listing their own
    decision back to them as a finding would be noise.
    """
    lines += [
        "## Candidates considered but not comparable",
        "",
        "These companies were found by the search and then refused by the "
        "independent verification step, with its reason given below. They "
        "are not competitors of this company and are not counted as any. "
        "They are listed so the search itself can be checked.",
        "",
    ]

    for competitor, reason in considered:
        lines += [
            f"### {competitor.name}",
            "",
            f"**Why it was not comparable:** {reason}",
            "",
        ]
        if competitor.scale_and_stage:
            lines += [f"**Scale and stage:** {competitor.scale_and_stage}", ""]
        _sources_section(lines, competitor)


def build_report(
    company_name: str,
    company_url: str,
    identity: CompanyIdentity,
    research: CompetitorResearch,
    competitors: list[Competitor],
    excluded: list[tuple[str, str]],
    sources: list[str],
    identity_recalled: dict | None = None,
    url_remembered: dict | None = None,
    since_last_run: dict | None = None,
    considered: list | None = None,
) -> str:
    lines: list[str] = [
        f"# Competitor Research: {company_name}",
        "",
        f"*Generated {date.today().isoformat()}*",
        "",
    ]

    # Said first, because it is the answer to the question that was asked.
    if not competitors:
        lines += [f"**{NO_COMPARABLE_COMPETITORS}**", ""]

    lines += [
        "## The company",
        "",
        identity.description,
        "",
        f"- **Location:** {identity.location or 'not established'}",
    ]
    if identity.website:
        lines.append(f"- **Website:** {identity.website}")
    if company_url:
        lines.append(f"- **Identity anchored to:** {company_url}")

    # Anything taken from an earlier run has to carry that run's date.
    # Without this line a fact established weeks ago reads exactly like one
    # checked today, which is the opposite of what this report is for. One
    # line covers both kinds of reuse, since they often happen together: a
    # remembered website leads to a strong key, which is what makes the
    # identity reusable in the first place.
    memory_notes = []
    if url_remembered:
        memory_notes.append(
            f"website remembered from the run on "
            f"{(url_remembered.get('run_at') or '')[:10]} and confirmed by you")
    if identity_recalled:
        # The date the identity was ESTABLISHED, not the date of the last run
        # that reused it. Those differ on every reuse, and the older one is
        # the honest answer to "how current is this".
        established = (identity_recalled.get("established_at")
                       or identity_recalled.get("run_at") or "")[:10]
        age = identity_recalled.get("age_days")
        aged = f" ({age:.0f} days before this report)" if age is not None else ""
        memory_notes.append(
            f"identity established on {established}{aged} and reused, not "
            f"re-established for this report")
    if memory_notes:
        lines.append(f"- **From memory:** {'; '.join(memory_notes)}")
    lines.append("")

    # Placed before the competitor list: a repeat reader wants the delta
    # first, and a first-time reader never sees this section at all.
    if since_last_run:
        _since_last_run_section(lines, since_last_run)

    lines += [f"## Competitors ({len(competitors)})", ""]

    if not competitors:
        lines += [
            f"{NO_COMPARABLE_COMPETITORS} Verification refused every "
            f"candidate the search proposed"
            + (", each for the reason given below." if considered else ".")
            + " A smaller company is harder to find peers for: search "
            "surfaces the large names in a category, and those are not "
            "comparable.",
            "",
        ]
        if considered:
            _considered_section(lines, considered)

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
        _sources_section(lines, competitor)

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
        lines.extend(f"- **{name}**: {reason}" for name, reason in excluded)
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
