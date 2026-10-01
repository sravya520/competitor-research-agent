# Answer Key — DRAFT, needs your browser verification

**Status: not usable until verified.** No value below came from Tavily or
Firecrawl output. Deriving the key from either provider's results would bias
the benchmark toward whichever provider supplied it.

## Provenance tags

| Tag | Meaning |
|---|---|
| `[YOU]` | From your Phase 1 brief. Still needs confirming against the official site. |
| `[PRIOR]` | From my own prior knowledge. **Treat as a guess until you check it.** May be stale — my knowledge has a cutoff and funding/pricing changes often. |
| `[BLANK]` | I do not know this. Not guessed. Fill in or mark absent. |

## How to verify

For each fact: open the listed URL, and either confirm the value, correct it,
or mark it **ABSENT** if it genuinely isn't on the official site. Absent is a
valid and useful outcome — a fact that isn't published can't be a fair test of
retrieval, and marking it absent stops it penalising both providers.

## One design rule this key must follow

**Each fact is tied to the specific page it lives on**, and the benchmark will
fetch *that* page when scoring it. Scoring a pricing fact against a homepage
scrape would measure which page we chose, not which provider retrieved better.

Where a fact lives on a page the agent wouldn't naturally visit, that's worth
knowing too — note it and we'll decide whether to keep it.

---

## 1. Firecrawl — firecrawl.dev

> **Conflict of interest.** This is the vendor and the audience for the
> writeup, and we scrape it using Firecrawl. Flagged in limitations.

| # | Fact slot | Candidate | Check at |
|---|---|---|---|
| 1 | Free tier credits | 1,000 credits/month `[PRIOR]` | https://www.firecrawl.dev/pricing |
| 2 | Product/endpoint names | Scrape, Crawl, Map, Search, Extract `[PRIOR]` | https://docs.firecrawl.dev |
| 3 | Scrape credit cost | 1 credit/page `[PRIOR]` | https://docs.firecrawl.dev/billing |
| 4 | Open-source positioning | `[BLANK]` | https://www.firecrawl.dev |
| 5 | Funding / backing line | `[BLANK]` | https://www.firecrawl.dev/about |

## 2. Nango — nango.dev

| # | Fact slot | Candidate | Check at |
|---|---|---|---|
| 1 | Product category | Product integrations / unified API `[PRIOR]` | https://www.nango.dev |
| 2 | Number of pre-built integrations | `[BLANK]` — a headline number is usually on the homepage | https://www.nango.dev |
| 3 | Free tier exists? | `[BLANK]` | https://www.nango.dev/pricing |
| 4 | Open-source license | `[BLANK]` | https://github.com/NangoHQ/nango |
| 5 | Funding line | `[BLANK]` | https://www.nango.dev |

## 3. Composio — composio.dev

| # | Fact slot | Candidate | Check at |
|---|---|---|---|
| 1 | Product category | Tool/auth infrastructure for AI agents `[PRIOR]` | https://composio.dev |
| 2 | Number of tools/integrations | `[BLANK]` — headline number usually on homepage | https://composio.dev |
| 3 | Free tier exists? | `[BLANK]` | https://composio.dev/pricing |
| 4 | Named framework integrations | `[BLANK]` | https://docs.composio.dev |
| 5 | Funding line | `[BLANK]` | https://composio.dev |

## 4. Mobbin — mobbin.com

Expected to be the JS-heavy case where a headless scraper should beat a plain
fetcher. If a provider returns an empty shell here, that is a real result.

| # | Fact slot | Candidate | Check at |
|---|---|---|---|
| 1 | Product category | Design reference / UI pattern library `[PRIOR]` | https://mobbin.com |
| 2 | Screens or apps count | `[BLANK]` | https://mobbin.com |
| 3 | Pricing tiers | `[BLANK]` | https://mobbin.com/pricing |
| 4 | Platforms covered (iOS/Android/Web) | `[BLANK]` | https://mobbin.com |
| 5 | Free tier exists? | `[BLANK]` | https://mobbin.com/pricing |

## 5. Brickanta

| # | Fact slot | Candidate | Check at |
|---|---|---|---|
| 1 | Product category | AI agents for construction `[YOU]` | official site — **URL needed** |
| 2 | HQ city | Stockholm `[YOU]` | official site / YC profile |
| 3 | YC batch | F25 `[YOU]` | https://www.ycombinator.com/companies |
| 4 | Named product(s) | `[BLANK]` | official site |
| 5 | Pricing published? | `[BLANK]` | official site |

**I need the exact domain from you** — I will not guess a URL for a company I
don't know, since guessing wrong would score a real provider against a site
that isn't theirs.

## 6. Dataleap

| # | Fact slot | Candidate | Check at |
|---|---|---|---|
| 1 | Product category | Enterprise agent OS `[YOU]` | official site — **URL needed** |
| 2 | YC batch | S24 `[YOU]` | https://www.ycombinator.com/companies |
| 3 | Named product(s) | `[BLANK]` | official site |
| 4 | Pricing published? | `[BLANK]` | official site |
| 5 | HQ location | `[BLANK]` | official site / YC profile |

**Exact domain needed.** Note "Dataleap" is a fairly generic name — there may
be several companies using it, which is itself the entity-ambiguity problem
this project exists to handle. Worth watching during the run.

## 7. Manufact

| # | Fact slot | Candidate | Check at |
|---|---|---|---|
| 1 | Product category | MCP infrastructure `[YOU]` | official site — **URL needed** |
| 2 | Open-source SDK name | `mcp-use` `[YOU]` | GitHub |
| 3 | YC batch | S25 `[YOU]` | https://www.ycombinator.com/companies |
| 4 | Pricing published? | `[BLANK]` | official site |
| 5 | HQ location | `[BLANK]` | official site / YC profile |

**Exact domain needed.**

## 8. Arcade.dev — arcade.dev

| # | Fact slot | Candidate | Check at |
|---|---|---|---|
| 1 | Product category | Tool-calling / auth infrastructure for AI agents `[PRIOR]` | https://www.arcade.dev |
| 2 | Named toolkits/integrations | `[BLANK]` | https://docs.arcade.dev |
| 3 | Free tier exists? | `[BLANK]` | https://www.arcade.dev/pricing |
| 4 | Auth/OAuth positioning | `[BLANK]` | https://www.arcade.dev |
| 5 | Funding line | `[BLANK]` | https://www.arcade.dev |

## 9. Notion — notion.so

| # | Fact slot | Candidate | Check at |
|---|---|---|---|
| 1 | Free plan exists | Yes `[PRIOR]` | https://www.notion.com/pricing |
| 2 | Paid tier names | Plus, Business, Enterprise `[PRIOR]` — **likely stale, names have changed** | https://www.notion.com/pricing |
| 3 | Named products beyond core | Notion AI, Notion Calendar, Notion Mail `[PRIOR]` | https://www.notion.com |
| 4 | Founded year | 2013 `[PRIOR]` | https://www.notion.com/about |
| 5 | Founder name | Ivan Zhao `[PRIOR]` | https://www.notion.com/about |

## 10. Linear — linear.app

| # | Fact slot | Candidate | Check at |
|---|---|---|---|
| 1 | Free plan exists | Yes `[PRIOR]` | https://linear.app/pricing |
| 2 | Paid tier names | Basic, Business, Enterprise `[PRIOR]` — **verify, these change** | https://linear.app/pricing |
| 3 | Core concept names | Issues, Projects, Cycles, Initiatives `[PRIOR]` | https://linear.app |
| 4 | Founded year | 2019 `[PRIOR]` | https://linear.app/about |
| 5 | Founder name | Karri Saarinen `[PRIOR]` | https://linear.app/about |

---

## What I need back

1. **Three domains**: Brickanta, Dataleap, Manufact.
2. **Verified or corrected values**, or **ABSENT**, for each of the 50 slots.
3. A note on any fact that lives somewhere the agent wouldn't naturally look.

## Scoring method, for your review before Phase 2

- Case-insensitive substring match against retrieved `content`.
- An `accepted_variants` list per fact (e.g. "1,000" / "1000" / "1k") so
  formatting differences don't read as retrieval failures.
- Numbers matched as strings, not parsed — parsing invites silent coercion
  bugs that would quietly inflate scores.

**Known weakness, to be stated in the writeup:** key-fact presence rewards
verbosity. A provider returning the entire DOM scores well on recall while
scoring badly on boilerplate share. The two metrics must be read together, and
neither alone decides the comparison.
