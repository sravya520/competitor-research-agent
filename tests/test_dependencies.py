"""One Streamlit version for the whole repo.

The three dependency files once disagreed (==1.62.0, >=1.64, >=1.64), so the
demo, local development and production each ran a different Streamlit, and
installing the two requirements files in one command could not resolve at all.
Standard library only: this should run with nothing else installed.
"""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def streamlit_requirement(path: str) -> str:
    text = (ROOT / path).read_text(encoding="utf-8")
    found = re.findall(r"""^[\s"']*streamlit([^\s"',]*)""", text, flags=re.MULTILINE)
    if len(found) != 1:
        raise AssertionError(f"{path}: expected one streamlit line, found {found}")
    return found[0]


class StreamlitPin(unittest.TestCase):
    def test_all_three_files_pin_the_same_exact_version(self):
        pins = {path: streamlit_requirement(path)
                for path in ("requirements.txt", "requirements-web.txt", "pyproject.toml")}
        self.assertEqual(len(set(pins.values())), 1, pins)
        self.assertRegex(pins["requirements.txt"], r"^==\d+\.\d+\.\d+$")


if __name__ == "__main__":
    unittest.main()
