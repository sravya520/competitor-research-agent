# Answer Key Verification Checklist

Grouped by page so each URL is opened once.

**Status (1 Oct 2026):** Verified. Values were read from the official pages with a fetch independent of both Tavily and Firecrawl, then reviewed by Sravya.

**Legend:**
- `☑` = verified on the listed page, scored.
- `✗` = ABSENT on the listed page, or not applicable. Not scored.
- `⚑` = not yet confirmed. Excluded from scoring unless changed to `☑`.

**Rules agreed:**
- No `[PRIOR]` value enters the final key unverified.
- Anything not on the official page is ABSENT, never guessed.
- Each fact is scored only against the page listed above it.
- Pricing absent is not scored; it is recorded as not_applicable.
- Dataleap: each page is scored against its own wording.

---

## 1. Firecrawl

> ⚠️ Vendor, audience for the writeup, and we scrape it with Firecrawl itself.
> Flagged in limitations.

**https://www.firecrawl.dev/pricing**

| ✓ | Fact | Candidate | Verified value / ABSENT |
|---|---|---|---|
| ☑ | Free tier credits | 1,000 credits/month `[PRIOR]` | 1,000 credits / month |
| ☑ | Paid tier names | `[BLANK]` | Hobby, Standard, Growth, Scale, Enterprise |

**https://docs.firecrawl.dev/billing**

| ✓ | Fact | Candidate | Verified value / ABSENT |
|---|---|---|---|
| ☑ | Scrape credit cost | 1 credit/page `[PRIOR]` | 1 credit / page |
| ☑ | Search credit cost | 2 credits / 10 results `[PRIOR]` | 2 credits / 10 results (plus scrape cost per scraped result) |

**https://www.firecrawl.dev**

| ✓ | Fact | Candidate | Verified value / ABSENT |
|---|---|---|---|
| ☑ | Endpoint/product names | Scrape, Crawl, Map, Search `[PRIOR]` | Search, Scrape, Interact, Map, Crawl, Agent |

---

## 2. Nango: https://www.nango.dev

| ✓ | Fact | Candidate | Verified value / ABSENT |
|---|---|---|---|
| ☑ | Product category | Product integrations / unified API `[PRIOR]` | "Connect your product & agents to 1,000+ APIs" |
| ☑ | Pre-built integrations count | `[BLANK]` headline number | 1,000+ APIs |
| ✗ | Funding line | `[BLANK]` | ABSENT |

**https://www.nango.dev/pricing**

| ✓ | Fact | Candidate | Verified value / ABSENT |
|---|---|---|---|
| ☑ | Free tier exists | `[BLANK]` | Yes, "Free" |
| ⚑ | Paid tier names | `[BLANK]` | Pay-as-you-go, Enterprise |

---

## 3. Composio: https://composio.dev

| ✓ | Fact | Candidate | Verified value / ABSENT |
|---|---|---|---|
| ☑ | Product category | Tool/auth infra for AI agents `[PRIOR]` | "Give your AI secure access to 1,500+ apps in minutes" |
| ☑ | Tools/integrations count | `[BLANK]` headline number | 1,500+ apps |
| ⚑ | Named framework integrations | `[BLANK]` | Claude Code, ChatGPT/Codex, Cursor, MCP |

**https://composio.dev/pricing**

| ✓ | Fact | Candidate | Verified value / ABSENT |
|---|---|---|---|
| ☑ | Free tier exists | `[BLANK]` | Yes, "Hobby" |
| ☑ | Paid tier names | `[BLANK]` | Pro, Enterprise |

---

## 4. Mobbin: https://mobbin.com

> Expected JS-heavy. If a provider returns an empty shell here, that is a
> genuine result, not a bug to work around.

| ✓ | Fact | Candidate | Verified value / ABSENT |
|---|---|---|---|
| ☑ | Product category | Design reference / UI pattern library `[PRIOR]` | UI & UX design inspiration library |
| ⚑ | Screens or apps count | `[BLANK]` | 621,500+ screens |
| ⚑ | Platforms covered | `[BLANK]` | iOS, Web |

**https://mobbin.com/pricing**

| ✓ | Fact | Candidate | Verified value / ABSENT |
|---|---|---|---|
| ⚑ | Free tier exists | `[BLANK]` | Not confirmed (page blocked the verification fetch) |
| ⚑ | Paid tier names/prices | `[BLANK]` | Not confirmed (page blocked the verification fetch) |

---

## 5. Brickanta: https://brickanta.com

| ✓ | Fact | Candidate | Verified value / ABSENT |
|---|---|---|---|
| ☑ | Product category | AI agents for construction `[YOU]` | "the agentic AI platform for construction" |
| ✗ | HQ city | Stockholm `[YOU]` | ABSENT on homepage (moved to YC page below) |
| ⚑ | Named product(s) | `[BLANK]` | Agents for bidding, procurement, compliance, quality assurance |
| ✗ | Pricing published | `[BLANK]` | ABSENT, not_applicable |

**https://www.ycombinator.com/companies/brickanta**

| ✓ | Fact | Candidate | Verified value / ABSENT |
|---|---|---|---|
| ☑ | YC batch | F25 `[YOU]` | Fall 2025 (F25) |
| ☑ | HQ city | Stockholm `[YOU]` | Stockholm |

---

## 6. Dataleap: https://dataleap.ai

> Resolved: each page is scored against its own wording.

| ✓ | Fact | Candidate | Verified value / ABSENT |
|---|---|---|---|
| ☑ | Product category / tagline | "agentic OS" `[YOU]` | "The Agentic Operating System for Enterprises" |
| ✗ | Named product(s) | `[BLANK]` | ABSENT |
| ✗ | Pricing published | `[BLANK]` | ABSENT, not_applicable |

**https://www.ycombinator.com/companies/dataleap**

| ✓ | Fact | Candidate | Verified value / ABSENT |
|---|---|---|---|
| ☑ | Tagline | "AI Employees for the Enterprise" | "AI Employees for the Enterprise" |
| ☑ | YC batch | Summer 2024 | Summer 2024 |
| ☑ | HQ | San Francisco | San Francisco |

---

## 7. Manufact: https://manufact.com

| ✓ | Fact | Candidate | Verified value / ABSENT |
|---|---|---|---|
| ☑ | Product category | MCP infrastructure `[YOU]` | "The MCP Cloud" |
| ☑ | Open-source SDK name | `mcp-use` `[YOU]` | mcp-use (TypeScript and Python) |
| ⚑ | Pricing published | `[BLANK]` | Yes: Free, Hobby, Startup, Enterprise |
| ✗ | HQ location | `[BLANK]` | ABSENT |

**https://www.ycombinator.com/companies/manufact**

| ✓ | Fact | Candidate | Verified value / ABSENT |
|---|---|---|---|
| ⚑ | YC batch | S25 `[YOU]` | Not confirmed (page did not load in the verification fetch) |

---

## 8. Arcade.dev: https://www.arcade.dev

| ✓ | Fact | Candidate | Verified value / ABSENT |
|---|---|---|---|
| ☑ | Product category | Tool-calling / auth infra for AI agents `[PRIOR]` | "The actions runtime for enterprise AI agents" |
| ☑ | Auth/OAuth positioning | `[BLANK]` | Authentication runs against your IdP; authorization is delegated |
| ✗ | Funding line | `[BLANK]` | ABSENT |

**https://www.arcade.dev/pricing**

| ✓ | Fact | Candidate | Verified value / ABSENT |
|---|---|---|---|
| ☑ | Free tier exists | `[BLANK]` | Yes, "Free" |
| ☑ | Paid tier names | `[BLANK]` | Team, Enterprise |

---

## 9. Notion: https://www.notion.com/pricing

| ✓ | Fact | Candidate | Verified value / ABSENT |
|---|---|---|---|
| ☑ | Free plan exists | Yes `[PRIOR]` | Yes, "Free" |
| ☑ | Paid tier names | Plus, Business, Enterprise `[PRIOR]` | Plus, Business, Enterprise |

**https://www.notion.com**

| ✓ | Fact | Candidate | Verified value / ABSENT |
|---|---|---|---|
| ☑ | Named products beyond core | Notion AI, Notion Calendar, Notion Mail `[PRIOR]` | Notion AI, Agents, AI Meeting Notes, Enterprise Search, Notion Calendar (Notion Mail not shown) |

**https://www.notion.com/about**

| ✓ | Fact | Candidate | Verified value / ABSENT |
|---|---|---|---|
| ✗ | Founded year | 2013 `[PRIOR]` | ABSENT on this page |
| ✗ | Founder name | Ivan Zhao `[PRIOR]` | ABSENT on this page |

---

## 10. Linear: https://linear.app/pricing

| ✓ | Fact | Candidate | Verified value / ABSENT |
|---|---|---|---|
| ☑ | Free plan exists | Yes `[PRIOR]` | Yes, "Free" |
| ☑ | Paid tier names | Basic, Business, Enterprise `[PRIOR]` | Basic, Business, Enterprise |

**https://linear.app**

| ✓ | Fact | Candidate | Verified value / ABSENT |
|---|---|---|---|
| ☑ | Core concept names | Issues, Projects, Cycles, Initiatives `[PRIOR]` | Issues, Projects, Cycles, Initiatives |

**https://linear.app/about**

| ✓ | Fact | Candidate | Verified value / ABSENT |
|---|---|---|---|
| ☑ | Founded year | 2019 `[PRIOR]` | 2019 |
| ☑ | Founder name | Karri Saarinen `[PRIOR]` | Karri Saarinen, Jori Lallo, Tuomas Artman |

---

## Totals

| Status | Count |
|---|---|
| ☑ scored | 34 |
| ⚑ excluded until confirmed | 9 |
| ✗ absent / not_applicable | 9 |

Facts marked ☑ form the key. Rows still marked ⚑ are excluded. If you confirm
one in the browser, change ⚑ to ☑ before the run.

## Decision

Pricing absent: not scored. Recorded as not_applicable.