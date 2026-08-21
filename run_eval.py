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


def run_case(case: dict) -> list[str]:
    """Run one case. Returns a list of failures — empty means it passed."""
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
        return failures

    if stopped:
        note = identity.ambiguity_note if identity else "no identity returned"
        failures.append(f"Expected a confident identification, but stopped: {note}")
        return failures

    research = pipeline.research_competitors(case["company"], identity)
    if research is None:
        failures.append("Research step returned nothing (ran out of tool calls).")
        return failures

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
    return failures


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

    for case in cases:
        informational = case.get("informational", False)
        label = "watch" if informational else "gate"
        print(f"\n=== [{label}] {case['id']} ({case['company']}) ===")

        try:
            failures = run_case(case)
        except Exception as exc:  # a crash is a failure, not a reason to stop
            failures = [f"Crashed: {type(exc).__name__}: {exc}"]

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
    if notes:
        print(f"{len(notes)} informational case(s) differed — not failures:")
        for note in notes:
            print(f"  - {note}")

    sys.exit(0 if gates_passed == gates_total else 1)


if __name__ == "__main__":
    main()
