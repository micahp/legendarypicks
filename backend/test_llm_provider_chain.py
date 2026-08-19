#!/usr/bin/env python3
"""The LLM provider chain, and the permanent-refusal rule.

Written 2026-08-19, when `api.deepseek.com` ran out of credit and returned
2,334 HTTP 402s in seven days at roughly two a minute. The old code returned
None on failure and every caller read that as "no answer", so a dead account
was retried for 17 hours while previews, recaps and narratives sat dark.

A 401/402/403 is a PERMANENT refusal: it will not change until a person acts.
These tests pin that it is recorded once and then skipped, not retried, which
is the rule already written for ESPN's 403 and never applied to this path.
"""
import json
import unittest
import urllib.error
from unittest import mock

import _core


def _http_error(code):
    return urllib.error.HTTPError("http://x", code, "refused", None, None)


def _ok(text="a story"):
    class R:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self):
            return json.dumps({"choices": [{"message": {"content": text},
                                            "finish_reason": "stop"}],
                               "usage": {"completion_tokens": 10}}).encode()
    return R()


class ProviderChainTests(unittest.TestCase):
    def setUp(self):
        _core._LLM_REFUSED_UNTIL.clear()
        self.addCleanup(_core._LLM_REFUSED_UNTIL.clear)
        self._p = _core._LLM_PROVIDERS
        _core._LLM_PROVIDERS = ["nous", "openrouter"]
        self.addCleanup(setattr, _core, "_LLM_PROVIDERS", self._p)
        # Both providers have a credential unless a test says otherwise.
        self.ep = mock.patch.object(
            _core, "_llm_endpoint",
            side_effect=lambda p: (f"https://{p}.test/chat", {"Authorization": "Bearer x"}))
        self.ep.start()
        self.addCleanup(self.ep.stop)

    def test_the_first_provider_that_answers_wins(self):
        with mock.patch("urllib.request.urlopen", return_value=_ok("from nous")) as u:
            self.assertEqual(_core._llm_chat("s", "u"), "from nous")
        self.assertEqual(u.call_count, 1)

    def test_a_402_falls_through_to_the_next_provider(self):
        calls = [_http_error(402), _ok("from openrouter")]
        def side(*a, **k):
            r = calls.pop(0)
            if isinstance(r, Exception):
                raise r
            return r
        with mock.patch("urllib.request.urlopen", side_effect=side):
            self.assertEqual(_core._llm_chat("s", "u"), "from openrouter")

    def test_a_refused_provider_is_SKIPPED_not_retried(self):
        # The whole point. One 402 must not become 2,334.
        with mock.patch("urllib.request.urlopen", side_effect=_http_error(402)):
            self.assertIsNone(_core._llm_chat("s", "u"))
        self.assertIn("nous", _core._LLM_REFUSED_UNTIL)
        with mock.patch("urllib.request.urlopen", side_effect=_http_error(402)) as u:
            self.assertIsNone(_core._llm_chat("s", "u"))
            self.assertEqual(u.call_count, 0, "a refused provider must not be called again")

    def test_a_500_is_NOT_treated_as_permanent(self):
        with mock.patch("urllib.request.urlopen", side_effect=_http_error(500)):
            self.assertIsNone(_core._llm_chat("s", "u"))
        self.assertEqual(_core._LLM_REFUSED_UNTIL, {},
                         "a server error is transient; only 401/402/403 are permanent")

    def test_no_provider_returns_None_rather_than_raising(self):
        # Every caller is built on None, including a request handler.
        self.ep.stop()
        with mock.patch.object(_core, "_llm_endpoint", return_value=None):
            self.assertIsNone(_core._llm_chat("s", "u"))
        self.ep.start()

    def test_an_empty_answer_is_not_returned_as_content(self):
        class Empty:
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def read(self):
                return json.dumps({"choices": [{"message": {"content": ""},
                                                "finish_reason": "length"}],
                                   "usage": {"completion_tokens": 8000,
                                             "completion_tokens_details":
                                                 {"reasoning_tokens": 8000}}}).encode()
        with mock.patch("urllib.request.urlopen", return_value=Empty()):
            self.assertIsNone(_core._llm_chat("s", "u"))

    def test_the_request_carries_a_user_agent(self):
        # Without one the Nous edge answers 403 with Cloudflare error 1010,
        # which reads exactly like an auth failure and is not one.
        seen = {}
        def side(req, *a, **k):
            seen.update({k.lower(): v for k, v in req.header_items()})
            return _ok()
        with mock.patch("urllib.request.urlopen", side_effect=side):
            _core._llm_chat("s", "u")
        self.assertIn("user-agent", seen)


class ConfigTests(unittest.TestCase):
    def test_the_model_is_dated_never_a_moving_alias(self):
        # `deepseek-v4-pro` is an undated alias and DeepSeek moved what it
        # points at without renaming it, onto something twice the price.
        self.assertIn("-0731", _core._LLM_MODEL)
        self.assertNotEqual(_core._LLM_MODEL, "deepseek-v4-pro")

    def test_the_old_name_still_resolves_for_existing_callers(self):
        self.assertIs(_core._deepseek_chat, _core._llm_chat)


if __name__ == "__main__":
    unittest.main()
