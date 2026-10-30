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

import contextlib
import io
import os
import unittest
from unittest.mock import patch

os.environ.setdefault("GEMINI_API_KEY", "test-gemini-key")
os.environ.setdefault("TAVILY_API_KEY", "test-tavily-key")

import httpx  # noqa: E402

import failures  # noqa: E402
import config  # noqa: E402
from google.genai import errors  # noqa: E402


def api_error(code, status="ERROR"):
    """A google-genai APIError carrying a specific HTTP code."""
    return errors.APIError(code, {"error": {"code": code, "status": status,
                                            "message": f"synthetic {code}"}})


def api_error_after(code, delay, status="RESOURCE_EXHAUSTED"):
    """An APIError carrying RetryInfo, the way a real quota error does.

    `delay` is the duration string the provider sends, such as "54616s".
    """
    return errors.APIError(code, {"error": {
        "code": code, "status": status,
        "message": f"synthetic {code}; quotaMetric generate_content_requests",
        "details": [
            {"@type": "type.googleapis.com/google.rpc.QuotaFailure",
             "violations": [{"quotaId": "PerDayPerProject"}]},
            {"@type": "type.googleapis.com/google.rpc.RetryInfo",
             "retryDelay": delay},
        ],
    }})


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


class SuggestedDelay(unittest.TestCase):
    """Retry only when waiting can help.

    Found live: an exhausted daily quota answered "Please retry in 15h10m"
    and was retried four times anyway. The provider had already said the
    request could not succeed; four more rejections and fourteen seconds of
    backoff were the only result.
    """

    def test_the_suggested_delay_is_read(self):
        self.assertEqual(config.retry_after_seconds(
            api_error_after(429, "54616s")), 54616.0)
        self.assertEqual(config.retry_after_seconds(
            api_error_after(429, "7s")), 7.0)
        self.assertEqual(config.retry_after_seconds(
            api_error_after(429, "1.5s")), 1.5)

    def test_no_retry_info_means_no_suggestion(self):
        self.assertIsNone(config.retry_after_seconds(api_error(429)))
        self.assertIsNone(config.retry_after_seconds(ValueError("nope")))
        self.assertIsNone(config.retry_after_seconds(None))

    def test_an_unparseable_delay_is_ignored(self):
        """Falls back to the existing budget rather than crashing or
        refusing to retry on a format change."""
        self.assertIsNone(config.retry_after_seconds(
            api_error_after(429, "soon")))
        self.assertTrue(config.is_retryable_error(api_error_after(429, "soon")))

    def test_a_long_wait_is_not_retried(self):
        for delay in ("61s", "300s", "54616s"):
            with self.subTest(delay=delay):
                self.assertFalse(
                    config.is_retryable_error(api_error_after(429, delay)))

    def test_a_short_wait_is_retried(self):
        for delay in ("1s", "12s", "60s"):
            with self.subTest(delay=delay):
                self.assertTrue(
                    config.is_retryable_error(api_error_after(429, delay)))

    def test_the_boundary_is_inclusive(self):
        limit = config.MAX_SUGGESTED_WAIT_SECONDS
        self.assertTrue(config.is_retryable_error(
            api_error_after(429, f"{limit}s")))
        self.assertFalse(config.is_retryable_error(
            api_error_after(429, f"{limit + 1}s")))

    def test_the_rule_applies_to_any_code_that_carries_it(self):
        """A 503 saying "retry in two hours" is no more retryable than a
        429 saying it."""
        self.assertFalse(config.is_retryable_error(
            api_error_after(503, "7200s", status="UNAVAILABLE")))
        self.assertTrue(config.is_retryable_error(
            api_error_after(503, "4s", status="UNAVAILABLE")))

    def test_a_short_suggestion_sets_the_wait(self):
        """The provider knows when its own window opens, so its number beats
        the backoff curve."""
        wait = config.wait_by_cause(FakeRetryState(1, api_error_after(429, "9s")))
        self.assertGreaterEqual(wait, 9.0)
        self.assertLess(wait, 11.0)

    def test_a_429_without_retry_info_keeps_the_old_curve(self):
        waits = {config.wait_by_cause(FakeRetryState(3, api_error(429)))
                 for _ in range(20)}
        self.assertEqual(len(waits), 1, "429 backoff should stay deterministic")

    def test_a_hopeless_quota_error_is_attempted_once(self):
        from tenacity import retry, wait_none

        calls = {"n": 0}

        @retry(**{**config.RETRY_SETTINGS, "wait": wait_none(),
                  "before_sleep": None})
        def always_fails():
            calls["n"] += 1
            raise api_error_after(429, "54616s")

        with self.assertRaises(errors.APIError):
            always_fails()
        self.assertEqual(calls["n"], 1, "no point retrying a 15-hour wait")


class RetryLogging(unittest.TestCase):
    def line_for(self, exception):
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            config.log_retry(FakeRetryState(2, exception))
        return buffer.getvalue()

    def test_the_retry_log_is_one_line(self):
        line = self.line_for(api_error_after(429, "54616s"))
        self.assertEqual(len(line.strip().splitlines()), 1)

    def test_it_names_the_code_and_status(self):
        line = self.line_for(api_error_after(429, "54616s"))
        self.assertIn("attempt 2", line)
        self.assertIn("429", line)
        self.assertIn("RESOURCE_EXHAUSTED", line)

    def test_it_does_not_dump_the_payload(self):
        """A quota error embeds its whole JSON body in its message. Four
        retries of that filled the terminal and buried the outcome."""
        line = self.line_for(api_error_after(429, "54616s"))
        self.assertNotIn("quotaMetric", line)
        self.assertNotIn("retryDelay", line)
        self.assertLess(len(line), 120)

    def test_a_non_api_failure_is_named_by_type(self):
        self.assertIn("TransportError",
                      self.line_for(httpx.TransportError("dropped")))


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


class CliFailures(unittest.TestCase):
    """The CLI must report a provider failure as a sentence too.

    Found by running main.py for real against an exhausted daily quota: it
    printed the retry detail four times and then a traceback, while app.py
    had answered the same error with one plain sentence ever since the 503
    work. The messages are shared rather than reworded, so the two surfaces
    cannot drift apart again.
    """

    def exit_message(self, exception):
        import main

        with patch.object(main, "main", side_effect=exception):
            with self.assertRaises(SystemExit) as caught:
                main.run()
        return str(caught.exception)

    def test_an_exhausted_quota_is_a_sentence(self):
        message = self.exit_message(api_error(429))
        self.assertIn("daily free limit", message)
        self.assertNotIn("Traceback", message)
        self.assertNotIn("RESOURCE_EXHAUSTED", message)

    def test_an_upstream_failure_still_names_the_code(self):
        self.assertIn("503", self.exit_message(api_error(503)))

    def test_the_quota_message_is_written_for_a_key_owner(self):
        """The web wording addresses a visitor to someone else's demo, who
        can only come back later. A CLI user owns the key, so the useful
        facts are whose limit it is and when it resets."""
        message = self.exit_message(api_error(429))
        self.assertIn("Your Gemini key", message)
        self.assertIn("midnight Pacific", message)
        self.assertNotIn("demo", message)
        self.assertNotEqual(message, failures.api_error_message(429))

    def test_only_the_quota_wording_differs_by_surface(self):
        """Everything else stays shared, so the two surfaces cannot drift
        apart on anything but the one message that needed to."""
        for code in (500, 502, 503, 504, 400, 404):
            with self.subTest(code=code):
                self.assertEqual(failures.api_error_message(code, "cli"),
                                 failures.api_error_message(code))

    def test_ctrl_c_is_not_a_crash(self):
        self.assertIn("Stopped", self.exit_message(KeyboardInterrupt()))


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
