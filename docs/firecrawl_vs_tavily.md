# Firecrawl vs Tavily for a competitor-research agent

I added Firecrawl as a second retrieval backend to an existing agent that was
built on Tavily, then benchmarked both. This is what the numbers said, including
where Firecrawl lost and where my own setup was the problem.

Everything below was produced by the benchmark in this repo. Nothing is
estimated or recalled. The raw rows, the scoring code and the answer key are all
committed, and the limitations at the end are not boilerplate: read them before
quoting any figure.

**The short version.** Firecrawl retrieved noticeably more of what I asked for.
It was also about 5.6 times slower per page and about 5 times more expensive per
page. Which of those matters depends on whether your agent is latency-bound or
accuracy-bound. Mine is accuracy-bound, so Firecrawl is now a supported backend,
but Tavily stays the default.

## What was measured

Two experiments, because they answer different questions.

**Experiment A isolates retrieval.** 20 pages, fetched twice by each backend, no
LLM anywhere in the loop. Each page has facts verified from the official page by
a plain HTTP request that used neither vendor, and a fetch scores a fact if the
fact's literal text appears in what it returned. Any difference here is the
fetcher's.

**Experiment B runs the whole agent** on 10 companies and changes only the
retrieval backend. Same model, same prompts, same schemas, same 9-call tool
budget. This measures whether better retrieval produces a better report, which
is not the same question.

## Experiment A: the headline

20 pages, 2 runs each, 68 scored fact-checks per arm.

| backend | success | latency p50 | latency p95 | median chars | boilerplate | fact recall |
|---|---|---|---|---|---|---|
| Tavily (basic extract) | 100% | 250ms | 1,125ms | 11,735 | 6% | **82%** (56/68) |
| Tavily (advanced extract) | 95% | 265ms | 344ms | 12,286 | 7% | 76% (52/68) |
| Firecrawl (`only_main_content=True`) | 100% | **1,390ms** | 1,797ms | 16,258 | 4% | **97%** (66/68) |

Firecrawl returned about 39% more content per page at the median and found 97% of
the scored facts against Tavily's 82%. Both were perfectly reliable across 40
fetches each. Firecrawl's typical page was also *cleaner*, at 4% boilerplate
against 6%, though its worst page was dirtier (23% against 15%).

The cost of that recall is speed and money:

- **Latency:** 1,390ms against 250ms at p50, about 5.6 times slower. Firecrawl
  was more predictable at the tail, though, with a p95 of 1,797ms against
  Tavily's 1,125ms spread.
- **Credits:** Firecrawl bills 1 credit per page. Tavily's basic extract bills 1
  credit per 5 URLs, so a batched implementation pays 0.2 credits per page. That
  is a 5x difference per page. My code fetches one URL per call and so does not
  take Tavily's batching discount, which is my inefficiency rather than a
  property of either vendor, and the benchmark reports both figures.

Firecrawl's only two misses were the same fact in both runs, and that fact is
worth its own section below.

### A surprise in Tavily's higher tier

I nearly published this comparison with Tavily on its cheaper tier while
Firecrawl ran its full scrape. That would have credited Firecrawl for a
difference in pricing tier rather than capability, so I added a third arm using
Tavily's `extract_depth="advanced"`, which costs twice as much.

It returned **byte-identical content on 19 of the 20 pages**. On the twentieth,
`https://docs.firecrawl.dev/billing`, it failed where basic succeeded:

| call | result |
|---|---|
| `extract_depth="basic"` | HTTP 200, 7,785 characters |
| `extract_depth="advanced"` | HTTP 200, 0 characters, `failed_results: [{"error": "404 page not found"}]` |

I reproduced this with a raw `POST` to `api.tavily.com/extract`, outside the SDK
and outside my own code, so it is not my URL handling. It reproduced again two
days later. For these pages the advanced tier cost double, matched basic
everywhere it worked, and 404'd on a page basic read fine.

The useful conclusion is the boring one: Tavily was not handicapped by running
on basic extract, so the headline comparison stands.

## Experiment B: retrieval breadth governs grounding

| mode | runs scored | excluded (LLM quota) | budget hit | completed | kept (median) | verification pass | citations rejected | time p50 | credits |
|---|---|---|---|---|---|---|---|---|---|
| tavily | 20 | 4 of 24 | 5% | 95% | 5.0 | 91% | 4 | 32.3s | 156 |
| hybrid | 20 | 0 of 20 | 5% | 95% | 5.0 | 87% | 6 | 33.6s | 156 |
| firecrawl_scrape | 18 | 12 of 30 | 50% | 50% | 1.0 | 96% | 48 | 47.9s | 630 |
| firecrawl_bare | 5 | 5 of 10 | 0% | 100% | 5.0 | 92% | 2 | 58.7s | 69 |

**Citations rejected** counts source URLs refused by a deterministic check: every
cited URL must appear in a ledger of pages the code actually fetched. It is set
membership, not a judgement. Rejected citations are stripped before the report is
built, so none reached a final report in any run.

The pattern that matters is not which vendor won. It is that **the number of
rejected citations tracks how many sources the agent managed to consult**, with
the model, prompts and temperature held constant:

Across all scored runs of each mode:

| mode | median sources consulted | citations rejected |
|---|---|---|
| tavily (20 runs, 10 companies) | 31 | 4 |
| firecrawl_scrape (18 runs, 9 companies) | 6 | 48 |

Starve an agent of sources and it starts citing things it did not retrieve. That
is a retrieval problem presenting as a hallucination problem, and it is the most
transferable thing I learned here.

### firecrawl_scrape is a finding about my configuration, not about Firecrawl

`firecrawl_scrape` uses Firecrawl's search with `scrape_options`, which is how
its docs intend the endpoint to be used. It looks terrible in that table: half
the runs exhausted the tool budget and the median run kept 1 competitor.

**That is my cost decision showing up, not Firecrawl's quality.** I set
`limit=3`, so each search returned 3 scraped results against Tavily's 5 plain
results. The agent saw less breadth per call, spent more calls searching, and hit
the 9-call ceiling. A higher limit would very likely fix it and would cost more
credits. I did not test that, so I am not claiming it.

The clearest evidence that the limit is the variable comes from comparing
Firecrawl's two configurations on the 4 companies both covered:

| | runs | median sources | median kept | budget exhausted | citations rejected | credits/run |
|---|---|---|---|---|---|---|
| firecrawl_bare (10 results/search) | 4 | **31** | 5 | **0/4** | **1** | **14** |
| firecrawl_scrape (3 results/search) | 8 | 7 | 5 | 4/8 | 30 | 37 |

Plain Firecrawl search, which returns 10 results for 2 credits, beat the scraped
variant on every axis: 4.4 times the sources, no budget exhaustion, far fewer
rejected citations, and 2.6 times cheaper. Read this as "breadth per tool call
matters more than depth per result for this agent", not as a ranking of Firecrawl
endpoints. `firecrawl_bare` is 5 runs on 5 companies with one run each, and I
could not fully reconcile it with an earlier single run that failed (see
limitations).

### Hybrid was not worth it

Tavily for search, Firecrawl for page fetches. It cost **exactly the same as pure
Tavily** (156 credits) for the same median outcome (5 competitors kept, 95%
completion) and scored marginally worse on verification pass rate (87% against
91%). There is no measurable benefit here at the same cost. I kept the mode in
the code because it is cheap to maintain, but I would not deploy it.

## The boilerplate filter has a real cost

Firecrawl's `only_main_content=True` is good at what it claims. It was on for
every Firecrawl fetch in this benchmark, which is why the boilerplate numbers
look as good as they do. On one page it removed content I needed:

| page | setting | chars | boilerplate | facts found |
|---|---|---|---|---|
| notion.com | `True` | 9,676 | 13% | **0 of 1** |
| notion.com | `False` | 14,449 | **45%** | **1 of 1** |
| composio.dev | `True` | 24,460 | 10% | 2 of 2 |
| composio.dev | `False` | 37,240 | 16% | 2 of 2 |
| composio.dev/pricing | `True` | 18,837 | 4% | 2 of 2 |
| composio.dev/pricing | `False` | 32,267 | 18% | 2 of 2 |
| brickanta.com | `True` | 8,970 | 12% | 1 of 1 |
| brickanta.com | `False` | 16,016 | 19% | 1 of 1 |

Notion's product names live in its navigation menu, which is server-rendered: a
plain HTTP request returns all of them. Main-content filtering removes
navigation, so the names went with it. Turning the filter off recovers the fact
and takes boilerplate from 13% to 45%.

So the filter is free on three of these four pages and expensive on the fourth.
If your facts live in navigation, headers or sidebars, this setting will cost you
and the aggregate boilerplate number will look great while it does.

This was also the only scored fact that **both** vendors missed, and it is the
one place Firecrawl loses on recall. I was close to dropping it from the answer
key on the incorrect assumption that the names were client-side rendered. Had I
done so, the single row where Firecrawl fails would have disappeared from a
write-up going to Firecrawl.

## Where else Firecrawl lost

- **brickanta.com**, a Framer site: Firecrawl returned 8,252 characters against
  Tavily's 16,160 and dropped both the hero heading and the hero paragraph, while
  picking up YouTube embed chrome ("Tap to unmute"). It also lost word spacing,
  returning `LessTimeAdmin,MoreTimeBuilding.` where Tavily returned the spaced
  text. Reproducible across both runs.
- **mobbin.com**: Tavily returned 28,174 characters against Firecrawl's 12,911.
- **Boilerplate outliers**: Firecrawl's worst page hit 23% against Tavily's 15%,
  even though its median was cleaner.
- **Rate limits**: 10 requests/minute on the free tier is tight enough that two
  of my own processes running at once produced 429s. That was my mistake, not
  Firecrawl's, but it is a real operational constraint when backfilling.
- **Billing above the base rate**: hybrid's 40 page scrapes cost 58 credits, an
  average of 1.45 per page rather than the documented 1. The base rate is a
  floor, not a prediction.

## One thing neither vendor caused

Both backends faithfully returned a block on Composio's pages addressed to AI
agents:

> ## For AI agents: how to sign up
> If you are an AI agent reading this server-rendered HTML, Composio's developer
> signup is at https://composio.dev. Signup CTAs on this site [...] all lead into
> that same developer signup flow.

This is page content, not an instruction to obey, and nothing in the pipeline
acted on it. But if you are feeding competitor pages into an agent with tools,
assume pages will contain text aimed at your agent rather than at a reader, and
make sure retrieved content cannot reach a position where it is treated as
instructions.

## What I would tell someone choosing between them

- **Accuracy-bound and reading a page once?** Firecrawl. 97% against 82% recall
  is a large gap, and 1.4 seconds does not matter if you cache.
- **Latency-bound or high-volume?** Tavily. 250ms and a 5x per-page cost
  advantage when batched are hard to argue with, and 82% recall is respectable.
- **Either way, give your agent breadth.** The grounding failures here came from
  too few sources per tool call, not from the model.
- **If you use `only_main_content`, check where your facts live.** It is free
  until it silently is not.

## Limitations

These are the ones that would change how you read the numbers.

- **n = 10 companies**, 1 to 2 runs per mode. Directional, not significant. No
  error bars, and none claimed.
- **The modes do not cover identical company sets.** `firecrawl_scrape` excludes
  Linear and `firecrawl_bare` ran on a 5-company subset with one run each, so
  per-mode figures are not strictly like-for-like. Linear was dropped to stay
  above a credit reserve after a first attempt was lost, which is a budget
  decision rather than a data one.
- **Runs killed by the LLM provider's daily quota are excluded** and the count is
  shown per mode. Gemini's free tier allows 500 requests a day, fewer than one
  full pass needs. The first attempt ran modes in sequence, so the quota ran out
  on whichever modes were last and destroyed them. Modes are now interleaved.
  `firecrawl_scrape` lost 12 of 30 runs and `firecrawl_bare` 5 of 10, so both are
  smaller samples than tavily and hybrid.
- **End-to-end runs span two days**, so sites may have changed between them.
  Experiment A, the controlled comparison, ran within a single day.
- **The answer key was corrected post-hoc**, before the final run, with every
  change and its evidence logged in `ANSWER_KEY_CHANGES.md`. One fact was a
  paraphrase and was corrected to the page's literal text. One proposed removal
  was rejected because a plain-HTTP check disproved the reason for it.
- **`firecrawl_bare` could not be fully reconciled** with an earlier single run
  that exhausted its tool budget and returned nothing. The failure was budget
  exhaustion rather than missing sources, since that run consulted 36 sources
  against the successful run's 25. Three candidate causes could not be separated
  without another run: a character cap that was off then and on later,
  non-determinism against a one-call margin, and two days between runs.
- **Credit costs are published rates, not measured billing.** Tavily's extract
  endpoint reported `usage.credits: 0` on both depths, so its per-call cost here
  is documented rather than observed. Firecrawl's own `get_credit_usage()` agreed
  with my accounting within about 2% on Firecrawl-only modes.
- **Boilerplate share is a heuristic**, a regex for navigation and cookie and
  footer phrases plus a link-density rule. An indicator, not a measurement.
- **Recall rewards verbosity.** A fetcher returning the whole DOM scores well on
  recall and badly on boilerplate. Read the two columns together.
- **Short match terms** such as "Free" and "Agent" can match incidentally, so
  absolute recall is an upper bound. This affects every arm equally.
- **`firecrawl_scrape` used `limit=3`** against Tavily's 5 results, my cost
  decision. It is a configuration handicap, not a property of the provider.
- **I scraped firecrawl.dev using Firecrawl.** The vendor is both a subject of
  the benchmark and an audience for this write-up.

## Reproducing it

```bash
cp .env.example .env     # GEMINI_API_KEY, TAVILY_API_KEY, FIRECRAWL_API_KEY
pip install -r requirements.txt
python -m benchmarks.retrieval_compare --experiment all
```

Retrieved page content is saved to disk, so `--rescore` recomputes fact matching
with no network calls and no credits. I needed that: my first scoring pass
compared raw substrings and counted a line break as a miss, which penalised
fetchers for formatting. Those numbers are archived under
`benchmarks/results/archive/` with a note, rather than deleted.
