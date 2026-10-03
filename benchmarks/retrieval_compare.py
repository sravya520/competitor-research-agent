"""Compare Tavily and Firecrawl as retrieval backends.

    python -m benchmarks.retrieval_compare --experiment a     # retrieval level
    python -m benchmarks.retrieval_compare --experiment b     # end to end
    python -m benchmarks.retrieval_compare --experiment all
    python -m benchmarks.retrieval_compare --report-only      # rebuild outputs

Two experiments, deliberately separate. Experiment A is deterministic: fixed
URLs, no LLM, so differences come from the fetcher. Experiment B runs the full
pipeline, where agent non-determinism is present and must not be confused with
provider quality.

Results append to results/raw_*.jsonl after every single call, so a run that
dies partway keeps everything it already paid for. Re-running skips work that
is already recorded.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import statistics as stats
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import tools  # noqa: E402
from benchmarks.harness import _extract_remaining, run_once  # noqa: E402
from config import MODEL  # noqa: E402
from retrieval import (  # noqa: E402
    CreditMeter,
    FirecrawlProvider,
    ResponseCache,
    TavilyProvider,
)

RESULTS = Path("benchmarks/results")
KEY_PATH = Path("benchmarks/answer_key.json")

# Companies for the end-to-end experiment, with the URL used to anchor
# identity. Site types are recorded so results can be segmented.
COMPANIES = [
    {"name": "Firecrawl", "url": "https://www.firecrawl.dev", "site_type": "docs/dev-tool"},
    {"name": "Nango", "url": "https://www.nango.dev", "site_type": "docs/dev-tool"},
    {"name": "Composio", "url": "https://composio.dev", "site_type": "docs/dev-tool"},
    {"name": "Mobbin", "url": "https://mobbin.com", "site_type": "js-app"},
    {"name": "Brickanta", "url": "https://brickanta.com", "site_type": "startup-marketing"},
    {"name": "Dataleap", "url": "https://dataleap.ai", "site_type": "startup-marketing"},
    {"name": "Manufact", "url": "https://manufact.com", "site_type": "startup-marketing"},
    {"name": "Arcade.dev", "url": "https://www.arcade.dev", "site_type": "docs/dev-tool"},
    {"name": "Notion", "url": "https://www.notion.com", "site_type": "saas-marketing"},
    {"name": "Linear", "url": "https://linear.app", "site_type": "saas-marketing"},
]

MODE_RUNS = {
    "tavily": 2,
    "hybrid": 2,
    "firecrawl_scrape": 2,
    "firecrawl_bare": 1,
}

# Agreed: bare search is run on a 5-company subset covering mixed site types,
# since its purpose is to characterise a configuration, not to rank companies.
BARE_SUBSET = {"Mobbin", "Notion", "Firecrawl", "Brickanta", "Linear"}

# Excluded from firecrawl_scrape for budget, not for data. The first attempt's
# runs were lost to the LLM's daily quota and redoing all of them would have
# spent into the Firecrawl credit reserve. Linear was chosen because tavily and
# hybrid already cover it and it is the least differentiating of the remaining
# sites. This is a deliberate hole in the sample and the limitations say so:
# firecrawl_scrape is measured on fewer companies than tavily and hybrid.
SCRAPE_EXCLUDED = {"Linear"}

# Never spend below this many Firecrawl credits. The run stops before the job
# that would cross it, so the reserve is still intact when it stops.
CREDIT_RESERVE = 100

# Median Firecrawl credits per run, measured from the first attempt's clean runs.
# firecrawl_bare had no clean run to measure, so its figure is a deliberately
# generous estimate: over-estimating stops the run early, which is the safe
# direction, while under-estimating would spend into the reserve.
ESTIMATED_FIRECRAWL_CREDITS = {
    "tavily": 0.0,
    "hybrid": 8.0,
    "firecrawl_scrape": 35.0,
    "firecrawl_bare": 20.0,
}

# Boilerplate heuristic. Stated explicitly because this is the most arguable
# metric in the set: it is a heuristic, not a measurement, and the write-up
# says so. A line counts as boilerplate when it is navigation chrome, a cookie
# or subscribe prompt, or is nothing but links.
_BOILERPLATE_PATTERNS = re.compile(
    r"cookie|subscribe|newsletter|sign in|sign up|log in|privacy policy|"
    r"terms of service|all rights reserved|skip to (main )?content|"
    r"^\s*(home|pricing|docs|blog|about|contact|careers|login)\s*$",
    re.IGNORECASE,
)
_LINK_ONLY = re.compile(r"^\s*[\[\|\-\*\s]*(\[[^\]]*\]\([^)]*\)[\s\|\-\*]*)+$")


def boilerplate_share(text: str) -> float | None:
    """Fraction of non-empty lines that look like chrome rather than content."""
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines:
        return None
    noise = sum(
        1 for ln in lines
        if _BOILERPLATE_PATTERNS.search(ln) or _LINK_ONLY.match(ln)
    )
    return noise / len(lines)


def load_key() -> dict:
    return json.loads(KEY_PATH.read_text(encoding="utf-8"))


def _normalise(text: str) -> str:
    """Collapse all whitespace so matching compares words, not formatting.

    Found during the first run: Firecrawl scored 0/1 on dataleap.ai for a
    tagline its content plainly contained, because the markdown broke the
    phrase across lines while Tavily's did not. A raw substring check was
    therefore scoring line-breaking style rather than retrieval, and
    systematically penalising whichever provider wrapped text differently.
    """
    return re.sub(r"\s+", " ", text).lower()


def fact_present(fact: dict, content: str) -> bool:
    """Whitespace-insensitive, case-insensitive substring matching."""
    haystack = _normalise(content)
    terms = [_normalise(t) for t in fact["terms"]]
    if fact["match"] == "all":
        return all(t in haystack for t in terms)
    return any(t in haystack for t in terms)


def append_jsonl(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record) + "\n")


def is_quota_failure(row: dict) -> bool:
    """Did the LLM provider's quota end this run?

    Such a run tells us nothing about the retrieval mode under test, so it is
    excluded from end-to-end aggregates. Matching on the provider's own status
    string rather than on an HTTP code, because a 429 from a retrieval provider
    IS a result about that provider and must keep counting.
    """
    error = row.get("error") or ""
    return "RESOURCE_EXHAUSTED" in error or "generate_content_free_tier" in error


def read_jsonl(path: Path) -> list[dict]:
    """Read a results file, tolerating a torn final line.

    These files are appended to while a run is in progress, so reporting can
    catch the last line mid-write. Skipping it is right; a report that refuses
    to build is worse than one missing the row still being written.
    """
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            print(f"[warn] skipping unparseable line in {path.name}")
    return rows


# --------------------------------------------------------------------------
# Experiment A — retrieval level, deterministic
# --------------------------------------------------------------------------

CONTENT_DIR = Path(__file__).resolve().parent / "cache" / "experiment_a_content"


def _content_path(fetcher: str, run: int, url: str) -> Path:
    digest = hashlib.sha256(url.encode()).hexdigest()[:16]
    return CONTENT_DIR / f"{fetcher}_run{run}_{digest}.txt"


def save_content(fetcher: str, run: int, url: str, content: str) -> None:
    """Keep exactly what the fetcher returned, so scoring can be redone later.

    Scoring is the part most likely to need a fix; fetching is the part that
    costs credits. Separating them means a scorer bug costs nothing to correct.
    """
    CONTENT_DIR.mkdir(parents=True, exist_ok=True)
    path = _content_path(fetcher, run, url)
    path.write_text(f"{url}\n{'=' * 70}\n{content}", encoding="utf-8")


def load_content(fetcher: str, run: int, url: str) -> str | None:
    path = _content_path(fetcher, run, url)
    if not path.exists():
        return None
    text = path.read_text(encoding="utf-8")
    _, _, body = text.partition("=" * 70 + "\n")
    return body


def rescore() -> None:
    """Recompute fact hits from saved content. No network, no credits.

    Rewrites raw_retrieval.jsonl in place. Rows whose content was not saved are
    left untouched and reported, rather than silently scored as zero.
    """
    out = RESULTS / "raw_retrieval.jsonl"
    rows = read_jsonl(out)
    key = load_key()
    facts_by_page = defaultdict(list)
    for fact in key["facts"]:
        facts_by_page[fact["page"]].append(fact)

    changed = missing = 0
    for row in rows:
        content = load_content(row["fetcher"], row["run"], row["url"])
        if content is None:
            missing += 1
            continue
        facts = facts_by_page[row["url"]]
        found = [f for f in facts if row["ok"] and fact_present(f, content)]
        missed = [f for f in facts if f not in found]
        before = row.get("facts_found")
        row["facts_found"] = len(found)
        row["facts_found_names"] = [f["fact"] for f in found]
        row["facts_missed_names"] = [f["fact"] for f in missed]
        row["content_chars"] = len(content)
        row["rescored"] = True
        if before != len(found):
            changed += 1

    with out.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row) + "\n")

    print(f"rescored {len(rows) - missing}/{len(rows)} rows, "
          f"{changed} changed, {missing} had no saved content")


def experiment_a(runs: int = 2) -> None:
    """Fetch every answer-key page with each fetcher and score it.

    No LLM involved, so any difference is the fetcher's.
    """
    out = RESULTS / "raw_retrieval.jsonl"
    done = {(r["fetcher"], r["url"], r["run"]) for r in read_jsonl(out)}

    key = load_key()
    pages = sorted({f["page"] for f in key["facts"]})
    facts_by_page = defaultdict(list)
    for fact in key["facts"]:
        facts_by_page[fact["page"]].append(fact)

    meter = CreditMeter()
    # Fetches stay live. The response cache keys on provider+operation+url with
    # no run number, so enabling it would serve run 2 the bytes from run 1 and
    # the second run would stop measuring run-to-run variance.
    #
    # Instead each fetch's content is written to disk by save_content() below.
    # That is what makes re-scoring free: the first version of this ran with no
    # content saved, a whitespace bug was found in fact matching, and fixing it
    # meant paying to re-fetch all 80 pages. `--rescore` now replays the saved
    # content through the scorer without touching the network.
    # Three arms. tavily is the as-deployed baseline on basic extract.
    # tavily_advanced is here because Firecrawl's scrape is its full-fidelity
    # product while basic extract is Tavily's cheap tier: without this arm the
    # comparison would credit Firecrawl for a difference in tier rather than in
    # capability. It costs double, so it is reported separately and never folded
    # into the as-deployed baseline.
    fetchers = {
        "tavily": TavilyProvider(meter=meter, cache=ResponseCache(enabled=False)),
        "tavily_advanced": TavilyProvider(
            meter=meter, cache=ResponseCache(enabled=False),
            extract_depth="advanced"),
        "firecrawl": FirecrawlProvider(meter=meter, cache=ResponseCache(enabled=False)),
    }

    total = len(pages) * len(fetchers) * runs
    step = 0
    for run in range(1, runs + 1):
        for name, fetcher in fetchers.items():
            for url in pages:
                step += 1
                if (name, url, run) in done:
                    print(f"[A {step}/{total}] skip (done) {name} {url}")
                    continue
                print(f"[A {step}/{total}] {name} run{run} {url}", flush=True)

                doc = fetcher.fetch(url)
                save_content(name, run, url, doc.content)
                facts = facts_by_page[url]
                found = [f for f in facts if doc.ok and fact_present(f, doc.content)]
                missed = [f for f in facts if f not in found]

                append_jsonl(out, {
                    "experiment": "A",
                    "fetcher": name,
                    "run": run,
                    "url": url,
                    "ok": doc.ok,
                    "error": doc.error,
                    "latency_ms": doc.latency_ms,
                    "content_chars": len(doc.content),
                    "boilerplate_share": boilerplate_share(doc.content),
                    "facts_total": len(facts),
                    "facts_found": len(found),
                    "facts_found_names": [f["fact"] for f in found],
                    # Recorded so a miss can be investigated later without
                    # re-reading the key and re-deriving which fact failed.
                    "facts_missed_names": [f["fact"] for f in missed],
                    "only_main_content": getattr(fetcher, "only_main_content", None),
                    "fetched_at": datetime.now(timezone.utc).isoformat(),
                })

    print(f"\nExperiment A credits: {meter.snapshot()}")


def refetch_failed(attempts: int = 4) -> None:
    """Re-fetch only the rows that failed, then re-score.

    Exists because of a self-inflicted result: Experiment A was run while the
    end-to-end benchmark was also hitting Firecrawl, and _throttle only paces
    one process. The account's 10 req/min was exceeded across both, so two
    pages came back as 429s. Those are an artefact of how the benchmark was
    run, not a property of the provider, and reporting them as provider
    reliability would be wrong.

    Run this when no other benchmark process is active.
    """
    out = RESULTS / "raw_retrieval.jsonl"
    rows = read_jsonl(out)
    failed = [r for r in rows if not r["ok"]]
    if not failed:
        print("no failed rows")
        return

    meter = CreditMeter()
    fetchers = {
        "tavily": TavilyProvider(meter=meter, cache=ResponseCache(enabled=False)),
        "tavily_advanced": TavilyProvider(
            meter=meter, cache=ResponseCache(enabled=False),
            extract_depth="advanced"),
        "firecrawl": FirecrawlProvider(meter=meter, cache=ResponseCache(enabled=False)),
    }

    print(f"re-fetching {len(failed)} failed row(s)")
    for row in failed:
        fetcher = fetchers[row["fetcher"]]
        for attempt in range(1, attempts + 1):
            doc = fetcher.fetch(row["url"])
            if doc.ok:
                break
            print(f"  attempt {attempt} failed: {str(doc.error)[:90]}")
            if attempt < attempts:
                time.sleep(20 * attempt)
        if not doc.ok:
            print(f"  GAVE UP {row['fetcher']} run{row['run']} {row['url']}")
            continue
        save_content(row["fetcher"], row["run"], row["url"], doc.content)
        row["ok"] = True
        row["error"] = None
        row["latency_ms"] = doc.latency_ms
        row["content_chars"] = len(doc.content)
        row["boilerplate_share"] = boilerplate_share(doc.content)
        row["refetched"] = True
        print(f"  ok {row['fetcher']} run{row['run']} {row['url']} "
              f"({len(doc.content):,} chars)")

    with out.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row) + "\n")
    print(f"refetch credits: {meter.snapshot()}")
    rescore()


def ablation_main_content(sample: int = 3, pages: list[str] | None = None) -> None:
    """only_main_content on vs off.

    The setting materially changes the boilerplate metric, so its effect is
    measured rather than asserted.

    Scored facts are recorded per page as well as boilerplate. Measuring only
    boilerplate would record the setting's benefit and not its cost: filtering
    removes navigation, and on notion.com the navigation is where the product
    names actually are. Both sides have to be in the same row or the trade-off
    cannot be stated honestly.
    """
    out = RESULTS / "raw_ablation.jsonl"
    done = {(r["url"], r["only_main_content"]) for r in read_jsonl(out)}

    key = load_key()
    facts_by_page = defaultdict(list)
    for fact in key["facts"]:
        facts_by_page[fact["page"]].append(fact)

    if pages is None:
        pages = sorted(facts_by_page)[:sample]
    meter = CreditMeter()

    for url in pages:
        for flag in (True, False):
            if (url, flag) in done:
                print(f"[ablation] skip {url} main_content={flag}")
                continue
            provider = FirecrawlProvider(meter=meter, cache=ResponseCache(enabled=False))
            provider.only_main_content = flag
            print(f"[ablation] {url} only_main_content={flag}", flush=True)
            doc = provider.fetch(url)
            save_content(f"ablation_main{flag}", 1, url, doc.content)
            facts = facts_by_page[url]
            found = [f for f in facts if doc.ok and fact_present(f, doc.content)]
            missed = [f for f in facts if f not in found]
            append_jsonl(out, {
                "experiment": "ablation",
                "url": url,
                "only_main_content": flag,
                "ok": doc.ok,
                "content_chars": len(doc.content),
                "boilerplate_share": boilerplate_share(doc.content),
                "latency_ms": doc.latency_ms,
                "facts_total": len(facts),
                "facts_found": len(found),
                "facts_found_names": [f["fact"] for f in found],
                "facts_missed_names": [f["fact"] for f in missed],
            })

    print(f"\nAblation credits: {meter.snapshot()}")


# --------------------------------------------------------------------------
# Experiment B — end to end
# --------------------------------------------------------------------------

def _llm_available() -> tuple[bool, str]:
    """One cheap generation, to fail fast if the LLM's quota is still spent.

    Without this the benchmark starts work, spends a Firecrawl credit per run
    on retrieval, and only then discovers every run dies at the first LLM call.
    The first attempt lost 17 runs that way.
    """
    try:
        from config import MODEL, gemini_client
        gemini_client.models.generate_content(model=MODEL, contents="ok")
        return True, "available"
    except Exception as exc:  # noqa: BLE001 - any failure here means do not start
        message = str(exc)
        if "PerDay" in message:
            return False, "daily quota still exhausted"
        if "RESOURCE_EXHAUSTED" in message:
            return False, "rate limited (per-minute); retry shortly"
        return False, f"{type(exc).__name__}: {message[:120]}"


def _firecrawl_remaining() -> float | None:
    """Firecrawl's own remaining-credit figure, or None if it cannot be read."""
    try:
        from retrieval import FirecrawlProvider
        return _extract_remaining(FirecrawlProvider().live_credit_usage())
    except Exception as exc:  # noqa: BLE001 - a failed read must not crash the run
        print(f"[B] credit read failed: {type(exc).__name__}: {exc}")
        return None


def experiment_b() -> None:
    out = RESULTS / "raw_endtoend.jsonl"
    # A run the LLM's quota killed does not count as done, or resuming would
    # skip exactly the runs that need redoing. The failed row stays in the file
    # as evidence; the report excludes it and counts it as excluded.
    done = {(r["mode"], r["company"], r["run"]) for r in read_jsonl(out)
            if not is_quota_failure(r)}

    per_mode = {}
    for mode, run_count in MODE_RUNS.items():
        mode_jobs = []
        for company in COMPANIES:
            if mode == "firecrawl_bare" and company["name"] not in BARE_SUBSET:
                continue
            if mode == "firecrawl_scrape" and company["name"] in SCRAPE_EXCLUDED:
                continue
            for run in range(1, run_count + 1):
                mode_jobs.append((mode, company, run))
        per_mode[mode] = mode_jobs

    # Interleave the modes instead of finishing one before starting the next.
    # Grouping by mode meant the LLM's daily quota ran out partway through the
    # schedule and destroyed whichever modes happened to be last: firecrawl_bare
    # lost all 5 of its runs and firecrawl_scrape lost 12 of 20, while tavily and
    # hybrid, which ran first, were almost untouched. Round-robin spreads any
    # mid-run exhaustion across every mode, so a partial run still yields a
    # comparable sample for each rather than complete data for some and none for
    # others.
    jobs = []
    for tier in range(max(len(j) for j in per_mode.values())):
        for mode in MODE_RUNS:
            if tier < len(per_mode[mode]):
                jobs.append(per_mode[mode][tier])

    # Credit floor. The run stops rather than spending into the reserve, and it
    # stops BEFORE the run that would cross it, not after. Estimates are the
    # measured medians per mode from the first attempt; firecrawl_bare has no
    # clean run to measure, so its figure is deliberately generous.
    ok, why = _llm_available()
    if not ok:
        print(f"[B] not starting: LLM {why}. No credits spent.")
        return
    print(f"[B] LLM {why}")

    remaining = _firecrawl_remaining()
    if remaining is not None:
        print(f"[B] Firecrawl credits remaining: {remaining:.0f} "
              f"(floor {CREDIT_RESERVE})")
    else:
        print("[B] could not read Firecrawl credits; the floor cannot be "
              "enforced, so stopping rather than spending blind")
        return

    for index, (mode, company, run) in enumerate(jobs, 1):
        tag = (mode, company["name"], run)
        if tag in done:
            print(f"[B {index}/{len(jobs)}] skip (done) {mode} {company['name']} run{run}")
            continue

        cost = ESTIMATED_FIRECRAWL_CREDITS.get(mode, 0.0)
        if cost and remaining - cost < CREDIT_RESERVE:
            print(f"\n[B] STOPPING at job {index}/{len(jobs)}. "
                  f"{mode} needs about {cost:.0f} credits, {remaining:.0f} remain, "
                  f"and spending it would leave less than the {CREDIT_RESERVE} "
                  f"credit reserve. Completed work is saved; rerun to resume.")
            return

        print(f"[B {index}/{len(jobs)}] {mode} {company['name']} run{run}", flush=True)
        result = run_once(mode, company["name"], company["url"],
                          use_cache=False, truncate=True)

        # Prefer Firecrawl's own figure. Failing that, deduct the estimate
        # rather than a call count, which would understate the spend because a
        # search costs more than one credit.
        reported = _extract_remaining(result.firecrawl_credits_after)
        remaining = reported if reported is not None else remaining - cost
        record = result.as_dict()
        record["experiment"] = "B"
        record["run"] = run
        record["site_type"] = company["site_type"]
        append_jsonl(out, record)


# --------------------------------------------------------------------------
# Reporting
# --------------------------------------------------------------------------

def _p95(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, int(round(0.95 * (len(ordered) - 1))))
    return ordered[index]


def _safe_median(values):
    return stats.median(values) if values else None


# Firecrawl's published rates, keyed by the meter's provider.operation label.
# search_scrape is 2 credits for the search plus 1 per scraped result, and the
# benchmark scrapes 3 results per search.
FIRECRAWL_RATES = {
    "firecrawl.search": 2.0,
    "firecrawl.fetch": 1.0,
    "firecrawl_scrape.search": 5.0,
    "firecrawl_scrape.search_scrape": 5.0,
    "firecrawl_scrape.fetch": 1.0,
}


def _firecrawl_credits_from_calls(row: dict) -> float:
    """What our accounting says a run spent with Firecrawl.

    For the Firecrawl-only modes this is the meter's own figure, which charges
    2 credits per search plus 1 per result actually returned. The flat rate
    below is only a fallback for hybrid, whose rows mix both vendors and
    predate per-provider credit tracking; it assumes 3 results per search and
    so slightly over-charges a search that returned fewer.
    """
    if row.get("mode", "").startswith("firecrawl"):
        return row.get("credits_as_implemented", 0.0)
    return sum(FIRECRAWL_RATES.get(key, 0.0) * count
               for key, count in (row.get("provider_calls") or {}).items())


def build_report() -> None:
    RESULTS.mkdir(parents=True, exist_ok=True)
    a_rows = read_jsonl(RESULTS / "raw_retrieval.jsonl")
    b_rows = read_jsonl(RESULTS / "raw_endtoend.jsonl")
    abl_rows = read_jsonl(RESULTS / "raw_ablation.jsonl")

    summary: dict = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "model": MODEL,
        "answer_key": {
            "path": str(KEY_PATH),
            "scored_facts": len(load_key()["facts"]) if KEY_PATH.exists() else None,
        },
        "experiment_a": {},
        "experiment_b": {},
        "ablation": {},
    }

    # --- A ---
    by_fetcher = defaultdict(list)
    for row in a_rows:
        by_fetcher[row["fetcher"]].append(row)

    for fetcher, rows in by_fetcher.items():
        ok_rows = [r for r in rows if r["ok"]]
        latencies = [r["latency_ms"] for r in ok_rows]
        boiler = [r["boilerplate_share"] for r in ok_rows if r["boilerplate_share"] is not None]
        summary["experiment_a"][fetcher] = {
            "attempts": len(rows),
            "success_rate": len(ok_rows) / len(rows) if rows else None,
            "latency_ms_median": _safe_median(latencies),
            "latency_ms_p95": _p95(latencies),
            "content_chars_median": _safe_median([r["content_chars"] for r in ok_rows]),
            "boilerplate_share_median": _safe_median(boiler),
            "facts_found": sum(r["facts_found"] for r in rows),
            "facts_total": sum(r["facts_total"] for r in rows),
            "key_fact_recall": (
                sum(r["facts_found"] for r in rows) / sum(r["facts_total"] for r in rows)
                if sum(r["facts_total"] for r in rows) else None
            ),
            "failures": [
                {"url": r["url"], "error": r["error"]} for r in rows if not r["ok"]
            ],
        }

    # --- B ---
    by_mode = defaultdict(list)
    for row in b_rows:
        by_mode[row["mode"]].append(row)

    for mode, all_rows in sorted(by_mode.items()):
        # A run killed by the LLM provider's quota measured the quota, not the
        # retrieval mode, so it is excluded rather than averaged in. This is not
        # cosmetic: the Firecrawl modes ran last and absorbed the exhausted
        # Gemini daily quota, which made firecrawl_scrape look like it kept 0
        # competitors when its clean runs keep as many as Tavily. Tavily's own
        # median was depressed by four such runs. The count is reported so an
        # excluded run is visible rather than quietly dropped.
        excluded = [r for r in all_rows if is_quota_failure(r)]
        rows = [r for r in all_rows if not is_quota_failure(r)]
        if not rows:
            summary["experiment_b"][mode] = {
                "runs": 0,
                "runs_attempted": len(all_rows),
                "excluded_llm_quota": len(excluded),
                "note": "every run was killed by the LLM provider's quota; no data",
            }
            continue

        finished = [r for r in rows if not r["hit_tool_budget"] and not r["error"]]
        pass_rates = [r["verification_pass_rate"] for r in rows
                      if r["verification_pass_rate"] is not None]
        psr = [r["primary_source_ratio"] for r in rows
               if r.get("primary_source_ratio") is not None]
        search_shares = [
            r["truncation_stats"].get("search_truncated_share")
            for r in rows
            if r.get("truncation_stats", {}).get("search_truncated_share") is not None
        ]
        page_shares = [
            r["truncation_stats"].get("pages_truncated_share")
            for r in rows
            if r.get("truncation_stats", {}).get("pages_truncated_share") is not None
        ]
        # Recomputed here rather than read from the row. Rows recorded before
        # the credit-attribution fix stored a gap that was the whole Firecrawl
        # spend instead of a discrepancy, so trusting the stored value would
        # publish a 67-credit "gap" that never existed. Deriving it from the
        # call counts and the documented rates gives the same answer for every
        # row regardless of when it was recorded.
        gaps = [r["firecrawl_credits_delta"] - _firecrawl_credits_from_calls(r)
                for r in rows if r.get("firecrawl_credits_delta") is not None]

        summary["experiment_b"][mode] = {
            "runs": len(rows),
            "runs_attempted": len(all_rows),
            "excluded_llm_quota": len(excluded),
            "errors": sum(1 for r in rows if r["error"]),
            "identity_confirmed_rate": sum(r["identity_confirmed"] for r in rows) / len(rows),
            "budget_hit_rate": sum(r["hit_tool_budget"] for r in rows) / len(rows),
            "completed_rate": len(finished) / len(rows),
            "competitors_proposed_median": _safe_median([r["competitors_proposed"] for r in rows]),
            "competitors_kept_median": _safe_median([r["competitors_kept"] for r in rows]),
            "verification_pass_rate_mean": (
                sum(pass_rates) / len(pass_rates) if pass_rates else None),
            "fabrication_failures_total": sum(r["fabrication_failures"] for r in rows),
            "fabricated_urls_dropped_total": sum(r["fabricated_urls_dropped"] for r in rows),
            "primary_source_ratio_mean": sum(psr) / len(psr) if psr else None,
            "wall_clock_s_median": _safe_median([r["wall_clock_s"] for r in rows]),
            "credits_as_implemented_total": round(
                sum(r["credits_as_implemented"] for r in rows), 2),
            "credits_tavily_batched_total": round(
                sum(r["credits_theoretical_tavily_batched"] for r in rows), 2),
            "search_truncated_share_mean": (
                sum(search_shares) / len(search_shares) if search_shares else None),
            "pages_truncated_share_mean": (
                sum(page_shares) / len(page_shares) if page_shares else None),
            "credit_meter_gap_max": max(gaps, key=abs) if gaps else None,
        }

    # --- ablation ---
    for flag in (True, False):
        rows = [r for r in abl_rows if r["only_main_content"] is flag]
        if rows:
            summary["ablation"][f"only_main_content={flag}"] = {
                "pages": len(rows),
                "content_chars_median": _safe_median([r["content_chars"] for r in rows]),
                "boilerplate_share_median": _safe_median(
                    [r["boilerplate_share"] for r in rows if r["boilerplate_share"] is not None]),
            }

    (RESULTS / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    _write_csv(a_rows, b_rows)
    _write_markdown(summary, a_rows, b_rows, abl_rows)
    print(f"wrote {RESULTS}/summary.json, summary.md, retrieval.csv, endtoend.csv")


def _write_csv(a_rows: list[dict], b_rows: list[dict]) -> None:
    if a_rows:
        with (RESULTS / "retrieval.csv").open("w", newline="", encoding="utf-8") as fh:
            cols = ["fetcher", "run", "url", "ok", "latency_ms", "content_chars",
                    "boilerplate_share", "facts_found", "facts_total", "error"]
            writer = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(a_rows)

    if b_rows:
        with (RESULTS / "endtoend.csv").open("w", newline="", encoding="utf-8") as fh:
            cols = ["mode", "company", "site_type", "run", "identity_confirmed",
                    "hit_tool_budget", "research_provider_calls", "competitors_proposed",
                    "competitors_kept", "verification_pass_rate", "fabrication_failures",
                    "primary_source_ratio", "wall_clock_s", "credits_as_implemented",
                    "credits_theoretical_tavily_batched", "credit_meter_gap", "error"]
            writer = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(b_rows)


def _fmt(value, pct=False, digits=2):
    if value is None:
        return "n/a"
    if pct:
        return f"{value:.0%}"
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    return str(value)


def _write_markdown(summary: dict, a_rows: list[dict], b_rows: list[dict],
                    abl_rows: list[dict]) -> None:
    lines = [
        "# Tavily vs Firecrawl — benchmark results",
        "",
        f"Generated {summary['generated_at']}",
        f"Model held constant across all modes: `{summary['model']}`",
        f"Answer key: {summary['answer_key']['scored_facts']} facts, "
        f"independently verified (see `docs/ANSWER_KEY_CHECKLIST.md`)",
        "",
        "## Experiment A — retrieval level (no LLM)",
        "",
        "| fetcher | success | latency p50 | latency p95 | content chars | boilerplate | key-fact recall |",
        "|---|---|---|---|---|---|---|",
    ]
    for fetcher, s in summary["experiment_a"].items():
        lines.append(
            f"| {fetcher} | {_fmt(s['success_rate'], pct=True)} "
            f"| {_fmt(s['latency_ms_median'], digits=0)}ms "
            f"| {_fmt(s['latency_ms_p95'], digits=0)}ms "
            f"| {_fmt(s['content_chars_median'], digits=0)} "
            f"| {_fmt(s['boilerplate_share_median'], pct=True)} "
            f"| {_fmt(s['key_fact_recall'], pct=True)} "
            f"({s['facts_found']}/{s['facts_total']}) |"
        )

    lines += ["", "## Experiment B — end to end", "",
              "| mode | runs scored | excluded (LLM quota) | budget hit | completed "
              "| kept (median) | verif. pass | citations rejected | time p50 | credits |",
              "|---|---|---|---|---|---|---|---|---|---|"]
    for mode, s in summary["experiment_b"].items():
        if not s["runs"]:
            lines.append(
                f"| {mode} | 0 | {s['excluded_llm_quota']} of {s['runs_attempted']} "
                f"| n/a | n/a | n/a | n/a | n/a | n/a | n/a |")
            continue
        lines.append(
            f"| {mode} | {s['runs']} "
            f"| {s['excluded_llm_quota']} of {s['runs_attempted']} "
            f"| {_fmt(s['budget_hit_rate'], pct=True)} "
            f"| {_fmt(s['completed_rate'], pct=True)} "
            f"| {_fmt(s['competitors_kept_median'], digits=1)} "
            f"| {_fmt(s['verification_pass_rate_mean'], pct=True)} "
            f"| {s['fabrication_failures_total']} "
            f"| {_fmt(s['wall_clock_s_median'], digits=1)}s "
            f"| {_fmt(s['credits_as_implemented_total'], digits=1)} |"
        )

    lines += [
        "",
        "**Citations rejected** counts source URLs the fabrication check "
        "refused: a deterministic test that every cited URL appears in the "
        "ledger of pages our own code actually fetched. It is set membership, "
        "not a judgement, so it rejects every citation that is not in the "
        "ledger. In both entry points (`main.py`, `app.py`) the rejected "
        "citations are stripped before the report is built and before "
        "corroboration is checked, so 100% of them were caught and none "
        "reached a final report. The check cannot detect a citation whose URL "
        "*was* fetched but is described wrongly; corroboration and the "
        "precise-claims check cover that separately.",
        "",
        "### Credits, both ways", "",
              "| mode | as implemented | with Tavily batching |", "|---|---|---|"]
    for mode, s in summary["experiment_b"].items():
        if not s["runs"]:
            lines.append(f"| {mode} | n/a | n/a |")
            continue
        lines.append(
            f"| {mode} | {_fmt(s['credits_as_implemented_total'], digits=1)} "
            f"| {_fmt(s['credits_tavily_batched_total'], digits=1)} |")

    lines += ["", "### Truncation (1,500 search / 25,000 page)", "",
              "| mode | search results truncated | pages truncated |", "|---|---|---|"]
    for mode, s in summary["experiment_b"].items():
        if not s["runs"]:
            lines.append(f"| {mode} | n/a | n/a |")
            continue
        lines.append(
            f"| {mode} | {_fmt(s['search_truncated_share_mean'], pct=True)} "
            f"| {_fmt(s['pages_truncated_share_mean'], pct=True)} |")

    if summary["ablation"]:
        lines += ["", "## Ablation — only_main_content", "",
                  "| setting | pages | content chars | boilerplate |", "|---|---|---|---|"]
        for setting, s in summary["ablation"].items():
            lines.append(
                f"| {setting} | {s['pages']} "
                f"| {_fmt(s['content_chars_median'], digits=0)} "
                f"| {_fmt(s['boilerplate_share_median'], pct=True)} |")

        # Per page as well as aggregated. The aggregate shows only that
        # filtering cuts boilerplate; it hides that on one page the filtering
        # removed a scored fact. Both directions belong in the report.
        per_page = defaultdict(dict)
        for row in abl_rows:
            per_page[row["url"]][row["only_main_content"]] = row
        caption = ("Per page, with the scored facts each setting retrieves. "
                   "Filtering is free on most pages and expensive on one: it "
                   "costs no facts on three of these four while cutting "
                   "boilerplate, and on notion.com it removes the navigation "
                   "where the product names are.")
        if any("facts_total" not in r for r in abl_rows):
            caption += (" Rows marked not scored predate fact scoring in the "
                        "ablation and were not re-fetched.")
        lines += ["", caption, "",
                  "| page | setting | chars | boilerplate | facts |",
                  "|---|---|---|---|---|"]
        for url in sorted(per_page):
            for flag in (True, False):
                row = per_page[url].get(flag)
                if not row:
                    continue
                if row.get("facts_total"):
                    facts = f"{row['facts_found']}/{row['facts_total']}"
                else:
                    facts = "not scored"
                lines.append(
                    f"| {url} | `{flag}` | {row['content_chars']:,} "
                    f"| {_fmt(row['boilerplate_share'], pct=True)} | {facts} |")

    lines += [
        "",
        "## Limitations",
        "",
        "- **n = 10 companies**, 1-2 runs per mode. This is a directional "
        "comparison, not a result with error bars. No significance is claimed.",
        "- **The modes do not all cover the same companies.** firecrawl_scrape "
        "excludes Linear and firecrawl_bare runs on a 5-company subset, so "
        "their samples are smaller than tavily's and hybrid's. Linear was "
        "dropped to stay above the Firecrawl credit reserve after the first "
        "attempt's runs were lost to the LLM quota. That is a budget decision, "
        "not a data one, and it means per-mode figures are not strictly "
        "like-for-like across the same company set.",
        "- **The end-to-end runs span two days.** Gemini's free tier allows 500 "
        "requests a day, which is fewer than one full pass needs, so the modes "
        "were completed across two calendar days. Sites may have changed between "
        "them. Experiment A, which is the controlled retrieval comparison, ran "
        "within a single day.",
        "- **Answer key wording was corrected post-hoc**, before the final "
        "end-to-end run, and every change is logged with its evidence in "
        "`docs/ANSWER_KEY_CHANGES.md`. One fact was corrected from a paraphrase "
        "to the page's literal text; one proposed removal was rejected because "
        "the plain-HTTP check disproved the reason for it.",
        "- **firecrawl_bare's result could not be fully reconciled with the "
        "earlier single run.** The Phase 1 run on Linear exhausted all 9 "
        "research tool calls and returned nothing; the final run on the same "
        "company used 7 calls and kept 5. The failure was budget exhaustion, "
        "not missing sources: the failed run consulted 36 sources against the "
        "successful run's 25. Three candidate causes could not be separated "
        "without a further run, which was out of scope: the per-result "
        "character cap was off in Phase 1 and on afterwards, which shortens "
        "context and can change tool-call behaviour; the margin is thin, with "
        "one final run using 8 of 9 calls, and agent tool sequences are "
        "non-deterministic; and the two runs were two days apart. The earlier "
        "note that bare search returns uniformly short snippets does not hold "
        "either: 16% of its search results on Linear and 40% on Notion "
        "exceeded the 1,500-character cap. Read firecrawl_bare as 5 runs on 5 "
        "companies, one run each, not as a settled result.",
        "- **Credit costs come from each vendor's published pricing, not from "
        "measured billing.** Tavily's extract endpoint reported "
        "`usage.credits: 0` on both basic and advanced depth, so its per-call "
        "cost here is the documented rate rather than an observed charge. "
        "Firecrawl's figures were cross-checked against its own "
        "`get_credit_usage()` and the gap is reported per run. On the "
        "Firecrawl-only modes our accounting lands within about 2% of "
        "Firecrawl's own: 630 computed against 619 billed for "
        "firecrawl_scrape, 69 against 67 for firecrawl_bare. Hybrid's 40 "
        "computed against 58 billed is a real under-count: its 40 page "
        "scrapes averaged 1.45 credits each rather than the base 1, so some "
        "pages bill above the base rate. The documented base rate is "
        "therefore a floor, not a prediction, and a plan sized on it will "
        "under-budget for sites that need costlier scraping. The worst single "
        "run shows a 29-credit gap; it ran while another of our own processes "
        "was also calling Firecrawl, and the before/after reading is "
        "account-wide so it cannot isolate one process. The other 17 runs fall "
        "between -7 and 0, as do all 10 runs executed with no concurrent use.",
        "- **We scrape firecrawl.dev using Firecrawl.** The vendor is both a "
        "benchmark subject and the audience for this write-up.",
        "- **Runs killed by the LLM provider's daily quota are excluded**, and "
        "the count is shown per mode. Gemini's free tier allows 500 requests a "
        "day; the first attempt ran the modes in sequence, so exhaustion landed "
        "entirely on whichever modes were scheduled last. Modes are now "
        "interleaved. Any mode whose scored-run count is below its attempted "
        "count is a smaller sample than the others and should be read as such.",
        "- **Boilerplate share is a heuristic**, not a measurement: a regex for "
        "nav/cookie/footer phrases plus a link-density rule. It is reported as "
        "an indicator, not a precise figure.",
        "- **Firecrawl main-content filtering was ON** (`only_main_content=True`) "
        "for every Firecrawl fetch. Boilerplate numbers must be read as "
        "\"with Firecrawl main-content filtering on\". The ablation measures its effect.",
        "- **Key-fact recall rewards verbosity.** A fetcher returning the whole "
        "DOM scores well on recall and badly on boilerplate. Read the two together.",
        "- **Short match terms** such as 'Free', 'Map' and 'Agent' can match "
        "incidentally, so absolute recall is an upper bound. This affects all "
        "fetchers equally.",
        "- **Uneven key coverage.** Firecrawl and Linear carry 5 scored facts; "
        "Mobbin carries 1, because its pages blocked the independent verification "
        "fetch. Only the aggregate across all 34 facts is comparable.",
        "- **firecrawl_scrape used limit=3** against Tavily's 5 results, a cost "
        "decision. After the shared 1,500-char cap it therefore receives less "
        "total context than Tavily, which is a handicap from configuration "
        "rather than a property of the provider.",
        "- **Agent non-determinism** is present in Experiment B. Identical inputs "
        "can produce different tool-call sequences, which is why Experiment A "
        "exists separately.",
        "",
        "## Reproduce",
        "",
        "```bash",
        "cp .env.example .env     # add GEMINI_API_KEY, TAVILY_API_KEY, FIRECRAWL_API_KEY",
        "pip install -r requirements.txt",
        "python -m benchmarks.retrieval_compare --experiment all",
        "```",
    ]

    (RESULTS / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--experiment", choices=["a", "b", "ablation", "all"], default="all")
    parser.add_argument("--runs", type=int, default=2, help="runs for experiment A")
    parser.add_argument("--report-only", action="store_true")
    parser.add_argument("--rescore", action="store_true",
                        help="recompute experiment A facts from saved content")
    parser.add_argument("--refetch-failed", action="store_true",
                        help="re-fetch experiment A rows that errored, then re-score")
    parser.add_argument("--ablation-pages", nargs="+", metavar="URL",
                        help="run the only_main_content ablation on these pages only")
    args = parser.parse_args()

    if args.ablation_pages:
        ablation_main_content(pages=args.ablation_pages)
        build_report()
        return

    if args.refetch_failed:
        refetch_failed()
        build_report()
        return

    if args.rescore:
        rescore()
        build_report()
        return

    if args.report_only:
        build_report()
        return

    if args.experiment in ("a", "all"):
        experiment_a(runs=args.runs)
    if args.experiment in ("ablation", "all"):
        ablation_main_content()
    if args.experiment in ("b", "all"):
        experiment_b()

    build_report()


if __name__ == "__main__":
    main()
