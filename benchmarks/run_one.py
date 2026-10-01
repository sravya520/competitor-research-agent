"""One real run per mode, as a pre-benchmark smoke check.

    python -m benchmarks.run_one                      # all three modes
    python -m benchmarks.run_one firecrawl            # one mode
    python -m benchmarks.run_one --company Linear --url https://linear.app

Live by default (no cache), because the point is to prove each mode really
works end to end against the real APIs.
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from benchmarks.harness import RESEARCH_TOOL_CALL_BUDGET, run_once  # noqa: E402

MODES = ("tavily", "firecrawl", "hybrid")


def show(result) -> None:
    r = result
    print(f"\n{'=' * 62}")
    print(f"MODE: {r.mode}   company: {r.company}")
    print(f"{'=' * 62}")

    if r.error:
        print(f"  ERROR: {r.error}")

    print(f"  model                  {r.model}")
    print(f"  wall clock             {r.wall_clock_s}s")
    print(f"  identity confirmed     {r.identity_confirmed}"
          + (f"  ({r.identity_stopped_reason})" if r.identity_stopped_reason else ""))
    print(f"  competitors            {r.competitors_kept} kept / "
          f"{r.competitors_proposed} proposed", end="")
    print(f"   (pass rate {r.verification_pass_rate:.0%})"
          if r.verification_pass_rate is not None else "")
    print(f"  sources consulted      {r.sources_consulted}")
    print(f"  research tool calls    {r.research_provider_calls} "
          f"(budget {RESEARCH_TOOL_CALL_BUDGET})")
    print(f"  hit tool budget        {r.hit_tool_budget}")
    print(f"  fabrication failures   {r.fabrication_failures} "
          f"(dropped {r.fabricated_urls_dropped})")
    print(f"  uncorroborated         {r.uncorroborated_count}")
    if r.primary_source_ratio is not None:
        print(f"  primary source ratio   {r.primary_source_ratio:.0%}")

    print(f"  credits (as impl.)     {r.credits_as_implemented}")
    print(f"  credits (tavily batch) {r.credits_theoretical_tavily_batched}")
    print(f"  calls                  {r.provider_calls}")

    if r.firecrawl_credits_delta is not None:
        print(f"  firecrawl reported     {r.firecrawl_credits_delta} credits spent")
        print(f"  meter gap              {r.credit_meter_gap} "
              f"(reported minus our computed)")
    elif r.firecrawl_credits_before is not None:
        print("  firecrawl credit usage unavailable; cross-check skipped")
        print(f"    before: {r.firecrawl_credits_before}")
        print(f"    after:  {r.firecrawl_credits_after}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("modes", nargs="*", default=None,
                        help=f"any of {', '.join(MODES)}; default all")
    parser.add_argument("--company", default="Linear")
    parser.add_argument("--url", default="https://linear.app")
    parser.add_argument("--cache", action="store_true",
                        help="allow cache hits (default: live)")
    parser.add_argument("--out", default="benchmarks/results/smoke_runs.json")
    args = parser.parse_args()

    modes = args.modes or list(MODES)
    for mode in modes:
        if mode not in MODES:
            sys.exit(f"unknown mode {mode!r}; valid: {', '.join(MODES)}")

    results = []
    for mode in modes:
        result = run_once(mode, args.company, args.url, use_cache=args.cache)
        results.append(result)
        show(result)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps([r.as_dict() for r in results], indent=2), encoding="utf-8")
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
