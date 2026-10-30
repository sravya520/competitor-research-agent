"""The run ledger: what was researched, when, and under which key.

Stage 1 of memory is write-only. Every finished run appends one JSON object
to a ledger file; nothing reads it back yet. That order is deliberate --
reads change what the agent does and can quietly poison a report, while a
write nobody consumes cannot break a run that works today. The later stages
(reuse identity, diff against the last run, learn the reviewer's
exclusions) all need this history to exist first.

Two decisions shape the rest of this module.

KEYS. Memory only works if a later run can find an earlier one, so every
run is filed under a key. Names cannot do that job: the model's own output
drifts between calls -- which is why apply_verifications() in pipeline.py
pairs competitors by index rather than by name -- and a founder typing
"Notion", "Notion Labs" or "notion.so" means one company every time. A
registered domain does not drift, so wherever a domain is known, the domain
is the key. Where none is, the key falls back to the name and is marked
weak; a weak key may inform a later run but must never let it skip
identification. This repo holds two different "Sprout Design" reports,
which is that risk in the flesh.

OPT-IN. Nothing here reads or writes anything unless MEMORY_PATH names a
file (or a caller passes an explicit path, which is how the tests avoid
touching the environment). There is no default location. A public demo
never sets it, so no visitor inherits a stranger's history and no record of
who-researched-whom accumulates unasked.

STORAGE. One JSON object per line (JSON Lines), appended. A single JSON
array would mean read-parse-append-rewrite on every run, so an interrupted
write could destroy every previous record and two Streamlit sessions could
clobber each other. Appending has neither failure mode, and the file stays
greppable. No database yet: Stage 1 runs no queries, and the functions here
are the seam to put one behind later.

Standard library only, so this module can be tested without an API key and
imported from both the CLI and the Streamlit app.
"""

import json
import os
from datetime import datetime, timezone
from urllib.parse import urlparse

# 2 added url_source and url_remembered_from. 3 added identity_established_at.
# 4 added model_resolved. Older lines simply lack those fields, and every read
# here uses .get with a fallback, so an older ledger stays readable without a
# migration.
SCHEMA_VERSION = 4

LEDGER_PATH_ENV = "MEMORY_PATH"

# How old a stored identity may be and still be reused. Deliberately
# conservative: an identity is cheap to re-establish (one call, two searches)
# and a wrong one poisons everything downstream, since every later step is
# told which company it is researching.
RECALL_MAX_AGE_DAYS = 30

# Hosts that are a directory, a profile or a publishing platform rather than
# a company. A strong key has to identify exactly one company, and these
# identify none: app.py invites a LinkedIn URL explicitly, so applying the
# domain rule to one would file every company researched that way under
# "linkedin.com", a single bucket holding everybody's history with no error
# to warn us. The same goes for a GitHub organisation page or a Medium
# publication, which are addresses on someone else's platform.
#
# Accepted consequence: a company that IS one of these, such as GitHub
# itself, gets a weak name-based key and so is never recalled from a URL.
# Rare, and the failure is a missed shortcut rather than a wrong answer.
#
# Not handled here, deliberately: hosts shared at the SUBDOMAIN level, such
# as acme.notion.site or acme.github.io. Those are already distinct keys
# because the full host is kept, so they identify one company each. Noted
# for Stage 3, which is where subdomain keying is worth revisiting.
DIRECTORY_HOSTS = {
    "crunchbase.com",
    "facebook.com",
    "github.com",
    "gitlab.com",
    "huggingface.co",
    "instagram.com",
    "linkedin.com",
    "medium.com",
    "producthunt.com",
    "twitter.com",
    "x.com",
    "youtube.com",
}


# --------------------------------------------------------------------------
# Keys
# --------------------------------------------------------------------------

def _slug(company_name: str) -> str:
    """Hyphenated lowercase form of a name, or "" if there is nothing to use.

    Same scheme as save_report() in report.py, so a key and a report
    filename derived from one name agree with each other.
    """
    cleaned = "".join(ch if ch.isalnum() else " " for ch in company_name)
    return "-".join(cleaned.split()).lower()


def _host(website: str) -> str:
    """The host of a URL: lowercased, no scheme, credentials, port or "www.".

    Returns "" when nothing host-shaped can be found.
    """
    candidate = website.strip()

    # urlparse() puts a scheme-less "notion.so/about" entirely in .path and
    # leaves .netloc empty. People type bare domains constantly, so prefix
    # "//" (a protocol-relative URL) and let urlparse do the rest.
    if "//" not in candidate:
        candidate = f"//{candidate}"

    host = urlparse(candidate).netloc.lower()
    host = host.rpartition("@")[2]   # strip any user:password@
    host = host.partition(":")[0]    # strip any :port
    return host.removeprefix("www.")


def _looks_like_host(host: str) -> bool:
    """True only for something plausibly a hostname.

    This guards the strong-key path. Both UIs take the URL as free text, and
    "hello" or "not a url" typed into that box parses into a non-empty
    netloc -- which would then be filed as a domain, giving a *strong* key
    that rests on nothing. A hostname has at least two non-empty
    dot-separated labels and no whitespace; that is crude, but it is the
    difference between a trusted key and a typo.
    """
    if not host or any(ch.isspace() for ch in host):
        return False
    labels = host.split(".")
    return len(labels) > 1 and all(labels)


def _is_directory_host(host: str) -> bool:
    """True for a directory host or any subdomain of one.

    Exact matching alone would miss "uk.linkedin.com", which is every bit
    as much a directory page as "linkedin.com" is.
    """
    return any(host == known or host.endswith(f".{known}")
               for known in DIRECTORY_HOSTS)


def canonical_key(website: str | None, company_name: str) -> tuple[str, bool]:
    """Return (key, key_is_strong) for storing this company's run history.

    A strong key is a real domain. A weak key ("name:some-company") is a
    guess from a name, and callers must not treat it as established
    identity. An empty key means the company could not be identified at
    all; a run like that is not filed, rather than filed under a bucket
    that every unidentifiable run would share.
    """
    slug = _slug(company_name)
    name_key = (f"name:{slug}", False) if slug else ("", False)

    if not website:
        return name_key

    host = _host(website)

    # A directory host is a page about the company, not the company itself,
    # so it is no better evidence of identity than the name is. Anything
    # that does not look like a host at all is weaker still.
    if not _looks_like_host(host) or _is_directory_host(host):
        return name_key

    return host, True


# --------------------------------------------------------------------------
# Records
# --------------------------------------------------------------------------

def ledger_path() -> str | None:
    """Where the ledger lives, or None when memory is switched off.

    There is no default path on purpose. Memory is opt-in: with MEMORY_PATH
    unset, nothing here reads or writes anything, and the hosted demo never
    sets it. That matters more now that reads can change what a run does --
    a visitor to a public demo should not inherit a stranger's history, and
    a file of who-researched-whom should not accumulate unasked.

    Read at call time, not import time, so a test or a deployment can point
    it elsewhere. An explicit path argument always wins over this, which is
    what lets the tests work without touching the environment.
    """
    return os.environ.get(LEDGER_PATH_ENV) or None


def enabled() -> bool:
    """Whether the environment switches memory on.

    Only for deciding what to say to the user. The functions below are
    gated on the resolved path, and an explicit path still works when this
    is False, which is how the tests stay independent of the environment.
    """
    return ledger_path() is not None


def _utc_now() -> str:
    """An unambiguous instant, e.g. 2026-10-30T11:42:08Z.

    Reports print local dates for humans; a ledger gets sorted and diffed,
    so it stores UTC.
    """
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _competitor_record(competitor) -> dict:
    """The fields a later diff needs, read off a Competitor.

    getattr rather than attribute access keeps this module free of a
    schemas.py import, so tests can pass any simple stand-in object.
    Positioning is stored because the Stage 3 diff is not only "who
    appeared and disappeared" but "who repositioned".
    """
    return {
        "name": getattr(competitor, "name", "") or "",
        "positioning": getattr(competitor, "positioning", "") or "",
        "pricing": getattr(competitor, "pricing", None),
        "sources": list(getattr(competitor, "sources", None) or []),
    }


def build_record(
    *,
    company_name: str,
    company_url: str = "",
    identity=None,
    competitors=(),
    excluded_auto=(),
    removed_by_human=(),
    problems=(),
    sources=(),
    model: str = "",
    model_resolved=(),
    retrieval_provider: str = "",
    url_source: str = "",
    url_remembered_from: str = "",
    identity_established_at: str = "",
    run_at: str | None = None,
) -> dict:
    """Assemble one ledger record. Pure: no file access, and no clock if
    run_at is supplied.

    Keyword-only on purpose -- eleven positional arguments, most of them
    lists, is a mix-up waiting to happen.

    excluded_auto and removed_by_human stay SEPARATE. Both UIs merge them
    into one list for the report, distinguished only by the English string
    "Removed by human reviewer.", and Stage 4 (learning the reviewer's
    preferences) would then have to parse prose to recover what the human
    actually chose. The split is captured here, where it still exists.
    """
    key, key_is_strong = canonical_key(
        getattr(identity, "website", None) or company_url, company_name,
    )
    stamped_at = run_at or _utc_now()

    return {
        "schema_version": SCHEMA_VERSION,
        "key": key,
        "key_is_strong": key_is_strong,
        "company_name": company_name,
        "company_url": company_url or "",
        "run_at": stamped_at,
        # When the identity in this record was LAST ESTABLISHED LIVE, which
        # is this run only if the identify step actually ran. Callers copy
        # the original date forward when they reuse one.
        #
        # Without this, age could only be measured from run_at, and since
        # every completed run writes a record, each reuse reset the age to
        # zero. An identity would be reused forever and every report would
        # claim it was established today. Found by test, not in production.
        "identity_established_at": identity_established_at or stamped_at,
        "identity": {
            "description": getattr(identity, "description", "") or "",
            "location": getattr(identity, "location", None),
            "website": getattr(identity, "website", None),
        },
        "competitors": [_competitor_record(c) for c in competitors],
        "excluded_auto": [[name, reason] for name, reason in excluded_auto],
        "excluded_by_human": list(removed_by_human),
        "problems": list(problems),
        # The alias that was configured, and the versions the API said
        # actually answered. "gemini-flash-lite-latest" is not an answer to
        # "which model produced this run"; it is a pointer that moves.
        "model": model,
        "model_resolved": list(model_resolved),
        "retrieval_provider": retrieval_provider,
        # How the URL that anchored this run was obtained: "typed", or
        # "remembered" when the user accepted one this ledger offered, with
        # the run it came from. Worth storing because a remembered URL makes
        # the run partly a consequence of an earlier one, and a chain of
        # those should be visible rather than inferred.
        "url_source": url_source,
        "url_remembered_from": url_remembered_from,
        "sources_consulted": list(sources),
    }


def append_record(record: dict, path: str) -> str:
    """Append one record as a single line. Returns the path written to.

    The path is required: whether memory is on at all is decided once, in
    record_run, rather than in every function that touches the file.
    """
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)

    # sort_keys so two records diff cleanly; ensure_ascii=False so a company
    # name with an accent stays readable in the file.
    line = json.dumps(record, ensure_ascii=False, sort_keys=True)
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(line + "\n")

    return path


def record_run(*, path: str | None = None, **fields) -> dict | None:
    """Build and append a record for a finished run.

    Returns None, and writes nothing, when memory is switched off (see
    ledger_path) or when the company could not be identified well enough to
    key it -- better no entry than one in a bucket shared by every
    unidentifiable run. Use enabled() to tell those two cases apart before
    reporting anything to the user.

    Callers wrap this: nothing in a run depends on the ledger, so failing to
    write it must never cost the user their report.
    """
    path = path or ledger_path()
    if not path:
        return None

    record = build_record(**fields)
    if not record["key"]:
        return None

    append_record(record, path)
    return record


def _parse_run_at(value) -> datetime | None:
    """Parse a stored timestamp, or None if it cannot be read.

    Anything unparseable is treated as unknown rather than as "now": a
    record whose age cannot be established must not be reused.
    """
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def record_age_days(record: dict, now: datetime | None = None) -> float | None:
    """How old a record is, in days, or None if its timestamp is unreadable.

    now is injectable so tests do not depend on the real clock.
    """
    stored = _parse_run_at(record.get("run_at"))
    if stored is None:
        return None
    return ((now or datetime.now(timezone.utc)) - stored).total_seconds() / 86400


def identity_established_at(record: dict) -> str:
    """When this record's identity was last established live.

    Falls back to run_at for ledger lines written before schema 3, where
    the two were the same thing for any record the identify step produced.
    """
    return record.get("identity_established_at") or record.get("run_at") or ""


def identity_age_days(record: dict, now: datetime | None = None) -> float | None:
    """How old the IDENTITY in a record is, not how old the record is.

    These differ on every reused identity, and only this one bounds how
    long a stale description can survive.
    """
    return record_age_days(
        {"run_at": identity_established_at(record)}, now)


def recall_identity(
    key: str,
    path: str | None = None,
    max_age_days: float = RECALL_MAX_AGE_DAYS,
    now: datetime | None = None,
) -> dict | None:
    """The most recent usable identity stored under this key, or None.

    "Usable" means it actually describes a company and is recent enough to
    still be worth trusting. What a company *is* changes far more slowly
    than who competes with it, but it does change: companies rebrand, move,
    get acquired. So this is bounded by age rather than kept forever, and
    the age is returned so a caller can say out loud how old it is.

    Returning a plain dict, not a CompanyIdentity, keeps this module free
    of a schemas.py import. The caller converts.
    """
    if not key:
        return None

    for record in read_runs(key, path):
        identity = record.get("identity") or {}
        if not identity.get("description"):
            continue

        # Measured from when the identity was established, never from when
        # this record was written: a reused identity writes a fresh record,
        # and measuring from that would renew the limit on every run.
        age = identity_age_days(record, now)
        if age is None or age > max_age_days:
            continue

        return {
            "description": identity["description"],
            "location": identity.get("location"),
            "website": identity.get("website"),
            # When the identity itself was established, which is the date
            # worth showing a user, and what a later reuse copies forward.
            "established_at": identity_established_at(record),
            # When the run that last used it happened.
            "run_at": record.get("run_at", ""),
            "age_days": age,
            "key_is_strong": bool(record.get("key_is_strong")),
        }

    return None


def read_all_runs(path: str | None = None) -> list[dict]:
    """Every record in the ledger, newest first. Empty when memory is off.

    A malformed line is skipped rather than raised: the ledger is
    append-only, so an interrupted write can leave one partial last line,
    and losing all history to one bad line would be the worse failure.

    The whole file is read because the useful questions are not all
    key-shaped. Matching a company by NAME needs every record, since a name
    cannot be turned into the domain key a run was filed under.
    """
    path = path or ledger_path()
    if not path:
        return []

    records = []
    try:
        with open(path, encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(record, dict):
                    records.append(record)
    except FileNotFoundError:
        return []

    records.sort(key=lambda record: record.get("run_at", ""), reverse=True)
    return records


def read_runs(key: str, path: str | None = None) -> list[dict]:
    """Past records for one key, newest first."""
    if not key:
        return []
    return [record for record in read_all_runs(path) if record.get("key") == key]
