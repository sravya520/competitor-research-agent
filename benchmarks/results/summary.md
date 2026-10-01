# Tavily vs Firecrawl — benchmark results

Generated 2026-10-01T15:42:04.743664+00:00
Model held constant across all modes: `gemini-flash-lite-latest`
Answer key: 34 facts, independently verified (see `docs/ANSWER_KEY_CHECKLIST.md`)

## Experiment A — retrieval level (no LLM)

| fetcher | success | latency p50 | latency p95 | content chars | boilerplate | key-fact recall |
|---|---|---|---|---|---|---|
| tavily | 100% | 250ms | 1125ms | 11735 | 6% | 82% (56/68) |
| firecrawl | 100% | 1390ms | 1797ms | 16258 | 4% | 97% (66/68) |
| tavily_advanced | 95% | 265ms | 344ms | 12286 | 7% | 76% (52/68) |

## Experiment B — end to end

| mode | runs scored | excluded (LLM quota) | budget hit | completed | kept (median) | verif. pass | fabrications | time p50 | credits |
|---|---|---|---|---|---|---|---|---|---|
| firecrawl_bare | 0 | 5 of 5 | n/a | n/a | n/a | n/a | n/a | n/a | n/a |
| firecrawl_scrape | 8 | 12 of 20 | 38% | 62% | 4.5 | 96% | 26 | 49.9s | 273.0 |
| hybrid | 20 | 0 of 20 | 5% | 95% | 5.0 | 87% | 6 | 33.6s | 156.0 |
| tavily | 16 | 4 of 20 | 0% | 100% | 4.5 | 89% | 4 | 33.1s | 122.0 |

### Credits, both ways

| mode | as implemented | with Tavily batching |
|---|---|---|
| firecrawl_bare | n/a | n/a |
| firecrawl_scrape | 273.0 | 273.0 |
| hybrid | 156.0 | 156.0 |
| tavily | 122.0 | 110.0 |

### Truncation (1,500 search / 25,000 page)

| mode | search results truncated | pages truncated |
|---|---|---|
| firecrawl_bare | n/a | n/a |
| firecrawl_scrape | 90% | 22% |
| hybrid | 2% | 8% |
| tavily | 2% | 11% |

## Ablation — only_main_content

| setting | pages | content chars | boilerplate |
|---|---|---|---|
| only_main_content=True | 4 | 14256 | 11% |
| only_main_content=False | 4 | 24142 | 18% |

Per page, with the scored facts each setting retrieves. Filtering is free on most pages and expensive on one: it costs no facts on three of these four while cutting boilerplate, and on notion.com it removes the navigation where the product names are.

| page | setting | chars | boilerplate | facts |
|---|---|---|---|---|
| https://brickanta.com | `True` | 8,970 | 12% | 1/1 |
| https://brickanta.com | `False` | 16,016 | 19% | 1/1 |
| https://composio.dev | `True` | 24,460 | 10% | 2/2 |
| https://composio.dev | `False` | 37,240 | 16% | 2/2 |
| https://composio.dev/pricing | `True` | 18,837 | 4% | 2/2 |
| https://composio.dev/pricing | `False` | 32,267 | 18% | 2/2 |
| https://www.notion.com | `True` | 9,676 | 13% | 0/1 |
| https://www.notion.com | `False` | 14,449 | 45% | 1/1 |

## Limitations

- **n = 10 companies**, 1-2 runs per mode. This is a directional comparison, not a result with error bars. No significance is claimed.
- **The end-to-end runs span two days.** Gemini's free tier allows 500 requests a day, which is fewer than one full pass needs, so the modes were completed across two calendar days. Sites may have changed between them. Experiment A, which is the controlled retrieval comparison, ran within a single day.
- **Answer key wording was corrected post-hoc**, before the final end-to-end run, and every change is logged with its evidence in `docs/ANSWER_KEY_CHANGES.md`. One fact was corrected from a paraphrase to the page's literal text; one proposed removal was rejected because the plain-HTTP check disproved the reason for it.
- **Credit costs come from each vendor's published pricing, not from measured billing.** Tavily's extract endpoint reported `usage.credits: 0` on both basic and advanced depth, so its per-call cost here is the documented rate rather than an observed charge. Firecrawl's figures were cross-checked against its own `get_credit_usage()` and the gap is reported per run.
- **We scrape firecrawl.dev using Firecrawl.** The vendor is both a benchmark subject and the audience for this write-up.
- **Runs killed by the LLM provider's daily quota are excluded**, and the count is shown per mode. Gemini's free tier allows 500 requests a day; the first attempt ran the modes in sequence, so exhaustion landed entirely on whichever modes were scheduled last. Modes are now interleaved. Any mode whose scored-run count is below its attempted count is a smaller sample than the others and should be read as such.
- **Boilerplate share is a heuristic**, not a measurement: a regex for nav/cookie/footer phrases plus a link-density rule. It is reported as an indicator, not a precise figure.
- **Firecrawl main-content filtering was ON** (`only_main_content=True`) for every Firecrawl fetch. Boilerplate numbers must be read as "with Firecrawl main-content filtering on". The ablation measures its effect.
- **Key-fact recall rewards verbosity.** A fetcher returning the whole DOM scores well on recall and badly on boilerplate. Read the two together.
- **Short match terms** such as 'Free', 'Map' and 'Agent' can match incidentally, so absolute recall is an upper bound. This affects all fetchers equally.
- **Uneven key coverage.** Firecrawl and Linear carry 5 scored facts; Mobbin carries 1, because its pages blocked the independent verification fetch. Only the aggregate across all 34 facts is comparable.
- **firecrawl_scrape used limit=3** against Tavily's 5 results, a cost decision. After the shared 1,500-char cap it therefore receives less total context than Tavily, which is a handicap from configuration rather than a property of the provider.
- **Agent non-determinism** is present in Experiment B. Identical inputs can produce different tool-call sequences, which is why Experiment A exists separately.

## Reproduce

```bash
cp .env.example .env     # add GEMINI_API_KEY, TAVILY_API_KEY, FIRECRAWL_API_KEY
pip install -r requirements.txt
python -m benchmarks.retrieval_compare --experiment all
```
