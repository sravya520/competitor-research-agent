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

from streamlit.testing.v1 import AppTest  # noqa: E402

APP = str(HERE.parent / "moat_app.py")
TIMEOUT = 60


def page_html(app) -> str:
    return " ".join(element.proto.body for element in app.get("html"))


class LandingPage(unittest.TestCase):
    def test_moat_app_imports_and_renders_the_landing_page(self):
        app = AppTest.from_file(APP, default_timeout=TIMEOUT).run()

        self.assertEqual(len(app.exception), 0, f"the landing page raised: {app.exception}")
        html = page_html(app)
        self.assertIn('class="lp-', html, "the landing markup should be on the page")
        self.assertIn("Try it free", html)


if __name__ == "__main__":
    unittest.main()
