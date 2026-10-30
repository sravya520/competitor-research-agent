"""Shared configuration: API clients, model choice, and retry policy."""

import os

import httpx
from dotenv import load_dotenv
from google import genai
from google.genai import errors
from tavily import TavilyClient
from tenacity import (
    retry_if_exception,
    wait_exponential,
    wait_exponential_jitter,
)

load_dotenv()

# Flash-Lite is used during development because the free tier allows far more
# requests per day than the larger models. Quotas are tracked per model.
MODEL = "gemini-flash-lite-latest"

SYSTEM_INSTRUCTION = """You are a startup competitive-research analyst.
You research companies and produce clear, structured competitor analysis
for startup founders making strategic decisions."""

gemini_client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
tavily_client = TavilyClient(api_key=os.environ["TAVILY_API_KEY"])


# A provider error can carry RetryInfo saying how long to wait. Waiting
# longer than this inside one request is pointless: the caller is blocked on
# it, and a daily quota measured in hours will not clear. Beyond this, the
# right answer is to fail at once and say so. Found live: an exhausted daily
# quota said "retry in 15h10m" and was retried four times anyway, which
# bought nothing but four more rejections and 14 seconds of backoff.
MAX_SUGGESTED_WAIT_SECONDS = 60

# Quota names whose window cannot open inside one request. The real payload
# from an exhausted free tier names its quota outright:
#
#   quotaId: GenerateRequestsPerDayPerProjectPerModel-FreeTier
#   description: Generate content requests per day limit exceeded on Free Tier
#
# which is a better signal than any duration, because it says what kind of
# limit was hit rather than how long this particular rejection suggests
# waiting. A per-minute quota is deliberately absent: that one does clear in
# seconds and is worth retrying.
NON_CLEARING_QUOTA_MARKERS = ("perday", "per day", "per_day",
                              "perhour", "per hour", "per_hour",
                              "daily")


def retry_after_seconds(exception: BaseException | None) -> float | None:
    """How long the provider suggested waiting, or None if it did not.

    Google puts it in a RetryInfo entry inside the error payload, as a
    duration string like "54616s".
    """
    for entry in _error_details(exception):
        if not str(entry.get("@type", "")).endswith("RetryInfo"):
            continue
        try:
            return float(str(entry.get("retryDelay", "")).strip().rstrip("s"))
        except ValueError:
            return None

    return None


def _error_details(exception: BaseException | None) -> list:
    """The google.rpc detail entries on an APIError, if any.

    APIError.details holds the whole response body, so the entries are
    nested two levels in.
    """
    if not isinstance(exception, errors.APIError):
        return []

    payload = getattr(exception, "details", None)
    if not isinstance(payload, dict):
        return []

    entries = (payload.get("error") or {}).get("details") or []
    return [entry for entry in entries if isinstance(entry, dict)]


def exhausted_quotas(exception: BaseException | None) -> list[str]:
    """Names and descriptions of the quotas a QuotaFailure says were hit.

    Returned as plain text rather than parsed: the useful content is spread
    across quotaId, quotaMetric and description, and which of them carries
    the word "day" has already varied between payloads.
    """
    found = []
    for entry in _error_details(exception):
        if not str(entry.get("@type", "")).endswith("QuotaFailure"):
            continue
        for violation in entry.get("violations") or []:
            if not isinstance(violation, dict):
                continue
            found.extend(str(violation.get(field, ""))
                         for field in ("quotaId", "quotaMetric", "description")
                         if violation.get(field))
    return found


def hit_a_non_clearing_quota(exception: BaseException | None) -> bool:
    """True when the exceeded quota is one that cannot clear in seconds.

    The main signal for refusing to retry. A daily or hourly allowance is
    spent until its window rolls over, so no amount of waiting inside this
    request helps, whatever delay the error happens to suggest.
    """
    haystack = " ".join(exhausted_quotas(exception)).casefold()
    return any(marker in haystack for marker in NON_CLEARING_QUOTA_MARKERS)


def short_reason(exception: BaseException | None) -> str:
    """A few words naming a failure, for a one-line retry log."""
    if isinstance(exception, errors.APIError):
        return f"{exception.code} {exception.status}"
    if exception is None:
        return "unknown"
    return type(exception).__name__


def is_retryable_error(exception: BaseException) -> bool:
    """True only for failures that a later attempt might actually survive.

    A 404 (e.g. a retired model name) will fail identically forever, so
    retrying it just burns time and quota.

    Also covers httpx.TransportError — a raw connection drop (found live,
    via eval: RemoteProtocolError during a Tavily call). It carries no HTTP
    status to check, but a dropped connection is inherently transient, so
    it's always worth one more attempt.
    """
    if isinstance(exception, errors.APIError):
        if exception.code not in (429, 500, 502, 503, 504):
            return False

        # Retry only when waiting can actually help, and prefer what the
        # error SAYS over how long it suggests waiting. An exhausted daily
        # allowance is spent until its window rolls over, so it is hopeless
        # even if the payload carries no RetryInfo at all.
        if hit_a_non_clearing_quota(exception):
            return False

        # Fallback for anything that does not name its quota: a suggestion
        # measured in hours is the provider saying this request cannot
        # succeed now, whatever the code is, so take it at its word.
        suggested = retry_after_seconds(exception)
        return suggested is None or suggested <= MAX_SUGGESTED_WAIT_SECONDS

    return isinstance(exception, httpx.TransportError)


def log_retry(retry_state) -> None:
    """One line per retry: which attempt, and a few words on why.

    It used to print the whole exception. A Gemini quota error embeds its
    entire JSON payload in its message, so four retries filled the terminal
    with four screens of near-identical text and buried the actual outcome.
    The full exception is still logged once, by the handler that gives up.
    """
    print(f"[retry] attempt {retry_state.attempt_number} failed "
          f"({short_reason(retry_state.outcome.exception())}), retrying...")


# A 503 means the model is overloaded, not that the request is wrong. The
# previous budget of 4 attempts spent roughly 14 seconds of backoff, which a
# demand spike routinely outlasts: a live 503 reached a user as a generic
# failure even though retrying would have worked. These two codes get more
# attempts and jitter, so a fleet of clients does not retry in lockstep.
#
# Deliberately narrower than is_retryable_error below. 429 keeps the original
# budget: when it is a daily quota, waiting longer inside one request cannot
# help, and the app tells the user to come back later instead.
RETRY_WIDENED_CODES = (503, 504)

RETRY_ATTEMPTS_DEFAULT = 4
RETRY_ATTEMPTS_WIDENED = 6


def _is_widened(exception: BaseException | None) -> bool:
    return (isinstance(exception, errors.APIError)
            and exception.code in RETRY_WIDENED_CODES)


def _last_exception(retry_state):
    outcome = getattr(retry_state, "outcome", None)
    if outcome is None or not outcome.failed:
        return None
    return outcome.exception()


def attempt_limit(retry_state) -> int:
    """How many attempts this failure is allowed, by cause."""
    if _is_widened(_last_exception(retry_state)):
        return RETRY_ATTEMPTS_WIDENED
    return RETRY_ATTEMPTS_DEFAULT


def stop_by_cause(retry_state) -> bool:
    return retry_state.attempt_number >= attempt_limit(retry_state)


_wait_standard = wait_exponential(multiplier=2, min=2, max=30)
_wait_widened = wait_exponential_jitter(initial=2, max=45, jitter=3)


def wait_by_cause(retry_state) -> float:
    """What the provider asked for, else jittered backoff for an overloaded
    provider, else the original curve, so 429 timing is unchanged."""
    exception = _last_exception(retry_state)

    # A short, explicit suggestion beats guessing with a curve: the provider
    # knows when its own window opens. Long suggestions never reach here,
    # because is_retryable_error refuses to retry them at all.
    suggested = retry_after_seconds(exception)
    if suggested is not None:
        return min(suggested, MAX_SUGGESTED_WAIT_SECONDS) + 0.5

    if _is_widened(exception):
        return _wait_widened(retry_state)
    return _wait_standard(retry_state)


# Shared by every API call in pipeline.py. reraise=True means the original
# exception surfaces after the last attempt, instead of a tenacity wrapper.
RETRY_SETTINGS = dict(
    stop=stop_by_cause,
    wait=wait_by_cause,
    retry=retry_if_exception(is_retryable_error),
    before_sleep=log_retry,
    reraise=True,
)
