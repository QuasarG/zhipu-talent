from __future__ import annotations

import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from agi_talent_radar.core import llm_client


class _FakeCompletions:
    def __init__(self, handler):
        self.handler = handler

    def create(self, **kwargs):
        return self.handler(kwargs)


class _FakeClient:
    def __init__(self, handler):
        self.chat = SimpleNamespace(completions=_FakeCompletions(handler))


class _RateLimitError(RuntimeError):
    status_code = 429


def _json_response(content: str = '{"ok": true}'):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
    )


class LlmClientRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        llm_client._CIRCUIT.reset()
        self.previous_client = llm_client._CLIENT

    def tearDown(self) -> None:
        llm_client._CLIENT = self.previous_client
        llm_client._CIRCUIT.reset()

    def test_primary_rate_limit_opens_circuit_and_retries_on_fallback(self) -> None:
        models: list[str] = []
        calls: list[dict[str, str]] = []

        def handler(kwargs):
            models.append(kwargs["model"])
            if kwargs["model"] == "glm-5.3":
                raise _RateLimitError("429")
            return _json_response()

        llm_client._CLIENT = _FakeClient(handler)
        with patch.dict("os.environ", {"OPENAI_MODEL_FALLBACK": "glm-5.2"}):
            result = llm_client.call_llm_json(
                "system",
                {"input": "value"},
                model_override="glm-5.3",
                on_call=calls.append,
            )
            llm_client.call_llm_json("system", {}, model_override="glm-5.3", on_call=calls.append)

        self.assertEqual(result, {"ok": True})
        self.assertEqual(models, ["glm-5.3", "glm-5.2", "glm-5.2"])
        self.assertEqual(calls[0]["model"], "glm-5.2")
        self.assertEqual(calls[0]["fallback_reason"], "rate_limit_circuit_open")

    def test_business_error_1302_is_classified_as_rate_limit(self) -> None:
        error = RuntimeError(
            "Error code: 429 - {'error': {'code': '1302', 'message': '您的账户已达到速率限制'}}"
        )
        self.assertTrue(llm_client._is_rate_limit_error(error))

    def test_non_rate_limit_error_does_not_switch_model(self) -> None:
        models: list[str] = []

        def handler(kwargs):
            models.append(kwargs["model"])
            if len(models) < 3:
                raise TimeoutError("timeout")
            return _json_response()

        llm_client._CLIENT = _FakeClient(handler)
        with (
            patch.dict("os.environ", {"OPENAI_MODEL_FALLBACK": "glm-5.2"}),
            patch.object(llm_client.time, "sleep"),
        ):
            llm_client.call_llm_json("system", {}, model_override="glm-5.3")

        self.assertEqual(models, ["glm-5.3", "glm-5.3", "glm-5.3"])

    def test_all_json_calls_share_global_concurrency_limit(self) -> None:
        lock = threading.Lock()
        active = 0
        peak = 0

        def handler(_kwargs):
            nonlocal active, peak
            with lock:
                active += 1
                peak = max(peak, active)
            time.sleep(0.03)
            with lock:
                active -= 1
            return _json_response()

        llm_client._CLIENT = _FakeClient(handler)
        threads = [
            threading.Thread(
                target=llm_client.call_llm_json,
                args=("system", {"index": index}),
                kwargs={"model_override": "glm-5.2"},
            )
            for index in range(12)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertLessEqual(peak, 50)
        self.assertEqual(peak, 12)


if __name__ == "__main__":
    unittest.main()
