"""The real Moat app, driven through AppTest. No network.

Everything else about the web layer is tested below the page. This is the one place a page is
actually imported and drawn, so a bad import or a broken view fails here and not in production.
"""

import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE.parent), str(HERE)]

import web_setup  # noqa: E402  (sets the environment; must come before backend)

web_setup.require_web_packages()

from unittest.mock import patch  # noqa: E402

from streamlit.testing.v1 import AppTest, app_test  # noqa: E402

import runner  # noqa: E402
from backend import config, jobs, users  # noqa: E402
from views import auth, chrome  # noqa: E402

ROOT = HERE.parent
APP = str(ROOT / "moat_app.py")
TIMEOUT = 60


def page_html(app) -> str:
    return " ".join(element.proto.body for element in app.get("html"))


def open_page(url_path: str = "", job: str | None = None) -> AppTest:
    """AppTest.switch_page finds pages by file name, but st.navigation names them by url_path."""
    app = AppTest.from_file(APP, default_timeout=TIMEOUT)
    if url_path:
        app._page_hash = app_test.calc_hash(url_path)
    if job:
        app.query_params["job"] = job
    return app


class LandingPage(unittest.TestCase):
    def test_moat_app_imports_and_renders_the_landing_page(self):
        app = open_page().run()

        self.assertEqual(len(app.exception), 0, f"the landing page raised: {app.exception}")
        html = page_html(app)
        self.assertIn('class="lp-', html, "the landing markup should be on the page")
        self.assertIn("Try it free", html)


class SignedInCase(unittest.TestCase):
    """Stands in a real database user behind the sign-in gate, so these test the pages, not Google."""

    def signed_in_as(self, sub: str, **answers) -> users.UserInfo:
        user = users.upsert_login(sub, f"{sub}@example.com", "Test")
        users.accept_terms(user.id)
        if "use_case" in answers:
            users.save_use_case(user.id, answers["use_case"])
        if "team_size" in answers:
            users.save_team_size(user.id, answers["team_size"])
        if answers.get("onboarded"):
            users.finish_onboarding(user.id)
        patcher = patch.object(auth, "current_user", side_effect=lambda: users.get_info(user.id))
        patcher.start()
        self.addCleanup(patcher.stop)
        chrome.forget_recent()
        return users.get_info(user.id)


LOCAL = {"Host": "localhost:4000", "Origin": "http://localhost:4000"}


class SignInBypassDecision(unittest.TestCase):
    """The rule itself, on the headers a real connection would carry."""

    def setUp(self):
        patcher = patch.object(config, "DEV_AUTH", True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_a_truly_local_browser_is_allowed(self):
        for host, origin in (("localhost:4000", "http://localhost:4000"), ("127.0.0.1:4000", "http://127.0.0.1:4000"),
                             ("[::1]:4000", "http://[::1]:4000"), ("localhost", "https://localhost")):
            self.assertTrue(config.dev_auth_allowed({"Host": host, "Origin": origin}, None), host)
        self.assertTrue(config.dev_auth_allowed(LOCAL, "127.0.0.1"))

    def test_the_flag_being_off_refuses_even_a_local_connection(self):
        with patch.object(config, "DEV_AUTH", False):
            self.assertFalse(config.dev_auth_allowed(LOCAL, None))

    def test_a_public_or_lookalike_host_is_refused(self):
        for host in ("moatcra.vercel.app", "localhost.evil.example", "127.0.0.1.nip.io", "localhost@evil.example",
                     "0.0.0.0:4000", "192.168.1.5:4000", "", "[bad"):
            self.assertFalse(config.dev_auth_allowed({"Host": host, "Origin": "http://localhost:4000"}, None), host)

    def test_a_public_or_missing_origin_is_refused(self):
        for origin in ("https://moatcra.vercel.app", "http://localhost.evil.example", "null", "", "http://[bad"):
            self.assertFalse(config.dev_auth_allowed({"Host": "localhost:4000", "Origin": origin}, None), origin)
        self.assertFalse(config.dev_auth_allowed({"Host": "localhost:4000"}, None))

    def test_a_remote_client_is_refused_even_with_forged_local_headers(self):
        for ip in ("203.0.113.9", "192.168.1.5", "2001:db8::1", "not-an-ip"):
            self.assertFalse(config.dev_auth_allowed(LOCAL, ip), ip)

    def test_any_sign_of_a_proxy_is_refused(self):
        for header in ("X-Forwarded-For", "x-forwarded-host", "Forwarded", "X-Real-IP", "x-vercel-id"):
            self.assertFalse(config.dev_auth_allowed({**LOCAL, header: "203.0.113.9"}, None), header)

    def test_no_headers_at_all_is_refused(self):
        self.assertFalse(config.dev_auth_allowed({}, None))


class SignInBypassOnThePage(unittest.TestCase):
    """The pages obey the rule. The connection is what is faked here, not the rule."""

    def setUp(self):
        patcher = patch.object(config, "DEV_AUTH", True)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.dev_buttons = lambda app: [b for b in app.button if b.key == "dev_login"]

    def connect_as(self, headers, client_ip=None):
        patcher = patch.object(auth, "_dev_auth_on", lambda: config.dev_auth_allowed(headers, client_ip))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_from_a_public_address_the_button_is_not_offered(self):
        self.connect_as({"Host": "moatcra.vercel.app", "Origin": "https://moatcra.vercel.app"}, "203.0.113.9")
        app = open_page("app").run()

        self.assertEqual(self.dev_buttons(app), [])
        self.assertFalse(any("Local development mode" in w.value for w in app.warning))

    def test_from_a_public_address_a_session_already_marked_signed_in_gets_nothing(self):
        """Refusal has to hold on the sign-in check itself, not only by hiding the button."""
        self.connect_as({"Host": "moatcra.vercel.app", "Origin": "https://moatcra.vercel.app"}, "203.0.113.9")
        app = open_page("app")
        app.session_state["dev_signed_in"] = True
        app.run()

        self.assertNotIn("Who are we researching", page_html(app))
        self.assertIn("Find competitors", page_html(app))

    def test_a_real_session_with_no_connection_details_is_refused(self):
        """AppTest has no connection, so st.context is empty: the real check, failing closed."""
        app = open_page("app")
        app.session_state["dev_signed_in"] = True
        app.run()

        self.assertEqual(self.dev_buttons(app), [])
        self.assertIn("Find competitors", page_html(app))

    def test_from_this_machine_the_button_is_offered(self):
        self.connect_as(LOCAL)
        app = open_page("app").run()

        self.assertEqual(len(self.dev_buttons(app)), 1)


class TeammateEmailsAreGone(SignedInCase):
    def test_a_bigger_team_is_not_asked_for_anyones_email(self):
        self.signed_in_as("sub-team", use_case="x")
        app = open_page("app").run()
        app.radio[0].set_value("2 to 5").run()

        self.assertEqual([t.label for t in app.text_input], [])
        self.assertEqual([b.label for b in app.button], ["Continue"])

    def test_the_privacy_policy_no_longer_mentions_them(self):
        policy = (ROOT / "legal" / "privacy.md").read_text(encoding="utf-8").lower()
        self.assertNotIn("teammate", policy)


class OwnKeysAreHidden(SignedInCase):
    """Saving keys used to make every research fail, while the page said they were being used."""

    def test_onboarding_finishes_after_two_questions_with_no_key_step(self):
        user = self.signed_in_as("sub-ob")
        app = open_page("app").run()
        self.assertIn("Step 1 of 2", page_html(app))
        app.radio[0].set_value(app.radio[0].options[0]).run()
        app.button(key="ob_next1").click().run()
        self.assertIn("Step 2 of 2", page_html(app))
        app.radio[0].set_value("Just me").run()
        app.button(key="ob_next2").click().run()

        self.assertEqual(len(app.exception), 0, app.exception)
        self.assertTrue(users.get_info(user.id).onboarded)
        self.assertIn("Who are we researching", page_html(app))

    def test_someone_who_stopped_at_the_old_key_step_is_let_through(self):
        user = self.signed_in_as("sub-old", use_case="x", team_size="Just me")
        app = open_page("app").run()

        self.assertEqual(len(app.exception), 0, app.exception)
        self.assertTrue(users.get_info(user.id).onboarded)
        self.assertIn("Who are we researching", page_html(app))

    def test_the_account_page_has_no_key_controls(self):
        self.signed_in_as("sub-acct", use_case="x", team_size="Just me", onboarded=True)
        app = open_page("account").run()

        self.assertEqual(len(app.exception), 0, app.exception)
        self.assertEqual([t.label for t in app.text_input], [])
        self.assertFalse(any("key" in b.label.lower() for b in app.button))
        self.assertFalse(any("Your API keys" in s.value for s in app.subheader))

    def start_research(self, app: AppTest) -> AppTest:
        app.button(key="pick_general").click().run()
        app.text_input(key="cmp_name").set_value("Acme")
        app.text_input(key="cmp_url").set_value("https://acme.example")
        app.run()  # the button stays disabled until both boxes have been sent to the script
        app.button(key="run").click().run()
        return app

    def test_a_user_who_saved_keys_runs_on_the_free_run_and_is_not_refused(self):
        user = self.signed_in_as("sub-keys", use_case="x", team_size="Just me", onboarded=True)
        users.save_keys(user.id, "g-key", "t-key")
        with patch.object(runner, "start") as start:
            app = self.start_research(open_page("app").run())

        self.assertEqual(len(app.exception), 0, app.exception)
        start.assert_called_once()
        self.assertEqual(jobs.latest_for(user.id).key_mode, "house")
        self.assertEqual(users.get_info(user.id).free_runs_left, 0)

    def test_running_out_of_runs_says_so_and_mentions_no_keys(self):
        user = self.signed_in_as("sub-out", use_case="x", team_size="Just me", onboarded=True)
        users.consume_free_run(user.id)
        with patch.object(runner, "start") as start:
            app = self.start_research(open_page("app").run())

        start.assert_not_called()
        said = " ".join(w.value for w in app.warning)
        self.assertIn("used your free run", said)
        self.assertNotIn("key", said.lower())

    def test_no_page_or_job_reaches_the_parked_key_code(self):
        reached = ("vault", "keycheck", "save_keys", "load_keys", "key_hints", "clear_keys", "has_own_keys")
        files = [ROOT / "moat_app.py", ROOT / "runner.py", ROOT / "index.py", *sorted((ROOT / "views").glob("*.py"))]
        for path in files:
            text = path.read_text(encoding="utf-8")
            for name in reached:
                self.assertNotIn(name, text, f"{path.name} reaches {name}")

    def test_nothing_the_user_reads_says_their_own_keys_are_used(self):
        files = [ROOT / "legal" / "privacy.md", ROOT / "legal" / "terms.md", ROOT / "ui" / "landing.html",
                 *sorted((ROOT / "views").glob("*.py"))]
        for path in files:
            text = path.read_text(encoding="utf-8").lower()
            for phrase in ("your own api key", "your own key", "your keys", "add your api"):
                self.assertNotIn(phrase, text, path.name)


if __name__ == "__main__":
    unittest.main()
