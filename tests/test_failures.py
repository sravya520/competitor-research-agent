"""Tests for failure handling: secret bridging, retry budgets, user messages.

Run: python -m unittest discover -s tests -v

These exist because a transient Gemini 503 reached a user as "Something went
wrong talking to the research API", with the exception discarded, and took a
local reproduction to identify. Three things are protected here:

1. A 503 or 504 gets a wider retry budget than the rest, and 429 keeps the
   original one, since waiting longer inside one request cannot clear a daily
   quota.
2. Each failure class produces a message describing a different action, and
   the error code is always visible.
3. Every optional secret the deployed app understands is actually bridged.
   RETRIEVAL_PROVIDER and FIRECRAWL_API_KEY were silently dropped before,
   which left the provider switch dead on Streamlit Cloud.
"""

import os
import unittest

os.environ.setdefault("GEMINI_API_KEY", "test-gemini-key")
os.environ.setdefault("TAVILY_API_KEY", "test-tavily-key")

import failures  # noqa: E402
import config  # noqa: E402
from google.genai import errors  # noqa: E402


def api_error(code, status="ERROR"):
    """A google-genai APIError carrying a specific HTTP code."""
    return errors.APIError(code, {"error": {"code": code, "status": status,
                                            "message": f"synthetic {code}"}})


class FakeOutcome:
    def __init__(self, exception):
        self._exception = exception
        self.failed = exception is not None

    def exception(self):
        return self._exception


class FakeRetryState:
    """Minimal stand-in for tenacity's RetryCallState."""

    def __init__(self, attempt_number, exception):
        self.attempt_number = attempt_number
        self.outcome = FakeOutcome(exception)
        self.idle_for = 0.0


class RetryBudget(unittest.TestCase):
    def test_503_and_504_get_the_wider_budget(self):
        for code in (503, 504):
            with self.subTest(code=code):
                state = FakeRetryState(1, api_error(code))
                self.assertEqual(config.attempt_limit(state),
                                 config.RETRY_ATTEMPTS_WIDENED)

    def test_429_keeps_the_original_budget(self):
        state = FakeRetryState(1, api_error(429))
        self.assertEqual(config.attempt_limit(state),
                         config.RETRY_ATTEMPTS_DEFAULT)

    def test_500_and_502_keep_the_original_budget(self):
        # Retryable, but deliberately not widened: only 503/504 were.
        for code in (500, 502):
            with self.subTest(code=code):
                state = FakeRetryState(1, api_error(code))
                self.assertEqual(config.attempt_limit(state),
                                 config.RETRY_ATTEMPTS_DEFAULT)

    def test_stop_respects_the_wider_budget(self):
        busy = api_error(503)
        # A 503 must still be retried at the attempt where the old budget
        # would have given up.
        self.assertFalse(config.stop_by_cause(FakeRetryState(4, busy)))
        self.assertTrue(config.stop_by_cause(FakeRetryState(6, busy)))

    def test_stop_uses_the_default_budget_for_429(self):
        quota = api_error(429)
        self.assertTrue(config.stop_by_cause(FakeRetryState(4, quota)))

    def test_widened_wait_is_jittered(self):
        """Two 503 waits at the same attempt should differ, or a fleet of
        clients retries in lockstep."""
        busy = api_error(503)
        waits = {config.wait_by_cause(FakeRetryState(3, busy)) for _ in range(40)}
        self.assertGreater(len(waits), 1, "503 backoff is not jittered")

    def test_standard_wait_is_unchanged_for_429(self):
        quota = api_error(429)
        waits = {config.wait_by_cause(FakeRetryState(3, quota)) for _ in range(20)}
        self.assertEqual(len(waits), 1, "429 backoff should stay deterministic")

    def test_no_outcome_does_not_crash(self):
        class Bare:
            attempt_number = 1
            outcome = None
        self.assertEqual(config.attempt_limit(Bare()),
                         config.RETRY_ATTEMPTS_DEFAULT)

    def test_retryable_set_is_unchanged(self):
        for code in (429, 500, 502, 503, 504):
            self.assertTrue(config.is_retryable_error(api_error(code)), code)
        self.assertFalse(config.is_retryable_error(api_error(404)))
        self.assertFalse(config.is_retryable_error(ValueError("nope")))


class RetryWiring(unittest.TestCase):
    """The budget is only real if RETRY_SETTINGS actually uses it.

    Waits are neutralised here: the jittered curve would make a six-attempt
    run take minutes, and the timing is covered separately above.
    """

    def attempts_for(self, code):
        from tenacity import retry, wait_none
        calls = {"n": 0}

        @retry(**{**config.RETRY_SETTINGS, "wait": wait_none(),
                  "before_sleep": None})
        def always_fails():
            calls["n"] += 1
            raise api_error(code)

        with self.assertRaises(errors.APIError):
            always_fails()
        return calls["n"]

    def test_503_is_retried_six_times(self):
        self.assertEqual(self.attempts_for(503), 6)

    def test_504_is_retried_six_times(self):
        self.assertEqual(self.attempts_for(504), 6)

    def test_429_is_still_retried_four_times(self):
        self.assertEqual(self.attempts_for(429), 4)

    def test_500_and_502_are_still_retried_four_times(self):
        self.assertEqual(self.attempts_for(500), 4)
        self.assertEqual(self.attempts_for(502), 4)

    def test_non_retryable_is_attempted_once(self):
        self.assertEqual(self.attempts_for(404), 1)


class UserMessages(unittest.TestCase):
    def test_quota_message_for_429(self):
        message = failures.api_error_message(429)
        self.assertIn("daily usage limit", message)

    def test_upstream_message_names_the_code_and_blames_upstream(self):
        for code in failures.UPSTREAM_CODES:
            with self.subTest(code=code):
                message = failures.api_error_message(code)
                self.assertIn(str(code), message)
                self.assertIn("upstream", message)
                self.assertIn("not your query", message)

    def test_generic_message_still_shows_the_code(self):
        message = failures.api_error_message(400)
        self.assertIn("400", message)
        self.assertNotIn("upstream", message)

    def test_the_three_classes_differ(self):
        quota = failures.api_error_message(429)
        upstream = failures.api_error_message(503)
        generic = failures.api_error_message(400)
        self.assertEqual(len({quota, upstream, generic}), 3)

    def test_unknown_code_does_not_crash(self):
        self.assertIn("None", failures.api_error_message(None))


class LogLines(unittest.TestCase):
    def test_api_error_log_carries_code_and_status(self):
        line = failures.api_error_log_line(api_error(503, "UNAVAILABLE"))
        self.assertIn("code=503", line)
        self.assertIn("status=UNAVAILABLE", line)

    def test_unexpected_log_carries_type_and_text(self):
        line = failures.unexpected_error_log_line(ValueError("tavily exploded"))
        self.assertIn("ValueError", line)
        self.assertIn("tavily exploded", line)

    def test_unexpected_message_is_not_a_traceback(self):
        message = failures.unexpected_error_message()
        self.assertIn("logged", message)
        self.assertNotIn("Traceback", message)


class SecretBridge(unittest.TestCase):
    def test_bridges_the_two_required_keys(self):
        env = {}
        copied = failures.bridge_secrets(
            {"GEMINI_API_KEY": "g", "TAVILY_API_KEY": "t"}, env)
        self.assertEqual(env, {"GEMINI_API_KEY": "g", "TAVILY_API_KEY": "t"})
        self.assertCountEqual(copied, ["GEMINI_API_KEY", "TAVILY_API_KEY"])

    def test_bridges_the_optional_retrieval_keys(self):
        """The regression this module exists for: these were dropped, so the
        provider switch could not be set on Streamlit Cloud."""
        env = {}
        failures.bridge_secrets(
            {"RETRIEVAL_PROVIDER": "firecrawl", "FIRECRAWL_API_KEY": "f"}, env)
        self.assertEqual(env["RETRIEVAL_PROVIDER"], "firecrawl")
        self.assertEqual(env["FIRECRAWL_API_KEY"], "f")

    def test_existing_environment_wins(self):
        env = {"GEMINI_API_KEY": "from-env"}
        copied = failures.bridge_secrets({"GEMINI_API_KEY": "from-secrets"}, env)
        self.assertEqual(env["GEMINI_API_KEY"], "from-env")
        self.assertNotIn("GEMINI_API_KEY", copied)

    def test_unknown_secrets_are_ignored(self):
        env = {}
        failures.bridge_secrets({"SOMETHING_ELSE": "x"}, env)
        self.assertEqual(env, {})

    def test_missing_secrets_store_does_not_crash(self):
        """st.secrets raises when no secrets file exists at all."""
        class Exploding:
            def __contains__(self, key):
                raise RuntimeError("no secrets file")

        env = {}
        self.assertEqual(failures.bridge_secrets(Exploding(), env), [])
        self.assertEqual(env, {})

    def test_values_are_stringified(self):
        env = {}
        failures.bridge_secrets({"RETRIEVAL_PROVIDER": 42}, env)
        self.assertEqual(env["RETRIEVAL_PROVIDER"], "42")

    def test_every_provider_selector_key_is_bridged(self):
        """Any env var retrieval.py reads must be bridgeable, or it is dead on
        a deployed app."""
        for key in ("RETRIEVAL_PROVIDER", "FIRECRAWL_API_KEY"):
            self.assertIn(key, failures.BRIDGED_SECRET_KEYS)


if __name__ == "__main__":
    unittest.main(verbosity=2)
