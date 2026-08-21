"""Every prompt the system sends, in one place.

In an LLM application most iteration happens in prompt text, not code, so the
prompts are kept together where they can be read and compared side by side.
Each constraint here exists because of an observed failure — the comments say
which one.
"""

from schemas import CompanyIdentity, Competitor


def identity_prompt(company_name: str, company_url: str, anchor_content: str) -> str:
    """Step 0 — establish WHICH company we mean before researching anything.

    Without this step, a common company name silently pulls in unrelated
    same-named companies from other countries.
    """
    if company_url:
        anchor = f"""The user pointed at this specific page as the company they mean:
{company_url}

Here is the actual content of that page:

{anchor_content}

This page is the authoritative answer to WHICH company is meant — it
outranks anything you find by searching. If the page content above
describes a real company, set confident_match to True and base your
description on it. Only set confident_match to False if the page could
not be read at all. You may search to fill in details the page doesn't
cover, but never let a same-named company from search results override
the identity established by this page."""
    else:
        anchor = """No URL was provided, so you must determine the company's identity by
searching. If your searches turn up evidence that MORE THAN ONE distinct,
unrelated company shares this exact name (e.g. a same-named company
registered in a different country), set confident_match to False and
explain the mix-up in ambiguity_note — do not guess which one the user
probably means."""

    return f"""Identify and describe the company "{company_name}".

{anchor}

Describe what this specific company actually does, who it serves, and
where it is based — do not assume it is large or established.

Be economical — at most 2 searches.
"""


def research_prompt(company_name: str, identity: CompanyIdentity) -> str:
    """Step 1 — find competitors, scoped to the confirmed company."""
    return f"""The company "{company_name}" has been confirmed as:

{identity.description}
Location: {identity.location or 'unknown'}

Research the competitive landscape for THIS SPECIFIC company — not any
other company that happens to share a similar name.

Be economical — roughly 2-3 searches to discover candidates, plus a small
number of extractions to verify the most promising ones. Do not verify
every single candidate; use judgment about which are worth confirming.

Identify the top 5 most relevant competitors — genuinely comparable in
scale and stage to {company_name}. Competitors do NOT need to be in the
same country or region as {company_name} — what matters is whether they
genuinely compete for similar customers or deals, not where they are
headquartered. Every competitor MUST be a specific, real, named company
you found evidence of — never a generic category or description (e.g.
"local boutique agencies", "freelance designers" are NOT acceptable
answers). If your searches do not surface enough specific real
competitors, return fewer than 5 rather than padding the list with vague
placeholders — an honest, shorter list is far more useful than a
complete-looking but generic one.

For each competitor, include the specific source URL(s) — from the actual
search results you were given — that support what you say about them.
Only cite a URL that genuinely appeared in your search results; never
construct or guess at a URL.

You have TWO tools, and how you use them matters. Search results are
often dominated by "best agencies" roundup content, marked inline as
[ROUNDUP/LISTICLE CONTENT] — that content is fine for discovering a
candidate's NAME, but its stats (success rates, retention percentages,
exact team sizes) are frequently unverifiable or invented, since these
pages are usually published by a company ranking itself first. When a
listicle names a promising candidate, use extract_company_page on that
company's OWN site (search for it if you don't already have the URL) to
ground its actual profile — positioning, services, scale — in a primary
source rather than in the roundup's claims. If a competitor's details
still rest on only a listicle after trying this, say so plainly in
why_relevant rather than repeating its numbers as established fact.

Also summarize overall market trends, potential market gaps/opportunities,
and potential threats for {company_name}.
"""


def verification_prompt(
    company_name: str,
    identity: CompanyIdentity,
    competitors: list[Competitor],
) -> str:
    """Step 2 — an independent second opinion on the proposed competitors.

    Two things matter here. The competitors are NUMBERED, because pairing
    verdicts back to competitors by name breaks whenever the model
    abbreviates or expands a name. And the target company's own description
    is included: an earlier version omitted it, so the verifier was asked to
    judge "comparable scale" while blind to the target's scale, and waved
    through agencies fifty times larger than a two-person studio.

    Independence means withholding the reasoning that produced the answer,
    not withholding the subject of the question.
    """
    summaries = ""
    for i, competitor in enumerate(competitors):
        summaries += f"[{i}] Name: {competitor.name}\n"
        summaries += f"Why relevant: {competitor.why_relevant}\n"
        summaries += f"Positioning: {competitor.positioning}\n"
        summaries += f"Target customers: {competitor.target_customers}\n\n"

    return f"""A researcher proposed these competitors for "{company_name}".

THE TARGET COMPANY — this is what a competitor must be comparable to:
{identity.description}
Location: {identity.location or 'unknown'}

PROPOSED COMPETITORS:
{summaries}

For EACH numbered competitor above, independently assess TWO things:
1. Is it a SPECIFIC, real, named company — not a generic category or
   description (e.g. "local boutique agencies", "freelance designers")?
   Reject it if it is not a real, identifiable company.
2. Is it genuinely comparable in SCALE and STAGE to the target company
   described above? Compare like with like: if the target is a tiny
   studio of a few people, an agency of 50+ staff serving enterprise
   clients is NOT a peer, even in the same industry — reject it.
   Geography alone is never disqualifying; only scale/stage mismatch is.

Be skeptical — do not assume a competitor is valid just because it was
proposed. Return exactly one verification entry per competitor, echoing
its `index` number and name, with `verified=False` if it fails either
check above.
"""
