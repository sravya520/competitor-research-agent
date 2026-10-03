# Tavily vs Firecrawl — benchmark results

Generated 2026-10-03T08:08:02.567545+00:00
Model held constant across all modes: `gemini-flash-lite-latest`
Answer key: 34 facts, independently verified (see `docs/ANSWER_KEY_CHECKLIST.md`)

## Experiment A — retrieval level (no LLM)

| fetcher | success | latency p50 | latency p95 | content chars | boilerplate | key-fact recall |
|---|---|---|---|---|---|---|
| tavily | 100% | 250ms | 1125ms | 11735 | 6% | 82% (56/68) |
| firecrawl | 100% | 1390ms | 1797ms | 16258 | 4% | 97% (66/68) |
| tavily_advanced | 95% | 265ms | 344ms | 12286 | 7% | 76% (52/68) |

## Experiment B — end to end

| mode | runs scored | excluded (LLM quota) | budget hit | completed | kept (median) | verif. pass | citations rejected | time p50 | credits |
|---|---|---|---|---|---|---|---|---|---|
| firecrawl_bare | 5 | 5 of 10 | 0% | 100% | 5 | 92% | 2 | 58.7s | 69.0 |
| firecrawl_scrape | 18 | 12 of 30 | 50% | 50% | 1.0 | 96% | 48 | 47.9s | 630.0 |
| hybrid | 20 | 0 of 20 | 5% | 95% | 5.0 | 87% | 6 | 33.6s | 156.0 |
| tavily | 20 | 4 of 24 | 5% | 95% | 5.0 | 91% | 4 | 32.3s | 156.0 |

**Citations rejected** counts source URLs the fabrication check refused: a deterministic test that every cited URL appears in the ledger of pages our own code actually fetched. It is set membership, not a judgement, so it rejects every citation that is not in the ledger. In both entry points (`main.py`, `app.py`) the rejected citations are stripped before the report is built and before corroboration is checked, so 100% of them were caught and none reached a final report. The check cannot detect a citation whose URL *was* fetched but is described wrongly; corroboration and the precise-claims check cover that separately.

### Credits, both ways

| mode | as implemented | with Tavily batching |
|---|---|---|
| firecrawl_bare | 69.0 | 69.0 |
| firecrawl_scrape | 630.0 | 630.0 |
| hybrid | 156.0 | 156.0 |
| tavily | 156.0 | 142.0 |

### Truncation (1,500 search / 25,000 page)

| mode | search results truncated | pages truncated |
|---|---|---|
| firecrawl_bare | 15% | 25% |
| firecrawl_scrape | 87% | 16% |
| hybrid | 2% | 8% |
| tavily | 2% | 17% |

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
- **The modes do not all cover the same companies.** firecrawl_scrape excludes Linear and firecrawl_bare runs on a 5-company subset, so their samples are smaller than tavily's and hybrid's. Linear was dropped to stay above the Firecrawl credit reserve after the first attempt's runs were lost to the LLM quota. That is a budget decision, not a data one, and it means per-mode figures are not strictly like-for-like across the same company set.
- **The end-to-end runs span two days.** Gemini's free tier allows 500 requests a day, which is fewer than one full pass needs, so the modes were completed across two calendar days. Sites may have changed between them. Experiment A, which is the controlled retrieval comparison, ran within a single day.
- **Answer key wording was corrected post-hoc**, before the final end-to-end run, and every change is logged with its evidence in `docs/ANSWER_KEY_CHANGES.md`. One fact was corrected from a paraphrase to the page's literal text; one proposed removal was rejected because the plain-HTTP check disproved the reason for it.
- **firecrawl_bare's result could not be fully reconciled with the earlier single run.** The Phase 1 run on Linear exhausted all 9 research tool calls and returned nothing; the final run on the same company used 7 calls and kept 5. The failure was budget exhaustion, not missing sources: the failed run consulted 36 sources against the successful run's 25. Three candidate causes could not be separated without a further run, which was out of scope: the per-result character cap was off in Phase 1 and on afterwards, which shortens context and can change tool-call behaviour; the margin is thin, with one final run using 8 of 9 calls, and agent tool sequences are non-deterministic; and the two runs were two days apart. The earlier note that bare search returns uniformly short snippets does not hold either: 16% of its search results on Linear and 40% on Notion exceeded the 1,500-character cap. Read firecrawl_bare as 5 runs on 5 companies, one run each, not as a settled result.
- **Credit costs come from each vendor's published pricing, not from measured billing.** Tavily's extract endpoint reported `usage.credits: 0` on both basic and advanced depth, so its per-call cost here is the documented rate rather than an observed charge. Firecrawl's figures were cross-checked against its own `get_credit_usage()` and the gap is reported per run. On the Firecrawl-only modes our accounting lands within about 2% of Firecrawl's own: 630 computed against 619 billed for firecrawl_scrape, 69 against 67 for firecrawl_bare. Hybrid's 40 computed against 58 billed is a real under-count: its 40 page scrapes averaged 1.45 credits each rather than the base 1, so some pages bill above the base rate. The documented base rate is therefore a floor, not a prediction, and a plan sized on it will under-budget for sites that need costlier scraping. The worst single run shows a 29-credit gap; it ran while another of our own processes was also calling Firecrawl, and the before/after reading is account-wide so it cannot isolate one process. The other 17 runs fall between -7 and 0, as do all 10 runs executed with no concurrent use.
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
