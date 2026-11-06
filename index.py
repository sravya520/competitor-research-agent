"""Vercel entrypoint: runs the Streamlit app as a standard ASGI web app.

Vercel has no long-running server, but its Python runtime serves any ASGI app and supports
WebSockets, which is all Streamlit needs. Local development is unchanged: `streamlit run moat_app.py`.

Limits to know (DECISIONS D30, D34): a WebSocket closes after under a minute here and Streamlit reconnects with a
NEW session, so session state is not reliable. Accounts and research jobs live in the database, and research runs in a
background thread (runner.py), never inside a page.

There is no secrets.toml on Vercel, so everything comes from environment variables: KEY_VAULT_SECRET, DATABASE_URL,
GEMINI_API_KEY, TAVILY_API_KEY, GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, AUTH_COOKIE_SECRET and SITE_URL
(e.g. https://moatcra.vercel.app).
"""

import os

from backend import config  # noqa: F401  (stops the boot here, with a clear error, if the database isn't set)

from streamlit.starlette import App  # noqa: E402


def _auth_secrets() -> dict | None:
    cid, csec, cookie, site = (
        os.environ.get(k) for k in ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "AUTH_COOKIE_SECRET", "SITE_URL")
    )
    if not all((cid, csec, cookie, site)):
        return None  # sign-in stays "not set up" until all four are provided
    return {
        "auth": {
            "redirect_uri": site.rstrip("/") + "/oauth2callback",
            "cookie_secret": cookie,
            "client_id": cid,
            "client_secret": csec,
            "server_metadata_url": "https://accounts.google.com/.well-known/openid-configuration",
        }
    }


class _AuthToApp:
    """Streamlit's auth routes always redirect to "/" (the landing page). After sign-in the user should land
    in the product (the gate there sends new users on to consent and onboarding) and after sign-out on the
    login screen, so rewrite that one redirect to /app on those two routes. Everything else passes through."""

    def __init__(self, inner):
        self._inner = inner

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not scope["path"].endswith(("/auth/logout", "/oauth2callback")):
            return await self._inner(scope, receive, send)

        async def send_rewritten(message):
            if message["type"] == "http.response.start":
                headers = [
                    (k, b"/app" if k.lower() == b"location" and v in (b"/", b"") else v)
                    for k, v in message.get("headers", [])
                ]
                message = {**message, "headers": headers}
            await send(message)

        return await self._inner(scope, receive, send_rewritten)

    def __getattr__(self, name):  # anything else (lifespan hooks, routes) comes from the real app
        return getattr(self._inner, name)


app = _AuthToApp(App("moat_app.py", secrets=_auth_secrets()))
