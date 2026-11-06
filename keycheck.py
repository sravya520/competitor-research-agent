"""Checks that a user's own API keys work, before we save them. Returns a plain-language problem or None.

Parked with backend/vault.py: the own-keys feature is hidden, so no page calls this.

Knows nothing about Streamlit. The Gemini check lists models (free, no quota used); Tavily has no
free "who am I" call, so it runs one tiny search (one credit).
"""

from google import genai
from google.genai import errors
from tavily import TavilyClient
from tavily.errors import InvalidAPIKeyError, UsageLimitExceededError


def check_gemini(key: str) -> str | None:
    try:
        client = genai.Client(api_key=key.strip())  # keep a reference: a temporary client is closed before the lazy list is read
        next(iter(client.models.list(config={"page_size": 1})), None)
        return None
    except errors.APIError as exc:
        if exc.code in (400, 401, 403):
            return "Google did not accept that AI key. Check you copied all of it from Google AI Studio."
        return "We couldn't reach Google to check the AI key. Try again in a moment."
    except Exception:
        return "We couldn't check the AI key. Try again in a moment."


def check_tavily(key: str) -> str | None:
    try:
        TavilyClient(api_key=key.strip()).search("test", max_results=1)
        return None
    except InvalidAPIKeyError:
        return "Tavily did not accept that search key. Check you copied all of it from app.tavily.com."
    except UsageLimitExceededError:
        return "That Tavily key has no credits left. Add credits or use a different key."
    except Exception:
        return "We couldn't check the search key. Try again in a moment."
