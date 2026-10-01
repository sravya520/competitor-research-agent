"""Run the pipeline once under a chosen retrieval mode and collect metrics.

Shared by run_one.py (the per-mode smoke run) and retrieval_compare.py (the
full benchmark) so both measure identically.

Everything except retrieval is held constant across modes: same Gemini model,
same prompts, same schemas, same tool-call budget. Mode is the only variable.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone

import evaluate
import pipeline
import tools
from config import MODEL
from retrieval import (
    CreditMeter,
    FirecrawlProvider,
    FirecrawlScrapeSearchProvider,
    HybridProvider,
    ResponseCache,
    TavilyProvider,
)

# pipeline.research_competitors is configured with max_tool_calls=9. Recorded
# here so a change there shows up in results rather than silently shifting
# what "budget hit" means.
RESEARCH_TOOL_CALL_BUDGET = 9


@dataclass
class RunResult:
    mode: str
    company: str
    url: str
    model: str = MODEL
    started_at: str = ""
    wall_clock_s: float = 0.0

    identity_confirmed: bool = False
    identity_stopped_reason: str | None = None

    # Budget metric. research_competitors() returns None when the agent spends
    # its whole tool-call budget without producing a final answer, so the loop
    # ends holding a tool-call request instead of parsed output.
    research_returned_none: bool = False
    research_provider_calls: int = 0
    hit_tool_budget: bool = False

    competitors_proposed: int = 0
    competitors_kept: int = 0
    verification_pass_rate: float | None = None

    fabrication_failures: int = 0
    fabricated_urls_dropped: int = 0
    generic_name_failures: int = 0
    uncorroborated_count: int = 0
    primary_source_ratio: float | None = None

    sources_consulted: int = 0

    credits_as_implemented: float = 0.0
    credits_theoretical_tavily_batched: float = 0.0
    provider_calls: dict = field(default_factory=dict)

    # Recorded per run rather than assumed from the plan, so a result file is
    # self-describing and a changed setting cannot be mistaken for a changed
    # provider.
    truncation_settings: dict = field(default_factory=dict)
    truncation_stats: dict = field(default_factory=dict)

    # Firecrawl's own accounting, for cross-checking our computed meter.
    firecrawl_credits_before: dict | None = None
    firecrawl_credits_after: dict | None = None
    firecrawl_credits_delta: float | None = None
    credit_meter_gap: float | None = None

    error: str | None = None

    def as_dict(self) -> dict:
        return asdict(self)


def build_provider(mode: str, meter: CreditMeter, use_cache: bool):
    """Construct a provider for `mode`, sharing one meter so credits from both
    halves of hybrid land in the same counter."""
    cache = ResponseCache(enabled=use_cache)
    if mode == "tavily":
        return TavilyProvider(meter=meter, cache=cache)
    if mode == "firecrawl_bare":
        return FirecrawlProvider(meter=meter, cache=cache)
    if mode == "firecrawl_scrape":
        return FirecrawlScrapeSearchProvider(meter=meter, cache=cache)
    if mode == "hybrid":
        return HybridProvider(meter=meter, cache=cache)
    raise ValueError(f"unknown mode: {mode!r}")


def _firecrawl_half(provider):
    """The FirecrawlProvider inside `provider`, if there is one."""
    if isinstance(provider, FirecrawlProvider):
        return provider
    if isinstance(provider, HybridProvider):
        return provider.firecrawl
    return None


def _total_calls(meter: CreditMeter) -> int:
    return sum(meter.calls.values())


def run_once(mode: str, company: str, url: str = "", use_cache: bool = False,
             truncate: bool = True) -> RunResult:
    """One full pipeline run. Never raises: a crash is a result, not an abort.

    `truncate` applies the shared per-result character cap to every provider
    equally. On for benchmarks so the comparison measures retrieval rather
    than which provider returns more text; off in production.
    """
    result = RunResult(
        mode=mode, company=company, url=url,
        started_at=datetime.now(timezone.utc).isoformat(),
    )

    meter = CreditMeter()
    provider = build_provider(mode, meter, use_cache)
    fc = _firecrawl_half(provider)

    tools.reset_sources()
    tools.reset_truncation_stats()
    tools.set_truncation(truncate)
    tools.set_provider(provider)

    if fc is not None:
        result.firecrawl_credits_before = fc.live_credit_usage()

    started = time.monotonic()
    try:
        identity = pipeline.identify_company(company, url)

        if identity is None:
            result.identity_stopped_reason = "no identity returned"
        elif not identity.confident_match:
            result.identity_stopped_reason = "ambiguous"
        else:
            result.identity_confirmed = True

            calls_before_research = _total_calls(meter)
            research = pipeline.research_competitors(company, identity)
            result.research_provider_calls = _total_calls(meter) - calls_before_research

            if research is None:
                # The agent spent its budget without finishing.
                result.research_returned_none = True
                result.hit_tool_budget = True
            else:
                proposed = research.competitors
                result.competitors_proposed = len(proposed)

                verifications = pipeline.verify_competitors(company, identity, proposed)
                kept, _excluded = pipeline.apply_verifications(proposed, verifications)
                result.competitors_kept = len(kept)
                if proposed:
                    result.verification_pass_rate = len(kept) / len(proposed)

                consulted = tools.sources_consulted()
                result.fabrication_failures = len(
                    evaluate.check_sources_are_real(kept, consulted))
                result.generic_name_failures = len(
                    evaluate.check_no_generic_competitors(kept))
                result.fabricated_urls_dropped = evaluate.drop_fabricated_sources(
                    kept, consulted)
                result.uncorroborated_count = len(
                    evaluate.check_source_corroboration(kept))
                result.primary_source_ratio = evaluate.primary_source_ratio(kept)

    except Exception as exc:
        result.error = f"{type(exc).__name__}: {exc}"

    result.wall_clock_s = round(time.monotonic() - started, 2)
    result.sources_consulted = len(tools.sources_consulted())
    result.truncation_settings = tools.truncation_settings()
    result.truncation_stats = tools.truncation_stats()

    snapshot = meter.snapshot()
    result.credits_as_implemented = snapshot["as_implemented"]
    result.credits_theoretical_tavily_batched = snapshot["theoretical_tavily_batched"]
    result.provider_calls = snapshot["calls"]

    if fc is not None:
        result.firecrawl_credits_after = fc.live_credit_usage()
        before = _extract_remaining(result.firecrawl_credits_before)
        after = _extract_remaining(result.firecrawl_credits_after)
        if before is not None and after is not None:
            # Remaining credits go down as they are spent.
            result.firecrawl_credits_delta = round(before - after, 2)
            computed = sum(
                v for k, v in meter.calls.items() if k.startswith("firecrawl.")
            )
            # Compare Firecrawl's own accounting against our documented-rule
            # counter. A gap means the published rule and actual billing differ,
            # which is itself worth reporting rather than smoothing over.
            fc_computed = _firecrawl_computed_credits(meter)
            result.credit_meter_gap = round(
                result.firecrawl_credits_delta - fc_computed, 2)

    tools.set_provider(None)
    tools.set_truncation(False)  # never leave production behaviour altered
    return result


def _firecrawl_computed_credits(meter: CreditMeter) -> float:
    """Credits our meter attributes to Firecrawl specifically."""
    total = 0.0
    for key, count in meter.calls.items():
        provider, _, operation = key.partition(".")
        if provider != "firecrawl":
            continue
        total += 2.0 * count if operation == "search" else 1.0 * count
    return total


def _extract_remaining(usage: dict | None) -> float | None:
    """Pull a remaining-credits number out of whatever shape the SDK returns.

    Written defensively: this is a cross-check, so it must degrade to None
    rather than invent a number that would make the gap look clean.
    """
    if not usage or "error" in usage:
        return None
    for key in ("remaining_credits", "remainingCredits", "credits_remaining", "remaining"):
        value = usage.get(key)
        if isinstance(value, (int, float)):
            return float(value)
    return None
