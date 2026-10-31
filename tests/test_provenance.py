"""Tests for recording which model actually answered a run.

Run: python -m unittest discover -s tests -v

MODEL is an alias ending in "-latest", so it is a pointer, not an answer to
"which model produced this run". It resolved to gemini-3.5-flash-lite the
last time an error named it, and it will move again. Stage 3 compares a
competitor set against an earlier one, and without this a changed model
would read as a changed market.

pipeline.py collects the versions and exposes them through an accessor, the
same shape as the run ledger. Nothing here makes an API call: the
responses are stand-ins carrying only the field that matters.
"""

import os
import unittest
from types import SimpleNamespace

os.environ.setdefault("GEMINI_API_KEY", "test-gemini-key")
os.environ.setdefault("TAVILY_API_KEY", "test-tavily-key")

import memory  # noqa: E402
import pipeline  # noqa: E402
from runstate import RunState  # noqa: E402


def response(model_version):
    return SimpleNamespace(model_version=model_version, parsed=None)


class ModelVersions(unittest.TestCase):
    """One run's versions, recorded on that run.

    There is nothing to reset between tests: each builds its own RunState,
    which is the point of the change.
    """

    def setUp(self):
        self.run = RunState()

    def test_nothing_recorded_before_a_call(self):
        self.assertEqual(self.run.model_versions(), [])

    def test_a_response_records_its_version(self):
        pipeline._note_model_version(self.run, response("gemini-3.5-flash-lite"))
        self.assertEqual(self.run.model_versions(), ["gemini-3.5-flash-lite"])

    def test_the_response_is_passed_through_unchanged(self):
        """It wraps the API call, so it must not swallow the result."""
        original = response("gemini-3.5-flash-lite")
        self.assertIs(pipeline._note_model_version(self.run, original),
                      original)

    def test_several_versions_in_one_run_are_all_kept(self):
        """The identify, research and verify calls can land on different
        versions mid-rollout, and that is exactly worth knowing."""
        pipeline._note_model_version(self.run, response("gemini-3.5-flash-lite"))
        pipeline._note_model_version(self.run, response("gemini-3.6-flash-lite"))
        pipeline._note_model_version(self.run, response("gemini-3.5-flash-lite"))
        self.assertEqual(self.run.model_versions(),
                         ["gemini-3.5-flash-lite", "gemini-3.6-flash-lite"])

    def test_a_response_without_a_version_is_ignored(self):
        """Older SDKs and stubbed responses may not carry the field, and a
        missing version must not become an empty string in the ledger."""
        for stub in (response(None), response(""), SimpleNamespace(),
                     object()):
            with self.subTest(stub=type(stub).__name__):
                pipeline._note_model_version(self.run, stub)
        self.assertEqual(self.run.model_versions(), [])

    def test_a_second_run_starts_empty(self):
        """What reset_model_versions() used to be for. The Streamlit app
        researches several companies in one process, and now each gets its
        own run instead of sharing one cleared set."""
        pipeline._note_model_version(self.run, response("gemini-3.5-flash-lite"))
        self.assertEqual(RunState().model_versions(), [])


class RecordedProvenance(unittest.TestCase):
    def record(self, **kwargs):
        return memory.build_record(
            company_name="Notion",
            identity=SimpleNamespace(description="Workspace tool",
                                     location=None,
                                     website="https://notion.so"),
            **kwargs)

    def test_the_alias_and_the_resolved_versions_are_both_stored(self):
        record = self.record(model="gemini-flash-lite-latest",
                             model_resolved=["gemini-3.5-flash-lite"])
        self.assertEqual(record["model"], "gemini-flash-lite-latest")
        self.assertEqual(record["model_resolved"], ["gemini-3.5-flash-lite"])

    def test_a_run_with_no_resolved_version_stores_an_empty_list(self):
        """A reused identity makes no call, so a run can legitimately report
        fewer versions than it has steps."""
        self.assertEqual(self.record()["model_resolved"], [])

    def test_the_versions_are_copied_not_aliased(self):
        """self.run.model_versions() is rebuilt per call today, but the
        record must not share a list with its caller either way."""
        versions = ["gemini-3.5-flash-lite"]
        record = self.record(model_resolved=versions)
        versions.append("gemini-9")
        self.assertEqual(record["model_resolved"], ["gemini-3.5-flash-lite"])


if __name__ == "__main__":
    unittest.main()
