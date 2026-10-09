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
        return exception.code in (429, 500, 502, 503, 504)
    return isinstance(exception, httpx.TransportError)


def log_retry(retry_state) -> None:
    print(f"[retry] attempt {retry_state.attempt_number} failed "
          f"({retry_state.outcome.exception()}), retrying...")


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
    """Jittered backoff for an overloaded provider, the original curve
    otherwise, so 429 timing is unchanged."""
    if _is_widened(_last_exception(retry_state)):
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
