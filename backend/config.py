"""Backend settings, all from the environment (same pattern as the root config.py).

Nothing here is secret except DATABASE_URL (it may embed a password), so never log it.
"""

import ipaddress
import os
from collections.abc import Mapping
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).resolve().parent.parent


def _database_url() -> str:
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        # A throwaway database in production looks like it works: each instance gets its own copy, so
        # accounts, consent and free runs reset without a word. Stopping is the only honest answer.
        if os.environ.get("VERCEL"):
            raise RuntimeError("DATABASE_URL is not set. Moat will not start on Vercel without a database (see README).")
        try:
            (ROOT / "data").mkdir(exist_ok=True)  # local development only
        except OSError as exc:
            raise RuntimeError("DATABASE_URL is not set and data/ can't be created here. Set DATABASE_URL.") from exc
        return f"sqlite:///{(ROOT / 'data' / 'cra.db').as_posix()}"
    # Neon/Supabase/Heroku hand out postgres:// or postgresql://; SQLAlchemy needs the driver named.
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix):]
    return url


DATABASE_URL = _database_url()

# Usage limits protect the one shared Gemini/Tavily key (DECISIONS D11).
DAILY_RUNS_PER_USER = int(os.environ.get("DAILY_RUNS_PER_USER", "3"))
DAILY_RUNS_GLOBAL = int(os.environ.get("DAILY_RUNS_GLOBAL", "150"))

# Research runs on OUR keys that a user gets for free, once in their lifetime.
FREE_RUNS = int(os.environ.get("FREE_RUNS", "1"))

# Accounts that run on OUR keys without limit (no free-run cap, no daily cap). Matched on the
# Google-verified email. Set with UNLIMITED_EMAILS (comma separated); unset = nobody. No address belongs
# in this file: it would be published with the code and would hand out unlimited use of our keys.
UNLIMITED_EMAILS = frozenset(
    e.strip().lower()
    for e in os.environ.get("UNLIMITED_EMAILS", "").split(",")
    if e.strip()
)

# Parked with backend/vault.py: own API keys are hidden for now, and nothing in the UI saves or reads them.
# It still protects any key saved by an earlier version. Rotating it makes those unreadable.
KEY_VAULT_SECRET = os.environ.get("KEY_VAULT_SECRET", "").strip()

# Bump when Terms or Privacy change in a way users must re-accept.
LEGAL_VERSION = "2026-11-06.3"

# Shown in the legal pages. Unset => the legal pages show a "fill these in" warning.
OPERATOR_NAME = os.environ.get("OPERATOR_NAME", "").strip()
CONTACT_EMAIL = os.environ.get("CONTACT_EMAIL", "").strip()
JURISDICTION = os.environ.get("JURISDICTION", "").strip()

# Local-only sign-in bypass so the app can be developed without Google credentials.
# Off unless explicitly set; NEVER set in production. Setting it is not enough: see dev_auth_allowed.
DEV_AUTH = os.environ.get("CRA_DEV_AUTH", "") == "1"

_LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
# Any of these means a proxy is in front of us, so the connection only looks local to this process.
_PROXY_HEADERS = ("forwarded", "x-forwarded-for", "x-forwarded-host", "x-forwarded-proto", "x-real-ip", "x-vercel-id")


def _is_local_name(authority: str | None) -> bool:
    """True only for a bare loopback name. localhost.evil.com, localhost@evil.com and 0.0.0.0 are not."""
    if not authority:
        return False
    try:
        return urlsplit(f"//{authority.strip()}").hostname in _LOCAL_HOSTS
    except ValueError:
        return False


def dev_auth_allowed(headers: Mapping[str, str], client_ip: str | None) -> bool:
    """Whether this connection may use the sign-in bypass: only if the flag is on AND it is truly local.

    All three must be local. Host and Origin come from the client, so either alone could be forged, but a
    remote attacker cannot also forge the socket's address; a browser cannot forge Origin; and a reverse proxy
    on the same machine connects from loopback, which is why its forwarding headers count against it too.
    Anything missing counts as not local. client_ip is None for a loopback socket (st.context.ip_address).
    """
    if not DEV_AUTH:
        return False
    seen = {key.lower(): value for key, value in headers.items()}
    if any(name in seen for name in _PROXY_HEADERS):
        return False
    if not _is_local_name(seen.get("host")):
        return False
    origin = seen.get("origin", "")
    try:
        parts = urlsplit(origin)
    except ValueError:
        return False
    if parts.scheme not in ("http", "https") or not _is_local_name(parts.netloc):
        return False
    if client_ip is None:
        return True
    try:
        return ipaddress.ip_address(client_ip).is_loopback
    except ValueError:
        return False
