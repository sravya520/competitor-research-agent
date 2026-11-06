"""The Vercel entry point (index.py), in separate processes, because that is what instances are.

No network: Google's two endpoints are replaced. Each subprocess stands in for one server instance,
which shares nothing with another except what the environment gives them both.
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE.parent), str(HERE)]

import web_setup  # noqa: E402  (sets the environment; must come before backend)

web_setup.require_web_packages()

ROOT = HERE.parent
SECRET = "the-shared-cookie-secret-for-these-tests-000"

INSTANCE = r"""
import json, os, sys
from urllib.parse import parse_qs, urlparse

from authlib.integrations.starlette_client import StarletteOAuth2App

async def metadata(self):
    return {"issuer": "https://accounts.google.com", "jwks_uri": "https://x/jwks",
            "authorization_endpoint": "https://accounts.google.com/o/oauth2/v2/auth",
            "token_endpoint": "https://oauth2.googleapis.com/token"}

async def token(self, request, **kwargs):
    return {"userinfo": {"sub": "1", "email": "a@example.com", "email_verified": True},
            "id_token": "x", "access_token": "y"}

StarletteOAuth2App.load_server_metadata = metadata
StarletteOAuth2App.authorize_access_token = token

from starlette.testclient import TestClient

import index

site = os.environ["SITE_URL"]
client = TestClient(index.app, base_url=site, follow_redirects=False)
client.get("/_stcore/health")  # the first request starts the app and applies the secrets

if sys.argv[1] == "login":
    from streamlit.user_info import generate_login_redirect_url
    response = client.get(generate_login_redirect_url("default"))
    query = parse_qs(urlparse(response.headers["location"]).query)
    print(json.dumps({"state": query["state"][0], "redirect_uri": query["redirect_uri"][0],
                      "cookies": dict(response.cookies.items())}))
else:
    started = json.loads(sys.argv[2])
    client.cookies.update(started["cookies"])
    response = client.get(f"/oauth2callback?state={started['state']}&code=abc")
    print(json.dumps({"signed_in": "_streamlit_user" in response.cookies,
                      "location": response.headers.get("location")}))
"""


def instance_env(**overrides) -> dict:
    env = dict(os.environ, GOOGLE_CLIENT_ID="id.apps.googleusercontent.com", GOOGLE_CLIENT_SECRET="secret",
               SITE_URL="https://moatcra.vercel.app", DATABASE_URL=web_setup.DATABASE_URL, PYTHONIOENCODING="utf-8")
    for name in ("AUTH_COOKIE_SECRET", "STREAMLIT_SERVER_COOKIE_SECRET", "VERCEL"):
        env.pop(name, None)
    env.update(overrides)
    return env


def run_instance(env: dict, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-c", INSTANCE, *args], cwd=ROOT, env=env, capture_output=True,
                          text=True, encoding="utf-8", timeout=120)


def last_json(done: subprocess.CompletedProcess) -> dict:
    if done.returncode != 0:
        raise AssertionError(done.stderr[-1500:])
    return json.loads(done.stdout.strip().splitlines()[-1])


class BootWithoutADatabase(unittest.TestCase):
    def boot(self, **overrides) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, "-c", "import index"], cwd=ROOT, capture_output=True, text=True,
                              encoding="utf-8", timeout=120, env=instance_env(**overrides))

    def test_on_vercel_it_stops_and_names_the_missing_variable(self):
        done = self.boot(VERCEL="1", DATABASE_URL="")

        self.assertNotEqual(done.returncode, 0, "it must not start on a throwaway database")
        self.assertIn("DATABASE_URL is not set", done.stderr)

    def test_with_a_database_it_starts(self):
        self.assertEqual(self.boot(VERCEL="1").returncode, 0)


class SignInAcrossInstances(unittest.TestCase):
    """The login-state cookie used to be signed with a key random to each process, so a callback that
    reached a different instance than the login lost its state and the user landed back on sign-in,
    with no error anywhere they could see."""

    def assert_login_survives_a_change_of_instance(self, env):
        started = last_json(run_instance(env, "login"))
        self.assertEqual(started["redirect_uri"], "https://moatcra.vercel.app/oauth2callback")

        finished = last_json(run_instance(env, "callback", json.dumps(started)))
        self.assertTrue(finished["signed_in"], finished)
        self.assertEqual(finished["location"], "/app")

    def test_with_both_secrets_set_as_documented(self):
        self.assert_login_survives_a_change_of_instance(
            instance_env(AUTH_COOKIE_SECRET=SECRET, STREAMLIT_SERVER_COOKIE_SECRET=SECRET))

    def test_with_only_auth_cookie_secret_set(self):
        self.assert_login_survives_a_change_of_instance(instance_env(AUTH_COOKIE_SECRET=SECRET))

    def test_with_only_the_streamlit_variable_set(self):
        self.assert_login_survives_a_change_of_instance(instance_env(STREAMLIT_SERVER_COOKIE_SECRET=SECRET))


class OneDatabaseStaysThrowaway(unittest.TestCase):
    def test_these_tests_never_use_the_real_database(self):
        self.assertTrue(web_setup.DATABASE_URL.startswith("sqlite:///"))
        self.assertIn(Path(tempfile.gettempdir()).as_posix().lower(), web_setup.DATABASE_URL.lower())


if __name__ == "__main__":
    unittest.main()
