"""Shared setup for the tests of the web layer. Import this BEFORE anything from backend/.

backend.config reads its settings once, when first imported, and every test module runs in
one process, so whichever module imports it first decides for all of them. Keeping the settings
here means that is always this module: a throwaway database (never data/cra.db), small known
limits, and the sign-in bypass off, whatever the developer's own .env says (load_dotenv never
overrides a variable that is already set).
"""

import importlib.util
import os
import tempfile
import unittest
from pathlib import Path

INSTALL = "pip install -r requirements.txt -r requirements-web.txt"
WEB_PACKAGES = ("sqlalchemy", "authlib", "cryptography")

TMP = tempfile.mkdtemp()
DATABASE_URL = f"sqlite:///{Path(TMP, 'test.db').as_posix()}"

os.environ["DATABASE_URL"] = DATABASE_URL
os.environ["DAILY_RUNS_PER_USER"] = "3"
os.environ["DAILY_RUNS_GLOBAL"] = "5"
os.environ["FREE_RUNS"] = "1"
os.environ["KEY_VAULT_SECRET"] = "test-secret-not-for-production"
os.environ["CRA_DEV_AUTH"] = "0"
os.environ["UNLIMITED_EMAILS"] = "owner@example.com, Friend@Example.com"
os.environ.setdefault("GEMINI_API_KEY", "test-gemini-key")
os.environ.setdefault("TAVILY_API_KEY", "test-tavily-key")


def require_web_packages() -> None:
    """Skip the calling test module, with the fix, when the web packages aren't installed.

    The demo (app.py) needs only requirements.txt, so a checkout with just that installed is
    legitimate. unittest's loader turns a SkipTest raised during import into a visible skip.
    """
    missing = [name for name in WEB_PACKAGES if importlib.util.find_spec(name) is None]
    if missing:
        raise unittest.SkipTest(f"web packages missing ({', '.join(missing)}). Install them with: {INSTALL}")
