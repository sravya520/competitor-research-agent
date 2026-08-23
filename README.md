# Competitor Research Agent

An agentic AI tool that researches a startup's competitive landscape and produces a sourced Markdown report a founder can actually act on.

Give it a company name — and optionally a URL — and it identifies the company, decides for itself what to search, finds comparable competitors, independently verifies them, asks you to approve the result, and writes a report that cites where every claim came from.

**🔗 Live app: [competitor-research-agent-application.streamlit.app](https://competitor-research-agent-application.streamlit.app/)**

---

## Why this exists

You could ask a chatbot "who are Acme's competitors?" and get an answer in seconds. That answer has three problems:

1. **It may be invented.** Ask about a small company and a language model will often produce a confident, well-formatted profile of a company it knows nothing about.
2. **You can't check it.** No sources, no way to tell which parts are solid and which are guesses.
3. **It isn't reproducible.** Ask twice, get two different answers, with no record of what was considered or rejected.

This tool is built around the assumption that **the model will sometimes be wrong**, and that the job of the surrounding system is to catch it, show its work, and stop rather than guess. What it sells is not intelligence — it's **traceability**.

---

## What it does

```mermaid
flowchart TD
    A["Company name<br/>(+ optional URL)"] --> B[Identify]
    B -->|ambiguous| STOP["Stop and explain<br/>rather than guess"]
    B -->|confirmed| C[Research]
    C --> D[Verify]
    D --> E[Human review]
    E --> F["Markdown report<br/>with sources"]

    T(["search_web<br/>extract_company_page"]) -.-> B
    T -.-> C
```

| Step | What happens | What it protects against |
|---|---|---|
| **Identify** | Confirms which company is meant. A URL, if given, outranks search results. | Researching a different company that shares the name |
| **Research** | The agent chooses its own search queries, iterating until it has enough. | Stale training data; one fixed query missing the point |
| **Verify** | A **separate** call re-checks each competitor: is it a real, named company, and is it comparable in scale? | Generic placeholders; competitors 50× the target's size |
| **Check** | Deterministic checks: every cited URL must have actually been fetched; no competitor may be a generic category. | Fabricated or altered citations |
| **Review** | You see every competitor, every rejection, and every flagged problem, and can remove any. | Everything the automated checks missed |
| **Report** | Markdown with per-competitor sources, exclusions, and stated limitations. | Unverifiable claims presented as fact |

---

## Setup

Requires Python 3.11+. Both API keys have free tiers and need no credit card.

```bash
git clone <your-repo-url>
cd competitor-research-agent

python -m venv venv
venv\Scripts\activate        # Windows
source venv/bin/activate     # macOS / Linux

pip install -r requirements.txt
```

Create a `.env` file in the project root:

```
GEMINI_API_KEY=your-key-here
TAVILY_API_KEY=your-key-here
```

- **Gemini API key** — [Google AI Studio](https://aistudio.google.com) (free tier, no card)
- **Tavily API key** — [tavily.com](https://tavily.com) (1,000 searches/month free, no card)

> A Gemini *app* subscription is not the same thing as an API key. The key comes from AI Studio.

---

## Usage

```bash
python main.py
```

```
Enter a company or startup name: Sprout Design
Company website or LinkedIn URL (optional, press Enter to skip): https://sproutdesign.framer.website/

[extract] https://sproutdesign.framer.website/

Confirmed: Sprout Design is a boutique design studio founded by two IIT alumni,
combining product design, website design, and design strategy for startups.

[search] boutique product design studio MVP agency startup website design

================================================================
REVIEW
================================================================

Automatically excluded by verification:
  - 500 Designs: significantly larger and more established (part of the 500 Global
    ecosystem, executing enterprise projects), representing a scale mismatch.

4 competitor(s) passed verification:

  [0] UX Cabin — Flexible, senior-level boutique design partner for lean startup teams.
  [1] Semiflat Studio — Production-ready interface design specialists.
  [2] Orbix Studio — Rapid concept-to-launch execution.
  [3] Valtorian — Zero-handoff, direct-with-founders boutique studio.

Enter the numbers of any you want REMOVED (comma-separated), or press Enter to keep all:

Report written to report-sprout-design.md
4 competitor(s) included, 1 excluded.
```

Passing a URL is optional but strongly recommended for small or common-named companies. Without one, the tool will refuse to proceed if it can't tell which company you mean — see below.

A full generated report is committed as [`example-report.md`](example-report.md).

### Web UI

```bash
streamlit run app.py
```

Same pipeline, browser-based: a form for the company and URL, live progress while it searches, checkboxes to remove competitors during review, and a download button for the finished report. `app.py` is the only file that imports Streamlit — the pipeline itself (`pipeline.py`, `evaluate.py`, `report.py`, `tools.py`) has no idea a UI exists, which is what lets both entry points share it.

**Live version:** [competitor-research-agent-application.streamlit.app](https://competitor-research-agent-application.streamlit.app/)

---

## Deployment

Deployed on [Streamlit Community Cloud](https://streamlit.io/cloud) — free, no card, deploys straight from this GitHub repo.

1. Push to GitHub (already done if you're reading this here)
2. At [share.streamlit.io](https://share.streamlit.io), sign in with GitHub → **New app** → pick this repo, branch `main`, main file `app.py`
3. Under **Advanced settings → Secrets**, add:
   ```toml
   GEMINI_API_KEY = "your-key-here"
   TAVILY_API_KEY = "your-key-here"
   ```
4. Deploy

Locally, keys come from a `.env` file (gitignored). On Streamlit Cloud there is no `.env` — `app.py` bridges `st.secrets` into environment variables before the pipeline is imported, so `config.py` and the CLI never need to know which source they came from.

---

## Design decisions

Every safeguard here exists because of a specific observed failure, not because it sounded good in theory.

**Identity is confirmed before research begins.**
Asked about a two-person studio called "Sprout Design," the system repeatedly produced polished reports about *a different company with the same name* — a UK firm, an unrelated branding studio. Names are ambiguous; a URL is not. When a URL is provided, its page content is treated as authoritative and outranks anything search returns.

**When identity is ambiguous, it stops.**
An earlier version asked the user "is this the company you meant?" and continued on a yes. That was unsafe: confirming a description that said *"no entity could be verified"* let the research step latch onto the wrong company and spend its whole budget there. Now, low confidence is a hard stop with an explanation. **Refusing to answer is a feature.**

**Verification is a separate call with no shared history.**
A model asked to re-check its own reasoning tends to agree with itself. The verifier sees the proposed competitors and the target company — but not the reasoning that produced them.

**The verifier knows the target's scale.**
An early version passed only the company *name* to the verifier, then asked "is this comparable in scale?" — a question it had no way to answer. Eighty-person agencies sailed through as peers of a two-person studio. The fix: independence means withholding the *reasoning*, never the *subject*.

**Verdicts pair by index, not by name.**
Matching verdicts to competitors by string equality on model-generated names broke whenever the model abbreviated one ("Parallel" vs. "Parallel Design Studios"), producing a report that dropped a competitor and then included it anyway. Competitors are numbered; verdicts echo the number.

**Sources are tracked in code, not by the model.**
The model attributes sources per competitor, which is useful but fallible. Separately, the tools record every URL actually fetched. The report contains both: best-effort attribution, and a list that can't be misremembered.

**Fabricated citations are detected automatically, then removed.**
Because the tools record every URL genuinely fetched, any URL the model cites that isn't in that record was invented. This check found a real case: the model was handed `.../best-mvp-agencies-for-early-stage-products` and cited `.../best-mvp-**design**-agencies-for-early-stage-products` — a plausible-looking link that would 404. No human reading the report would have caught it, sitting as it was among five genuine URLs. Detection alone isn't enough, so fabricated citations are stripped before the report is written: a broken link still looks like evidence.

**Every competitor is labelled by how corroborated it is, not just whether it has a source.**
A competitor with one citation and a competitor checked against several independent pages looked identical in earlier versions of the report — both just had a "Sources" list. Now each one is counted by DISTINCT DOMAIN (two pages on the same site aren't independent confirmation of anything) and labelled plainly: corroborated across N sources, single-source and unconfirmed, or none cited at all. Nothing gets rejected for being single-sourced — a small real company legitimately may only have its own website — but nothing is presented with more confidence than the evidence actually supports either.

**Retries are selective.**
429, 5xx, and raw connection drops (`httpx.TransportError`) are retried, with exponential backoff. A 404 from a retired model name is never retried — it will fail identically forever, so retrying it just wastes quota. Retries cover the tool calls themselves (`search_web`, `extract_company_page`), not just the top-level model calls — a gap found by a live `RemoteProtocolError` during evaluation, in a tool call that had no retry protection at all.

**Listicle content is labelled at the source, and the research step can verify past it.**
"Best agencies for X" content isn't concentrated on a few spam domains — the same domain (a real competitor's own blog) can host both their legitimate site and a self-ranking roundup. So instead of blocking domains, `search_web` tags each result whose URL path matches roundup patterns (`/blog/best-`, `-alternatives`, `-vs-`, `/resources/`), and the research step was given a second tool — `extract_company_page`, previously only used for identity — with instructions to fetch a promising candidate's own site once a listicle names them, rather than trust the listicle's stats. A new metric, `primary_source_ratio`, tracks what fraction of citations rest on non-roundup sources.

**The report publishes what it rejected.**
Most tools show only what they kept. This one lists every rejected candidate with the reason — automated *and* human — so a reader can audit the judgment, not just the conclusion.

---

## Testing a non-deterministic system

```bash
python run_eval.py              # every case
python run_eval.py Duolingo     # one case
```

Regression cases live in `eval_cases.py`, and each one exists because the system once got it wrong — early runs returned global design giants as peers of a two-person studio, then CAD-drafting firms, then generic categories. Rather than defining the single "correct" competitor list for a company (which reasonable analysts would disagree about), each case asserts something narrower and checkable: *it must stop here*, or *it must not return these*.

The cases split into two tiers, and the distinction matters:

- **Gates** — stable assertions that should never break. No fabricated URLs, no generic categories, a well-known company returns real competitors.
- **Observations** — behaviour that genuinely varies between runs, reported but never failing the suite.

That split exists because this system does live web searches. The same input can legitimately produce different results on different days — one run finds no single match for an ambiguous name and stops, another finds a registered entity and proceeds. Asserting on that would be testing what search indexed this morning, not testing this code. **A test that flakes for unrelated reasons teaches you to ignore it**, and then you ignore it when it catches something real.

Each run also reports `primary_source_ratio` — the share of citations that are not roundup/listicle content — so a change to the search strategy can be judged by a number instead of a guess.

## Project structure

```
main.py        Orchestration and human review — reads as the workflow
pipeline.py    The three LLM steps: identify, research, verify
prompts.py     All prompt text, with comments on why each constraint exists
tools.py       search_web / extract_company_page, and source tracking
schemas.py     Pydantic models defining every structured output
evaluate.py    Automatic consistency checks (fabricated URLs, generic names)
eval_cases.py  Regression cases, each one a bug that actually happened
run_eval.py    Runs the cases and reports gates vs. observations
report.py      Markdown generation
config.py      Clients, model choice, retry policy
```

Prompts live in their own file deliberately: in an LLM application, most iteration happens in prompt text rather than code, so it should be easy to read and compare.

---

## Limitations

Stated plainly here and in every generated report:

- **Source quality is improved but not solved.** Search results are still dominated by "best agencies for X" content by construction — that's what ranks for those queries. Labelling roundup content and giving the research step a way to verify candidates against their own site (see Design decisions) measurably raised the primary-source share in testing (roughly 85-90% on the reference cases, versus the earlier reports where nearly every citation traced to a listicle), but it is a mitigation, not a fix — the underlying bias in what the web publishes about small companies hasn't gone away.
- **Scale comparison is a judgment call.** Verification catches obvious mismatches but not every borderline one.
- **Coverage is not guaranteed.** The tool finds competitors that are findable; a strong competitor with no web presence will be missed.
- **Small companies remain hard.** Without a URL, a company with a common name and thin web presence may be unidentifiable — by design, the tool stops rather than guessing.

---

## Possible improvements

- A dedicated company-search API (e.g. Crunchbase-style data) instead of general web search, to attack what labelling and extraction alone can't fix
- A Streamlit interface so a non-technical founder can use it
- Caching, so re-running a company doesn't re-spend search quota

---

## Built with

Python · [Google Gemini API](https://ai.google.dev) (`google-genai`) · [Tavily](https://tavily.com) search · Pydantic · Tenacity

No agent framework. The tool-calling loop, structured outputs, and verification step are wired directly against the API — the goal was to understand the mechanics rather than inherit them.
