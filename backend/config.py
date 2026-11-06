"""Backend settings, all from the environment (same pattern as the root config.py).

Nothing here is secret except DATABASE_URL (it may embed a password), so never log it.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).resolve().parent.parent


def _database_url() -> str:
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        # Local default. Free hosts wipe local disk on redeploy, so production sets DATABASE_URL.
        try:
            (ROOT / "data").mkdir(exist_ok=True)
            return f"sqlite:///{(ROOT / 'data' / 'cra.db').as_posix()}"
        except OSError:  # read-only filesystem (Vercel): /tmp is per-instance and ephemeral, so
            return "sqlite:////tmp/cra.db"  # real deployments MUST set DATABASE_URL
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
# Google-verified email. Override with UNLIMITED_EMAILS (comma separated); empty string = nobody.
UNLIMITED_EMAILS = frozenset(
    e.strip().lower()
    for e in os.environ.get("UNLIMITED_EMAILS", "smit.uxdesign@gmail.com,sravyadangeti520@gmail.com").split(",")
    if e.strip()
)

# Parked with backend/vault.py: own API keys are hidden for now, and nothing in the UI saves or reads them.
# It still protects any key saved by an earlier version. Rotating it makes those unreadable.
KEY_VAULT_SECRET = os.environ.get("KEY_VAULT_SECRET", "").strip()

# Bump when Terms or Privacy change in a way users must re-accept.
LEGAL_VERSION = "2026-11-06.2"

# Shown in the legal pages. Unset => the legal pages show a "fill these in" warning.
OPERATOR_NAME = os.environ.get("OPERATOR_NAME", "").strip()
CONTACT_EMAIL = os.environ.get("CONTACT_EMAIL", "").strip()
JURISDICTION = os.environ.get("JURISDICTION", "").strip()

# Local-only sign-in bypass so the app can be developed without Google credentials.
# Off unless explicitly set; NEVER set in production.
DEV_AUTH = os.environ.get("CRA_DEV_AUTH", "") == "1"
