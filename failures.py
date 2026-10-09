"""Secret bridging and failure messages, with no heavy imports.

`app.py` has to bridge Streamlit's secrets into `os.environ` *before* it
imports the pipeline, because `config.py` reads the keys the moment it is
imported. That ordering is why the key list used to be hardcoded inline and so
could not be tested. This module imports nothing but the standard library, so
`app.py` can import it first and the tests can import it without pulling in
Streamlit or needing any API key present.

The message helpers live here for the same reason: they are pure functions of
an error code, so they can be tested without a running Streamlit session.
"""

from __future__ import annotations

# Secrets worth bridging from st.secrets into os.environ.
#
# The first two are required: config.py raises KeyError at import without them.
# The second two are optional and were missing until a retrieval backend was
# added, which meant RETRIEVAL_PROVIDER and FIRECRAWL_API_KEY set as Streamlit
# secrets never reached os.environ and the provider switch silently stayed on
# its default when deployed.
BRIDGED_SECRET_KEYS = (
    "GEMINI_API_KEY",
    "TAVILY_API_KEY",
    "RETRIEVAL_PROVIDER",
    "FIRECRAWL_API_KEY",
)

# Codes where the provider is briefly unwell rather than the request being
# wrong. Retrying genuinely helps, so the user is told to retry.
UPSTREAM_CODES = (500, 502, 503, 504)


def bridge_secrets(secrets, environ, keys=BRIDGED_SECRET_KEYS) -> list[str]:
    """Copy known keys from a secrets mapping into an environment mapping.

    An existing environment value always wins, so a real environment variable
    or a local .env is never overwritten by a deployed secret. Returns the
    names actually copied, which is what makes this observable in a test.

    Reading st.secrets raises when no secrets file exists at all, so each
    lookup is guarded: a missing secrets store means nothing to bridge, not a
    crash on startup.
    """
    copied = []
    for key in keys:
        if key in environ:
            continue
        try:
            if key in secrets:
                environ[key] = str(secrets[key])
                copied.append(key)
        except Exception:
            # No secrets store, or it cannot be read. Nothing to bridge.
            continue
    return copied


def api_error_log_line(exc) -> str:
    """A one-line stdout record of a provider error.

    Streamlit Cloud's "Manage app" panel captures stdout, so this is the only
    trace that survives a failure in a deployed run. The previous handler
    discarded the exception entirely, which is why diagnosing a 503 needed a
    local reproduction.
    """
    code = getattr(exc, "code", None)
    status = getattr(exc, "status", None)
    return f"[api-error] code={code} status={status} {type(exc).__name__}: {exc}"


def api_error_message(code) -> str:
    """What to show the user for a provider error code.

    The three cases are genuinely different actions: wait for tomorrow, retry
    in a minute, or report a bug. Collapsing them into one message is what
    made a transient upstream outage look like a defect in the report.
    """
    if code == 429:
        return (
            "This demo has hit its free daily usage limit. Please try again "
            "later, or take a look at the source code on GitHub in the "
            "meantime."
        )
    if code in UPSTREAM_CODES:
        return (
            f"The model provider is briefly unavailable (error {code}). This "
            "is upstream, not your query. Please try again in a minute."
        )
    return (
        f"Something went wrong talking to the research API (error {code}). "
        "Please try again in a moment."
    )


def unexpected_error_log_line(exc) -> str:
    """Stdout record for anything that is not a provider API error."""
    return f"[unexpected] {type(exc).__name__}: {exc}"


def unexpected_error_message() -> str:
    """Shown for non-API failures, which previously reached users as a raw
    traceback: a Tavily error, a dropped connection, or a code defect."""
    return (
        "Something went wrong while building the report. The details have "
        "been logged. Please try again, and if it keeps happening the logs "
        "will show the cause."
    )
