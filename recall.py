"""Where memory meets the pipeline: establish identity, reusing a recent run.

identify_company costs one LLM call and up to two searches. For a company
already researched under a known domain, that work has been done, and a
founder tracking the same competitor every month pays for it again every
time. This module decides when to reuse it instead.

It is deliberately NOT part of pipeline.py. pipeline.py stays memory-free,
so run_eval.py -- which calls it directly -- exercises the agent with no
stored history influencing the result. What keeps evaluation honest is the
layering, not a flag someone has to remember to set.

Two rules decide everything here.

STRONG KEYS ONLY. A key is strong only when it came from a domain. Reuse
needs that: "Sprout Design" naming one company today and a different one
next month is a collision this repo already contains twice. A weak key gets
no memory at all, not even as a hint. Offering the model a past run's guess
as a candidate would bias it toward repeating a misidentification, and an
ambiguous name is exactly where this pipeline is meant to stop rather than
guess.

FRESH ONLY, AND SAID OUT LOUD. The age limit lives in memory.py. A reused
identity is reported with the date it was established, in the terminal, in
the web UI and in the report, because a cached claim otherwise reads exactly
like a freshly established one.
"""

import re

import memory
import pipeline
from schemas import CompanyIdentity

# A figure only counts as a price when a currency symbol anchors it. Without
# that anchor, "AGPL-3.0" reads as the numbers 3 and 0.
_PRICE = re.compile(r"[$£€]\s?(\d+(?:[.,]\d+)?)")


def _price_figures(text) -> frozenset:
    return frozenset(_PRICE.findall(text or ""))


def _pricing_change(before, after):
    """(before, after) when the FIGURES differ, else (None, None).

    Rewording is not a price move. Two live runs described ClickUp as "$7
    /user/month ... $12" and "from $7/user/month ... $12 (billed annually)":
    identical figures, different prose. Comparing the strings called that a
    price change, which is the most misleading thing this section could say.

    Deliberately conservative. When either side quotes no figure at all,
    nothing is reported, even though the prose differs: one run finding a
    price and the other not is missing data, not a change in the market.
    """
    mine, theirs = _price_figures(before), _price_figures(after)
    if not (mine and theirs) or mine == theirs:
        return None, None
    return before, after

# How many remembered websites to offer at once. A list this long is already
# a sign the name is ambiguous; a longer one is a wall of text to read.
MAX_CANDIDATES = 5


def _normalised(name: str) -> str:
    """A name reduced to what two spellings of one company share.

    Letters and digits only, case folded, so "Sprout Design Pvt. Ltd" and
    "sprout design pvt ltd" match. casefold rather than lower because it
    also folds cases lower() leaves alone, such as the German sharp s.
    """
    return "".join(ch for ch in (name or "") if ch.isalnum()).casefold()


def find_candidates(
    name: str,
    path: str | None = None,
    now=None,
) -> list[dict]:
    """Websites this company name has resolved to before, newest first.

    This exists because of an asymmetry that makes the obvious lookup
    useless: a run is FILED under its domain, but someone typing a name
    alone can only ask about a name. Those two never meet, so a name-only
    run can never find its own history by key. Matching on the stored
    company_name is the only route to it.

    Returns at most MAX_CANDIDATES entries, one per distinct key, each with
    key, website, run_at and age_days. Several entries mean the name is
    genuinely ambiguous, which is the user's to resolve: nothing here picks
    one, and nothing is filtered out for being old. Age is reported so the
    user can judge it.

    Weak keys are skipped. A name-keyed record is a past run that could not
    establish a domain either, so it has no website to offer. Records whose
    timestamp cannot be read are skipped too, since a candidate shown
    without a date is a suggestion with no evidence attached.
    """
    wanted = _normalised(name)
    if not wanted:
        return []

    candidates: list[dict] = []
    seen: set[str] = set()

    for record in memory.read_all_runs(path):
        key = record.get("key")
        if not key or key in seen or not record.get("key_is_strong"):
            continue
        if _normalised(record.get("company_name", "")) != wanted:
            continue

        age_days = memory.record_age_days(record, now)
        if age_days is None:
            continue

        identity = record.get("identity") or {}
        seen.add(key)
        candidates.append({
            "key": key,
            # The resolved website first, then whatever was typed, then the
            # key itself, which is a domain and usable as a URL.
            "website": identity.get("website") or record.get("company_url") or key,
            "run_at": record.get("run_at", ""),
            "age_days": age_days,
        })

        if len(candidates) == MAX_CANDIDATES:
            break

    return candidates


def _identity_from(recalled: dict) -> CompanyIdentity:
    """Rebuild a CompanyIdentity from a stored one.

    confident_match is True because only confident runs reach the ledger:
    both UIs stop before writing a report when identity is ambiguous, so a
    stored identity is one that already passed that gate.
    """
    return CompanyIdentity(
        description=recalled["description"],
        location=recalled.get("location"),
        website=recalled.get("website"),
        # Carried through because verification reads it. memory.py refuses
        # to recall an identity that has none, so this is never empty here;
        # rebuilding a partial identity would feed the verifier "NOT
        # ESTABLISHED" and undo the comparison it was added for.
        scale_and_stage=recalled.get("scale_and_stage"),
        confident_match=True,
        ambiguity_note=None,
    )


def _domain_of(entry) -> str:
    """A stored competitor's derived domain, or "" for an older record."""
    return (entry.get("competitor_domain") or "").strip().casefold()


# A trailing parenthetical is how the model names a parent company, and it
# comes and goes between runs: two live runs produced "Jira (Atlassian)" and
# "Jira" for the same product, which then read as one company leaving and
# another arriving. Only a TRAILING parenthetical is removed, so a name that
# is nothing but a parenthetical still compares as itself.
_TRAILING_PARENTHETICAL = re.compile(r"\s*\([^()]*\)\s*$")


def _match_name(name: str) -> str:
    """The name used for comparing two runs. Display keeps the full name.

    Separate from _normalised, which find_candidates uses to match the
    company the user typed. That one must stay strict: it decides which
    history to offer, where a wrong match means researching the wrong
    company.
    """
    stripped = _TRAILING_PARENTHETICAL.sub("", name or "")
    return _normalised(stripped or name)


def since_last_run(
    key: str,
    key_is_strong: bool,
    competitors,
    excluded_names=(),
    current_model_resolved=(),
    current_retrieval_provider: str = "",
    path: str | None = None,
    now=None,
) -> dict | None:
    """Compare this run's competitors with the previous run's, or None.

    Returns None, meaning no section is written at all, when memory is off,
    when there is no prior record for this key, or when the key is weak. A
    weak key is a guess from a name, and comparing two runs that may be
    about two different companies would invent a trend out of an ambiguity.

    The newest prior record is used. The current run's own record has not
    been written yet at the point a report is built, so "newest" is already
    the previous run; nothing has to be excluded by hand.

    Entirely deterministic. No model is asked to summarise anything here:
    the whole value of this section is that it is arithmetic over two
    stored lists, so it cannot invent a change that did not happen.
    """
    if not key or not key_is_strong:
        return None

    try:
        records = memory.read_runs(key, path)
    except OSError:
        return None

    if not records:
        return None

    previous = records[0]
    prior = previous.get("competitors") or []

    prior_by_domain = {}
    prior_by_name = {}
    for entry in prior:
        domain = _domain_of(entry)
        if domain:
            prior_by_domain.setdefault(domain, entry)
        prior_by_name.setdefault(_match_name(entry.get("name", "")), entry)

    matched_entries = []
    new_names = []
    still_present = []

    for competitor in competitors:
        name = getattr(competitor, "name", "") or ""
        domain = memory.competitor_domain(competitor)

        entry = prior_by_domain.get(domain) if domain else None
        matched_by_name = False

        if entry is None:
            candidate = prior_by_name.get(_match_name(name))
            # Name is a fallback only when one side has no domain. Two
            # different domains mean two different companies, whatever the
            # names say, so no name match can override that.
            if candidate is not None and not (domain and _domain_of(candidate)):
                entry, matched_by_name = candidate, True

        if entry is None:
            new_names.append(name)
            continue

        matched_entries.append(id(entry))
        before, after = _pricing_change(
            entry.get("pricing"), getattr(competitor, "pricing", None))
        still_present.append({
            "name": name,
            "matched_by_name": matched_by_name,
            "pricing_before": before,
            "pricing_after": after,
        })

    excluded = {_match_name(name) for name in excluded_names}
    not_found = [
        entry.get("name", "") for entry in prior
        if id(entry) not in matched_entries
        and _match_name(entry.get("name", "")) not in excluded
    ]

    previous_model = list(previous.get("model_resolved") or [])
    previous_provider = previous.get("retrieval_provider") or ""
    current_model = list(current_model_resolved or [])
    provenance = None
    if (previous_model and current_model and previous_model != current_model) or (
            previous_provider and current_retrieval_provider
            and previous_provider != current_retrieval_provider):
        provenance = {
            "previous_model": previous_model,
            "current_model": current_model,
            "previous_provider": previous_provider,
            "current_provider": current_retrieval_provider,
        }

    return {
        "previous_run_at": previous.get("run_at", ""),
        "age_days": memory.record_age_days(previous, now),
        "provenance_changed": provenance,
        "new": new_names,
        "not_found": not_found,
        "still_present": still_present,
    }


def establish_identity(
    company_name: str,
    company_url: str,
    run,
    path: str | None = None,
    allow_recall: bool = True,
) -> tuple[CompanyIdentity | None, dict | None]:
    """Identify the company, reusing a recent run when one can be trusted.

    Returns (identity, recalled). `recalled` is the stored record's payload
    when memory was used and None when the live step ran, so callers can
    label a reused identity with its date. `identity` is None only when the
    live step failed to produce one, exactly as before.

    `run` is passed straight through to the live step, which needs it for
    its source ledger. It is required even though a recalled identity never
    touches it: a caller that has no run has no business starting one.

    allow_recall=False forces the live step even when a fresh record exists.
    Both UIs expose that, because a reused identity is still a judgement the
    user must be able to overrule: they may know the company has rebranded,
    moved or been acquired since, and no age limit can know that for them.
    """
    key, key_is_strong = memory.canonical_key(company_url, company_name)

    if key_is_strong and allow_recall:
        # Reads are best-effort, like the writes: an unreadable ledger must
        # cost the user a shortcut, not their run.
        try:
            recalled = memory.recall_identity(key, path)
        except OSError:
            recalled = None

        if recalled:
            return _identity_from(recalled), recalled

    return pipeline.identify_company(company_name, company_url, run), None
