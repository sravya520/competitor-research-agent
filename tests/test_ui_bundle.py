"""The generated stylesheet and Streamlit config are what production actually serves.

Standard library only. A build on a Windows checkout once wrote an app.css with none of its design
tokens defined, and every other test still passed, because nothing else reads the CSS.
"""

import re
import tomllib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class GeneratedBundle(unittest.TestCase):
    def test_every_design_token_app_css_uses_is_defined(self):
        css = (ROOT / "ui" / "app.css").read_text(encoding="utf-8")
        used = set(re.findall(r"var\((--ant-[a-z0-9-]+)", css))
        defined = set(re.findall(r"^\s*(--ant-[a-z0-9-]+):", css, flags=re.MULTILINE))

        self.assertTrue(used, "app.css should use the design tokens")
        self.assertEqual(used - defined, set())

    def test_the_bundle_is_in_step_with_the_css_it_is_built_from(self):
        bundle = (ROOT / "ui" / "app.css").read_text(encoding="utf-8")
        for source in ("components.css", "icons.css", "landing.css", "signin.css", "workspace.css", "neon.css", "motion.css"):
            text = (ROOT / "ui" / source).read_text(encoding="utf-8").replace("\r\n", "\n")
            self.assertIn(text, bundle.replace("\r\n", "\n"), f"app.css is stale: run node design-system/build-ui.js ({source})")


class GeneratedConfig(unittest.TestCase):
    def test_visitors_are_never_shown_a_traceback(self):
        with open(ROOT / ".streamlit" / "config.toml", "rb") as handle:
            settings = tomllib.load(handle)

        self.assertEqual(settings["client"]["showErrorDetails"], "none")
        self.assertIn('showErrorDetails = "none"', (ROOT / "design-system" / "build-ui.js").read_text(encoding="utf-8"),
                      "set it in the generator, or the next build removes it")


class LandingPageNames(unittest.TestCase):
    def test_competitors_are_plain_text_and_no_logo_files_ship(self):
        html = (ROOT / "ui" / "landing.html").read_text(encoding="utf-8")

        self.assertNotIn("lp-logo", html)
        self.assertNotIn("/logos/", html)
        self.assertFalse((ROOT / "static" / "logos").exists())
        for name in ("Coda", "ClickUp", "Confluence", "Obsidian", "Airtable"):
            self.assertIn(f'<span class="lp-co">{name}</span>', html)


if __name__ == "__main__":
    unittest.main()
