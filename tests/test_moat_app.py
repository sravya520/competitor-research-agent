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
from backend import jobs, users  # noqa: E402
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
