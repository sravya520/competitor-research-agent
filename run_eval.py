"""Run the regression cases in eval_cases.py and report pass/fail.

    python run_eval.py              # every case
    python run_eval.py Duolingo     # only cases whose id or company matches

Each case costs several API calls, so on a free tier prefer running one at a
time while iterating.
"""

import sys

import evaluate
import pipeline
import tools
from eval_cases import CASES


def _names(competitors) -> list[str]:
    return [c.name for c in competitors]


def run_case(case: dict) -> tuple[list[str], dict]:
    """Run one case. Returns (failures, metrics).

    An empty failures list means the case passed. `metrics` holds whatever
    was measurable — empty when the case stopped before producing anything
    to measure. Kept as a dict rather than several return values so adding
    a new metric later doesn't mean changing this function's signature.
    """
    tools.reset_sources()
    failures: list[str] = []

    identity = pipeline.identify_company(case["company"], case["url"] or "")
    stopped = identity is None or not identity.confident_match

    if case["expect_stop"]:
        if not stopped:
            failures.append(
                f"Expected to stop on an ambiguous name, but confidently "
                f"identified: {identity.description[:120]}"
            )
        return failures, {}

    if stopped:
        note = identity.ambiguity_note if identity else "no identity returned"
        failures.append(f"Expected a confident identification, but stopped: {note}")
        return failures, {}

    research = pipeline.research_competitors(case["company"], identity)
    if research is None:
        failures.append("Research step returned nothing (ran out of tool calls).")
        return failures, {}

    verifications = pipeline.verify_competitors(case["company"], identity, research.competitors)
    kept, _ = pipeline.apply_verifications(research.competitors, verifications)
    found = _names(kept)
    print(f"    found: {', '.join(found) or '(none)'}")

    minimum = case.get("min_competitors", 1)
    if len(kept) < minimum:
        failures.append(f"Expected at least {minimum} competitors, got {len(kept)}.")

    # Substring match, case-insensitive: the model may write "Twilio Segment"
    # where the case lists "Segment".
    for banned in case.get("must_not_include", []):
        for name in found:
            if banned.lower() in name.lower():
                failures.append(f"Returned '{name}', which should be excluded ({banned}).")

    wanted = case.get("should_include_any_of")
    if wanted and not any(w.lower() in n.lower() for w in wanted for n in found):
        failures.append(f"Expected at least one of {wanted}, found none.")

    failures.extend(evaluate.run_checks(kept, tools.sources_consulted()))

    metrics: dict = {}

    ratio = evaluate.primary_source_ratio(kept)
    if ratio is not None:
        print(f"    primary sources: {ratio:.0%} of citations")
        metrics["primary_source_ratio"] = ratio

    # Not gated the same way as failures above — these two are informational
    # by design (see evaluate.py), so they're tracked as metrics here too,
    # not appended to `failures`.
    if kept:
        uncorroborated = evaluate.check_source_corroboration(kept)
        corroboration_rate = 1 - (len(uncorroborated) / len(kept))
        print(f"    corroborated: {corroboration_rate:.0%} of competitors (2+ independent sources)")
        metrics["corroboration_rate"] = corroboration_rate

        precise_warnings = evaluate.check_precise_claims_are_corroborated(kept)
        if precise_warnings:
            print(f"    precise-claim warnings: {len(precise_warnings)}")
        metrics["precise_claim_warnings"] = len(precise_warnings)

    return failures, metrics


def main() -> None:
    keyword = sys.argv[1].lower() if len(sys.argv) > 1 else None
    cases = [
        c for c in CASES
        if not keyword or keyword in c["id"].lower() or keyword in c["company"].lower()
    ]

    if not cases:
        sys.exit(f"No cases matched {keyword!r}.")

    gates_passed = gates_total = 0
    notes: list[str] = []
    ratios: list[float] = []
    corroboration_rates: list[float] = []
    total_precise_warnings = 0

    for case in cases:
        informational = case.get("informational", False)
        label = "watch" if informational else "gate"
        print(f"\n=== [{label}] {case['id']} ({case['company']}) ===")

        try:
            failures, metrics = run_case(case)
        except Exception as exc:  # a crash is a failure, not a reason to stop
            failures, metrics = [f"Crashed: {type(exc).__name__}: {exc}"], {}

        if "primary_source_ratio" in metrics:
            ratios.append(metrics["primary_source_ratio"])
        if "corroboration_rate" in metrics:
            corroboration_rates.append(metrics["corroboration_rate"])
        total_precise_warnings += metrics.get("precise_claim_warnings", 0)

        if informational:
            # Reported, never fatal: this behaviour depends on live search.
            if failures:
                print("  DIFFERED from the expected behaviour:")
                for failure in failures:
                    print(f"    - {failure}")
                notes.append(f"{case['id']}: {failures[0]}")
            else:
                print("  behaved as expected")
            continue

        gates_total += 1
        if failures:
            print("  FAIL")
            for failure in failures:
                print(f"    - {failure}")
        else:
            print("  PASS")
            gates_passed += 1

    print(f"\n{gates_passed}/{gates_total} gate(s) passed.")
    if ratios:
        overall = sum(ratios) / len(ratios)
        print(f"Primary-source ratio: {overall:.0%} average across {len(ratios)} run(s).")
    if corroboration_rates:
        overall = sum(corroboration_rates) / len(corroboration_rates)
        print(f"Corroboration rate: {overall:.0%} average across {len(corroboration_rates)} run(s).")
    if total_precise_warnings:
        print(f"Precise-claim warnings: {total_precise_warnings} total across all runs.")
    if notes:
        print(f"{len(notes)} informational case(s) differed — not failures:")
        for note in notes:
            print(f"  - {note}")

    sys.exit(0 if gates_passed == gates_total else 1)


if __name__ == "__main__":
    main()
