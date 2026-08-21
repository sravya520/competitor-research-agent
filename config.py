"""Shared configuration: API clients, model choice, and retry policy."""

import os

import httpx
from dotenv import load_dotenv
from google import genai
from google.genai import errors
from tavily import TavilyClient
from tenacity import retry_if_exception, stop_after_attempt, wait_exponential

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


# Shared by every API call in pipeline.py. reraise=True means the original
# exception surfaces after the last attempt, instead of a tenacity wrapper.
RETRY_SETTINGS = dict(
    stop=stop_after_attempt(4),
    wait=wait_exponential(multiplier=2, min=2, max=30),
    retry=retry_if_exception(is_retryable_error),
    before_sleep=log_retry,
    reraise=True,
)
