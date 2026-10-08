# Firecrawl as a Second Retrieval Backend: Plan

**Branch:** `firecrawl-backend`
**Status:** Phase 0 (plan only, no code written)
**Date:** 2026-10-01

Default provider stays `tavily`. The live app, the CLI and `run_eval.py` must
behave identically unless `RETRIEVAL_PROVIDER` is explicitly set.

---

## 1. Current retrieval path

### Where Tavily is called

Exactly two call sites, both in `tools.py`:

| Function | Tavily call | Returns |
|---|---|---|
| `search_web(query)` | `tavily_client.search(query, max_results=5)` | A single formatted **string** |
| `extract_company_page(url)` | `tavily_client.extract(url)` | `raw_content` string, or an explicit failure message |

`tavily_client` itself is constructed once in `config.py` at module import.

### How that output reaches the agent loop

Both functions are passed directly to Gemini as **tools**:

```
pipeline.identify_company()     tools=[search_web]                        max_tool_calls=3
pipeline.research_competitors() tools=[search_web, extract_company_page]  max_tool_calls=9
```

The Gemini SDK's automatic function calling executes them and feeds the
returned string back into the conversation. **The model only ever sees the
string these functions return**. It has no access to the raw provider
response. That is the seam a provider abstraction slots into cleanly.

Two behaviours in `search_web` shape what the model sees, and both must be
preserved across providers:

1. Each result is rendered as `Title: / URL: / Content:` blocks.
2. Results whose URL path matches `_LISTICLE_MARKERS` get an inline
   `[ROUNDUP/LISTICLE CONTENT, ...]` tag appended to the title.

`identify_company` additionally calls `extract_company_page` **directly in
Python** (not as a tool) when a URL is supplied, to anchor identity.

### How it reaches verification and the fabrication checks

This is the part most at risk, because it depends on a side effect:

```
tools.py: _sources_consulted: set[str]     ← module-level state
   ├── search_web()           adds every result["url"]
   └── extract_company_page() adds url, but ONLY on success
                    │
                    ▼
        tools.sources_consulted()  → sorted list
                    │
     ┌──────────────┴───────────────┐
     ▼                              ▼
evaluate.check_sources_are_real   evaluate.drop_fabricated_sources
(cited URL ∉ ledger → fabricated) (strips those URLs from the report)
```

**The fabrication check is entirely dependent on `_sources_consulted` being an
accurate record of what was really fetched.** Any new provider must populate it
with exactly the same semantics, including the critical rule that **a failed
fetch adds nothing**. If a provider recorded a URL it failed to retrieve, a
model citation of that URL would wrongly pass the fabrication check, silently
weakening the strongest guarantee in the system.

`verify_competitors` does **not** touch retrieval at all. It is a fresh,
tool-less LLM call. Provider choice cannot affect it directly; it only affects
it through the quality of the competitor list handed to it.

`evaluate.primary_source_ratio` and `looks_like_listicle` operate on URLs only,
so they are provider-agnostic.

### Risk summary

| Component | Coupling to Tavily | Risk |
|---|---|---|
| `search_web` return format | High: string shape is the model's input | Format drift changes model behaviour |
| `_sources_consulted` | High: correctness of fabrication check | A recorded-but-failed fetch breaks the guarantee |
| `extract_company_page` failure string | Medium: identity step relies on it | Empty string ≠ failure message |
| `evaluate.*` | None (URL-only) |: |
| `verify_competitors` | None |: |

---

## 2. Firecrawl endpoints, costs, rate limits

All figures from `docs.firecrawl.dev/billing` and `/features/search`, read
2026-10-01. Third-party pricing blogs were deliberately not used as sources.

### Relevant endpoints

| Endpoint | Purpose here | Credits |
|---|---|---|
| `search` | Analogue of `tavily.search` | **2 per 10 results** (rounded up) |
| `scrape` | Analogue of `tavily.extract` | **1 per page** |
| `map` | Not used | 1 per call |
| `crawl` | Not used: whole-site crawling is out of scope | 1 per page |

### Cost modifiers: all avoided

| Modifier | Extra cost | Decision |
|---|---|---|
| `json` format (LLM extraction) | **+4 / page** | **Avoid.** Our pipeline already does LLM extraction downstream; paying Firecrawl to do it again would be 5× the cost and would move reasoning out of the part of the system we control. |
| PDF parsing | +1 / PDF page | Allow (rare, unavoidable) |
| PII redaction | +4 / page | Not used |
| Zero Data Retention | +1 / page | Not used |
| Prompt-injection check | +4 / page | Not used, but **note for the writeup**: this is a paid mitigation for a risk this project currently carries unmitigated |

We will request `formats=['markdown']` only.

### Free tier limits

- **1,000 credits / month**
- **10 requests / minute** on scrape, map and search
- **2 concurrent browsers**

The 10 req/min ceiling is the binding constraint on benchmark wall-clock time,
not the credit budget. The benchmark must rate-limit itself to stay under it.

### Cost comparison, per equivalent operation

| Operation | Tavily | Firecrawl |
|---|---|---|
| Search, 5 results | **1** credit | **2** credits |
| Fetch 1 page | **1** credit (basic extract bills per 5 URLs) | **1** credit |
| Fetch 5 pages | **1** credit (if batched in one call) | **5** credits |

Two honest observations to carry into the writeup:

1. **Firecrawl search costs 2× Tavily search** for our result count.
2. **Tavily extract bills per 5 URLs, Firecrawl scrape bills per page.** Our
   code fetches one URL per call, so today they tie at 1 credit each, but
   Tavily has 5× headroom we are not using. If page fetching were batched,
   Tavily would be 5× cheaper. This is a real Tavily advantage and must be
   reported, not buried.

Both free tiers are 1,000 credits/month, which makes the comparison tidy but is
coincidental.

---

## 3. Provider interface

### Shared model

```python
class RetrievedDoc(BaseModel):
    url: str
    title: str
    content: str
    provider: str            # "tavily" | "firecrawl"
    fetched_at: datetime
    latency_ms: int
    error: str | None = None
```

**Invariant:** `error is not None` ⇒ `content == ""`. A failed fetch never
produces content, never gets added to the source ledger, and is never rendered
into the string the model sees. This is the rule that keeps the fabrication
check sound.

### Protocol

```python
class RetrievalProvider(Protocol):
    name: str
    def search(self, query: str, max_results: int = 5) -> list[RetrievedDoc]: ...
    def fetch(self, url: str) -> RetrievedDoc: ...
```

Three implementations:

| Mode | `search()` | `fetch()` |
|---|---|---|
| `tavily` (default) | Tavily search | Tavily extract |
| `firecrawl` | Firecrawl search | Firecrawl scrape |
| `hybrid` | Tavily search | Firecrawl scrape |

Selected by `RETRIEVAL_PROVIDER`, defaulting to `tavily` when unset or
unrecognised (with a warning, not a crash, an unrecognised value silently
changing retrieval would be worse than a loud fallback).

### What stays in `tools.py`

`tools.py` keeps responsibility for the three things the pipeline depends on,
so provider choice cannot change them:

- Rendering `list[RetrievedDoc]` into the exact `Title:/URL:/Content:` string
- Applying the `[ROUNDUP/LISTICLE CONTENT]` tag
- Updating `_sources_consulted`, only for docs where `error is None`

**Consequence:** `search_web` and `extract_company_page` keep their current
signatures and return types. `pipeline.py`, `prompts.py` and `evaluate.py`
need **no changes at all**. The tool docstrings the model reads stay byte-identical,
which removes a confound from the benchmark.

### Caching

All raw provider responses cached to `benchmarks/cache/` keyed by
`sha256(provider + operation + query_or_url)`, stored with the response and
timestamp.

Purpose is development iteration, not benchmark integrity. **Benchmark runs use
`--fresh` to bypass the cache**, because a cached second run would measure
nothing, latency would be fake and variance would vanish. The cache preserves
raw responses so metrics can be recomputed later without re-spending credits.

---

## 4. Benchmark design

Two experiments, deliberately separate. Mixing them would confound provider
quality with agent non-determinism.

### Experiment A: retrieval level (deterministic)

Fixed URL and query lists, no LLM in the loop. Directly comparable.

| Metric | Definition |
|---|---|
| Success rate | `error is None` and `content` non-empty |
| Latency p50 / p95 | Per call, measured client-side |
| Usable content length | Characters after boilerplate stripping |
| Boilerplate share | `1 − (usable / raw)`; nav, cookie banners, footers |
| Key-fact presence | Of N hand-labelled facts per company, how many appear in `content` |

**Boilerplate detection method must be stated in the writeup**, because it is
the most arguable metric here. Proposed: a fixed list of marker phrases
(cookie/subscribe/navigation/footer patterns) plus link-density ratio. It is a
heuristic and will be labelled as one.

**Key-fact answer key**: per company, 5 facts verifiable from the homepage
(e.g. one-line product description, pricing presence, a named customer, HQ
location, a named integration). Presence = case-insensitive substring or a
small set of accepted variants. **This answer key must be confirmed before
Phase 2 runs**, per the task.

Known weakness to state: key-fact presence rewards verbosity. A provider
returning the whole DOM scores well on recall while scoring badly on
boilerplate share. The two metrics must be read together, and the writeup will
say so.

### Experiment B: end-to-end

Full pipeline per company per mode, measuring what actually reaches a user.

| Metric | Source |
|---|---|
| Claims produced | `len(competitors)` after research |
| Verification pass rate | kept ÷ proposed, from `apply_verifications` |
| Fabrication failures | `check_sources_are_real` problem count |
| Corroboration rate | `check_source_corroboration`, already implemented |
| Primary-source ratio | `primary_source_ratio`, already implemented |
| Wall-clock time | Per run |
| Credits used | Counted by the provider wrapper, not estimated |

**Credits are counted, never estimated**: each provider increments a counter
using the documented cost rule for the call it just made.

### Run matrix

3 modes × 10 companies × 2 runs = 60 end-to-end runs, plus Experiment A.
Two runs expose variance; they do not establish statistical significance, and
the writeup will say that plainly. With n=10 companies this is a directional
comparison, not a benchmark with error bars.

---

## 5. Credit budget

### Firecrawl (1,000/month free)

| Item | Calculation | Credits |
|---|---|---|
| Experiment A: scrape | 20 URLs × 2 runs × 1 | 40 |
| Experiment A: search | 10 queries × 2 runs × 2 | 40 |
| Experiment B: `firecrawl` mode | 10 co. × 2 runs × ~15 | 300 |
| Experiment B: `hybrid` mode | 10 co. × 2 runs × ~5 scrapes | 100 |
| Development & smoke tests |: | 50 |
| **Subtotal** | | **530** |
| **Reserve** (retries, reruns, failures) | | **470** |

~15 credits per `firecrawl` end-to-end run assumes worst case: ~5 searches
(10 credits) + ~5 scrapes (5 credits) against a 9-call budget.

### Tavily (1,000/month free)

| Item | Credits |
|---|---|
| Experiment A | ~28 |
| Experiment B: `tavily` mode | ~120 |
| Experiment B: `hybrid` mode (search only) | ~100 |
| **Subtotal** | **~250** |

### Guardrails

- Hard credit ceiling in the benchmark script; abort rather than overspend.
- Self-imposed rate limit under 10 req/min.
- Live counter printed per run.

---

## 6. Benchmark companies

Eight specified, plus two well-known SaaS for contrast. The mix matters: the
obscure companies are where this project's retrieval has historically been
weakest, and the well-known ones are the easy case that should look good for
both providers.

| # | Company | Why included |
|---|---|---|
| 1 | Firecrawl | The vendor itself. Dev-tool site, docs-heavy. **Conflict of interest: the audience for this writeup. Results reported unchanged.** |
| 2 | Nango | Dev tool, API-integration category, docs-heavy |
| 3 | Composio | Dev tool, AI-agent tooling, docs-heavy |
| 4 | Mobbin | Design-reference product; likely a JS-heavy app shell: the case where a headless-browser scraper should beat a plain fetcher |
| 5 | Brickanta | **Unknown to me.** Site type to be recorded during setup, not guessed. |
| 6 | Dataleap | **Unknown to me.** Same. |
| 7 | Manufact | **Unknown to me.** Same. |
| 8 | Arcade.dev | Dev tool, agent auth |
| 9 | Notion | Well-known SaaS, marketing-heavy site, heavy boilerplate |
| 10 | Linear | Well-known SaaS, modern JS-rendered marketing site |

Companies 5–7 are genuinely unknown to me. I am not going to characterise their
site types from memory. Their actual type gets recorded during setup, and if
any turns out not to have a reachable site, that is itself a result worth
reporting rather than a reason to substitute it.

Site-type labels (static / JS-rendered / docs / marketing) get recorded as data
during setup so results can be segmented by type.

---

## 7. Decisions needed before Phase 1

1. **`docs/` is gitignored.** It currently holds personal interview-prep
   material. Both this plan and the final writeup are project documentation
   meant to be public. Proposed fix: change the ignore rule from `docs/` to
   `docs/*` plus explicit `!docs/FIRECRAWL_PLAN.md` and
   `!docs/firecrawl_vs_tavily.md` negations, negation cannot rescue a file
   whose parent directory is excluded, so the pattern must exclude *contents*,
   not the directory. Alternative: move prep material to `prep/`.

2. **Test framework.** No tests exist and "no new frameworks" is a rule.
   Proposed: stdlib `unittest` + `unittest.mock`, zero new dependencies.
   Override to pytest if preferred.

3. **`.env.example` does not exist**: will be created, not updated.

4. **Answer key** for key-fact presence requires confirmation before Phase 2
   runs, per the task. Draft comes at the end of Phase 1 so it can be built
   from real fetched pages rather than from memory.

---

## 8. Explicitly out of scope

- `crawl` and `map` endpoints
- Firecrawl's `json` extraction format (+4 credits, duplicates our pipeline)
- Changing the default provider
- Any change to `pipeline.py`, `prompts.py` or `evaluate.py`
- Statistical significance claims
