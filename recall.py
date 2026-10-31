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

import memory
import pipeline
from schemas import CompanyIdentity

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
        confident_match=True,
        ambiguity_note=None,
    )


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
