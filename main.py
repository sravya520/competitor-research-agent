"""Competitor research for startups.

Run it, give it a company name, and optionally a URL that identifies the
company. It produces a Markdown report with sources.

The flow:
    identify  -> confirm which company is meant (stop if ambiguous)
    research  -> the agent chooses its own searches and finds competitors
    verify    -> an independent pass checks each competitor
    review    -> you get the final say before anything is written
    report    -> Markdown file on disk
"""

import sys

import evaluate
import pipeline
import report as report_module
from schemas import Competitor
from tools import sources_consulted


def clean_input(prompt: str) -> str:
    """Read input, stripping whitespace and invisible byte-order marks.

    Pasted text often carries a BOM, which would otherwise leak into search
    queries and the report filename.
    """
    return input(prompt).replace("﻿", "").strip()


def review_competitors(
    competitors: list[Competitor],
    excluded: list[tuple[str, str]],
    problems: list[str],
) -> list[Competitor]:
    """Show what the system decided and let the human overrule it."""
    print("\n" + "=" * 64)
    print("REVIEW")
    print("=" * 64)

    if problems:
        print("\nAutomatic checks flagged:")
        for problem in problems:
            print(f"  ! {problem}")

    if excluded:
        print("\nAutomatically excluded by verification:")
        for name, reason in excluded:
            print(f"  - {name}: {reason}")

    if not competitors:
        return []

    print(f"\n{len(competitors)} competitor(s) passed verification:\n")
    for i, competitor in enumerate(competitors):
        print(f"  [{i}] {competitor.name} — {competitor.positioning}")

    answer = clean_input(
        "\nEnter the numbers of any you want REMOVED (comma-separated), "
        "or press Enter to keep all: "
    )

    to_remove: set[int] = set()
    if answer:
        try:
            to_remove = {int(part.strip()) for part in answer.split(",") if part.strip()}
        except ValueError:
            print("Could not read that input — keeping all competitors.")

    kept = []
    for i, competitor in enumerate(competitors):
        if i in to_remove:
            excluded.append((competitor.name, "Removed by human reviewer."))
        else:
            kept.append(competitor)

    return kept


def main() -> None:
    company_name = clean_input("Enter a company or startup name: ")
    company_url = clean_input(
        "Company website or LinkedIn URL (optional, press Enter to skip): "
    )

    # Step 0 — which company do we actually mean?
    identity = pipeline.identify_company(company_name, company_url)

    if identity is None:
        sys.exit("Could not confirm the company's identity within the allowed tool calls.")

    if not identity.confident_match:
        print(f'\nCould not confidently identify a single company for "{company_name}":')
        print(f"What was found: {identity.description}")
        print(f"Location: {identity.location or 'unknown'}")
        print(f"\nWhy it's ambiguous: {identity.ambiguity_note}")
        print("\nStopping here rather than guessing which company you meant.")
        sys.exit("Try again with a more specific name, or pass the company's URL.")

    print(f"\nConfirmed: {identity.description}\n")

    # Step 1 — research, with the agent choosing its own searches.
    research = pipeline.research_competitors(company_name, identity)

    if research is None:
        sys.exit("The agent didn't finish within its allowed number of tool calls.")

    # Step 2 — independent verification.
    verifications = pipeline.verify_competitors(company_name, identity, research.competitors)
    verified, excluded = pipeline.apply_verifications(research.competitors, verifications)

    # Automatic consistency checks. Detecting a fabricated citation isn't
    # enough — a link that 404s still looks like evidence, so it is removed.
    problems = evaluate.run_checks(verified, sources_consulted())
    removed = evaluate.drop_fabricated_sources(verified, sources_consulted())
    if removed:
        problems.append(f"Removed {removed} fabricated source URL(s) from the report.")

    # Corroboration is checked AFTER fabricated URLs are stripped above —
    # a fake source counting toward "2 independent domains" would be worse
    # than not checking at all.
    problems += evaluate.check_source_corroboration(verified)
    problems += evaluate.check_precise_claims_are_corroborated(verified)

    # Step 3 — human review.
    final = review_competitors(verified, excluded, problems)

    if not final:
        sys.exit("\nNo competitors remain, so there is no report to write.")

    # Step 4 — write it out.
    content = report_module.build_report(
        company_name=company_name,
        company_url=company_url,
        identity=identity,
        research=research,
        competitors=final,
        excluded=excluded,
        sources=sources_consulted(),
    )
    filename = report_module.save_report(company_name, content)

    print(f"\nReport written to {filename}")
    print(f"{len(final)} competitor(s) included, {len(excluded)} excluded.")


if __name__ == "__main__":
    main()
