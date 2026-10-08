# Answer key corrections

Every change made to `benchmarks/answer_key.json` after it was first verified,
with the evidence for it. All of these are **post-hoc corrections made before
the final end-to-end run**, and the benchmark's limitations say so.

## Why corrections were needed

The original verification fetch returned model summaries of each page rather
than literal page text, so some key values were paraphrases of what the page
said rather than quotations of it. A paraphrase cannot be matched by substring,
so it scores as a miss for every provider and makes retrieval look worse than it
is.

## How each fact was re-checked

Any fact missed by **all** arms was re-checked against the official page's raw
HTML using a plain HTTP GET, `benchmarks/verify_key_raw.py`, which uses
`httpx` directly and involves neither Tavily nor Firecrawl. Because `httpx` does
not execute JavaScript, anything it returns is server-rendered by definition.

Two facts were missed by every arm. Both were investigated; one was corrected
and one was kept.

---

## 1. Brickanta / Product category: CORRECTED

| | |
|---|---|
| Page | https://brickanta.com |
| Old value | `the agentic AI platform for construction` |
| Old terms | `["agentic AI platform for construction", "AI platform for construction"]` |
| New value | `Agentic AI for Construction` |
| New terms | `["Agentic AI for Construction"]` |

**Evidence.** The old wording does appear in the raw HTML, but only inside three
metadata tags, `<meta name="description">`, `og:description` and
`twitter:description`:

```html
<meta name="description" content="Brickanta is the agentic AI platform for
construction. Hundreds of AI agents handle bidding, procurement, compliance and
quality assurance in every project.">
```

It appears nowhere in the rendered body text. Extraction services return page
content, not metadata, so no provider could return it and the row measured
nothing about retrieval.

The same claim *is* stated in visible body text as **"Agentic AI for
Construction"**, confirmed in the tag-stripped plain-HTTP rendering:

```
... Nicklas Lagerberg CEO Trusted by Agentic AI for Construction Running
Construction Projects is Complicated. We Make it Simple. ...
```

So the original value was accurate about the company but was taken from
metadata. The key now quotes the literal visible text.

**Effect.** All three arms retrieve the corrected phrase, so the row now scores
1 for everyone. It stops depressing every arm's recall and no longer favours
any provider.

---

## 2. Notion / Named products beyond core: KEPT, NOT DROPPED

| | |
|---|---|
| Page | https://www.notion.com |
| Value | `Notion AI, Agents, AI Meeting Notes, Enterprise Search, Notion Calendar` |
| Terms | `["Notion AI", "AI Meeting Notes", "Enterprise Search", "Notion Calendar"]` (match: any) |

This row was proposed for dropping on the grounds that the names were rendered
client-side and therefore unreachable by any server-side fetcher. **That premise
was wrong, and the plain-HTTP check disproved it.** The row is kept.

**Evidence.** All four names are present in the server-rendered HTML and survive
tag-stripping, in the site's navigation menu:

```
Product  Notion AI  AI tools for work  Agents  Automate busywork
AI Meeting Notes  Perfectly written by AI  Enterprise Search  Find answers
instantly  ...  Notion Calendar
```

The plain HTTP GET returns 3,042 characters of rendered text containing all
four. What the two providers returned from the same URL:

| fetcher | chars | terms found |
|---|---|---|
| plain HTTP GET | 3,042 | all 4 |
| tavily (basic) | 680 | none |
| tavily (advanced) | 680 | none |
| firecrawl, `only_main_content=True` | 9,676 | none |
| firecrawl, `only_main_content=False` | 14,449 | `Notion AI` |

So the fact is retrievable server-side, and both providers miss it as
configured. Firecrawl's own main-content filter is what removes it: turning the
filter off recovers one of the four terms, which is enough to satisfy the
`any` rule.

**Why keeping it matters.** This is the only scored fact that *both* providers
miss. Dropping it would have deleted the single row where Firecrawl fails and
flattered the provider this write-up is being sent to. It is a genuine shared
retrieval failure and a real cost of boilerplate filtering, so it stays and is
reported as such.

---

## Facts not changed

The 32 remaining scored facts were untouched. Facts that one arm found and
another missed were left alone by design: a disagreement between arms is the
measurement, not an error in the key.
