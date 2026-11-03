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

from google.genai import errors

# Forces a live identify even when a recent one is stored. A reused identity
# is a judgement the user must be able to overrule: they may know the company
# rebranded, moved or was acquired, which no age limit can know for them.
FRESH_IDENTITY_FLAG = "--fresh-identity"

import evaluate
import failures
import memory
import pipeline
import recall
import report as report_module
from config import MODEL
from runstate import RunState
from schemas import Competitor


def clean_input(prompt: str) -> str:
    """Read input, stripping whitespace and invisible byte-order marks.

    Pasted text often carries a BOM, which would otherwise leak into search
    queries and the report filename.
    """
    return input(prompt).replace("﻿", "").strip()


def offer_remembered_urls(company_name: str) -> tuple[str, dict | None]:
    """Offer websites this name has resolved to before. Returns (url, pick).

    Memory suggests; the user decides. Nothing is chosen automatically, even
    when there is only one candidate: two unrelated companies can share a
    name, and resolving that is the user's call. Ages are shown rather than
    used as a filter, for the same reason.
    """
    candidates = recall.find_candidates(company_name)
    if not candidates:
        return "", None

    print(f'\nYou have researched "{company_name}" before:')
    for number, candidate in enumerate(candidates, start=1):
        print(f"  [{number}] {candidate['website']}"
              f"   (last run {candidate['run_at'][:10]}, "
              f"{candidate['age_days']:.0f} days ago)")
    print("  [0] none of these")

    answer = clean_input("Use one of these? Enter a number, or press Enter to skip: ")
    if not answer:
        return "", None

    try:
        choice = int(answer)
    except ValueError:
        print("Could not read that input — continuing without a URL.")
        return "", None

    if not 1 <= choice <= len(candidates):
        return "", None

    chosen = candidates[choice - 1]
    print(f"Using {chosen['website']}, remembered from the run on "
          f"{chosen['run_at'][:10]}.")
    return chosen["website"], chosen


def review_competitors(
    competitors: list[Competitor],
    excluded: list[tuple[str, str]],
    problems: list[str],
) -> tuple[list[Competitor], list[str]]:
    """Show what the system decided and let the human overrule it.

    Returns (kept, names_the_human_removed). The removals are also appended
    to `excluded` for the report, which does not care who rejected what;
    they are returned separately as well because the run ledger does -- a
    reviewer's choice is evidence of what this user wants, and verification
    rejecting a candidate is not.
    """
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
        return [], []

    print(f"\n{len(competitors)} competitor(s) passed verification:\n")
    for i, competitor in enumerate(competitors):
        print(f"  [{i}] {competitor.name}: {competitor.positioning}")

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

    kept: list[Competitor] = []
    removed: list[str] = []
    for i, competitor in enumerate(competitors):
        if i in to_remove:
            excluded.append((competitor.name, "Removed by human reviewer."))
            removed.append(competitor.name)
        else:
            kept.append(competitor)

    return kept, removed


def main() -> None:
    allow_recall = FRESH_IDENTITY_FLAG not in sys.argv

    # One run, one state: its own source ledger, progress output and model
    # versions. Nothing about a run lives at module level, so two runs can
    # never read or clear each other's evidence.
    run = RunState()

    company_name = clean_input("Enter a company or startup name: ")
    company_url = clean_input(
        "Company website or LinkedIn URL (optional, press Enter to skip): "
    )

    # A name on its own cannot find its own history, because runs are filed
    # under a domain. So memory offers what this name resolved to before and
    # the user confirms; from there the run continues exactly as if they had
    # typed that URL, including reusing a fresh identity for it.
    url_remembered = None
    if not company_url:
        company_url, url_remembered = offer_remembered_urls(company_name)

    # Step 0 — which company do we actually mean? A company researched
    # before under its own domain can reuse that answer; see recall.py for
    # when it may not.
    identity, identity_recalled = recall.establish_identity(
        company_name, company_url, run, allow_recall=allow_recall,
    )

    if identity is None:
        sys.exit("Could not confirm the company's identity within the allowed tool calls.")

    if not identity.confident_match:
        print(f'\nCould not confidently identify a single company for "{company_name}":')
        print(f"What was found: {identity.description}")
        print(f"Location: {identity.location or 'unknown'}")
        print(f"\nWhy it's ambiguous: {identity.ambiguity_note}")
        print("\nStopping here rather than guessing which company you meant.")
        sys.exit("Try again with a more specific name, or pass the company's URL.")

    if identity_recalled:
        print(f"\nReusing the identity established on "
              f"{identity_recalled['established_at'][:10]} "
              f"({identity_recalled['age_days']:.0f} days ago). "
              f"Run with {FRESH_IDENTITY_FLAG} to establish it fresh instead.")

    print(f"\nConfirmed: {identity.description}")
    print(f"Location: {identity.location or 'not established'}"
          + (f" | Website: {identity.website}" if identity.website else "") + "\n")

    # Step 1 — research, with the agent choosing its own searches.
    research = pipeline.research_competitors(company_name, identity, run)

    if research is None:
        sys.exit("The agent didn't finish within its allowed number of tool calls.")

    # Step 2 — independent verification.
    verifications = pipeline.verify_competitors(
        company_name, identity, research.competitors, run)
    verified, excluded = pipeline.apply_verifications(research.competitors, verifications)

    # Automatic consistency checks. Detecting a fabricated citation isn't
    # enough — a link that 404s still looks like evidence, so it is removed.
    problems = evaluate.run_checks(verified, run.sources_consulted())
    removed = evaluate.drop_fabricated_sources(verified, run.sources_consulted())
    if removed:
        problems.append(f"Removed {removed} fabricated source URL(s) from the report.")

    # Corroboration is checked AFTER fabricated URLs are stripped above —
    # a fake source counting toward "2 independent domains" would be worse
    # than not checking at all.
    problems += evaluate.check_source_corroboration(verified)
    problems += evaluate.check_precise_claims_are_corroborated(verified)

    # Step 3 — human review. Snapshot the automatic exclusions first: review
    # appends the reviewer's own removals to the same list, and the ledger
    # needs to tell the two apart.
    excluded_auto = list(excluded)
    final, removed_by_human = review_competitors(verified, excluded, problems)

    if not final:
        sys.exit("\nNo competitors remain, so there is no report to write.")

    # Step 4 — write it out.
    # How this run differs from the last one for the same company. Returns
    # None, and so writes no section, unless memory is on and a prior run
    # exists under a strong key.
    key, key_is_strong = memory.canonical_key(
        identity.website or company_url, company_name)
    comparison = recall.since_last_run(
        key, key_is_strong, final,
        excluded_names=[name for name, _ in excluded],
        current_model_resolved=run.model_versions(),
        current_retrieval_provider=getattr(run.provider, "name", ""),
    )

    content = report_module.build_report(
        company_name=company_name,
        company_url=company_url,
        identity=identity,
        research=research,
        competitors=final,
        excluded=excluded,
        sources=run.sources_consulted(),
        identity_recalled=identity_recalled,
        url_remembered=url_remembered,
        since_last_run=comparison,
    )
    filename = report_module.save_report(company_name, content)

    # Step 5 — file this run in the ledger. Best-effort by design: nothing
    # reads it yet, so a failure to record must not cost the user the report
    # they just waited for.
    try:
        recorded = memory.record_run(
            company_name=company_name,
            company_url=company_url,
            identity=identity,
            competitors=final,
            excluded_auto=excluded_auto,
            removed_by_human=removed_by_human,
            problems=problems,
            sources=run.sources_consulted(),
            model=MODEL,
            model_resolved=run.model_versions(),
            retrieval_provider=getattr(run.provider, "name", ""),
            url_source=("remembered" if url_remembered
                        else "typed" if company_url else "none"),
            url_remembered_from=(url_remembered["run_at"] if url_remembered
                                 else ""),
            # Carried forward, not restamped: an identity must not become
            # immortal by being reused every few weeks.
            identity_established_at=(identity_recalled["established_at"]
                                     if identity_recalled else ""),
        )
        # record_run returns None both when memory is off and when the
        # company could not be keyed. Only the second is worth reporting.
        if recorded is None and memory.enabled():
            print("[memory] Run not recorded: the company could not be keyed.")
    except OSError as exc:
        print(f"[memory] Run not recorded ({exc}).")

    print(f"\nReport written to {filename}")
    print(f"{len(final)} competitor(s) included, {len(excluded)} excluded.")


def run() -> None:
    """Entry point: report a provider failure as a sentence, not a traceback.

    app.py has handled this since a transient 503 reached a user as a generic
    error, but the CLI never did. Found by running it for real: an exhausted
    daily quota printed four screens of retry detail and then a traceback,
    while the web UI had a plain sentence for the same error all along.

    Unexpected exceptions are deliberately left to raise. The CLI is the
    development surface, and there a traceback is the useful answer.
    """
    try:
        main()
    except errors.APIError as exc:
        print(failures.api_error_log_line(exc), flush=True)
        sys.exit(failures.api_error_message(exc.code, surface="cli"))
    except KeyboardInterrupt:
        sys.exit("\nStopped.")


if __name__ == "__main__":
    run()
