from __future__ import annotations

import os
import unittest
from unittest.mock import MagicMock, patch

from agi_talent_radar.core.llm_client import _loads_json, call_llm_json, call_llm_stream


class LLMClientTest(unittest.TestCase):
    def test_loads_json_repairs_missing_comma(self) -> None:
        result = _loads_json('{"resume": {"name": "么琳" "stage": "博士在读"}}')

        self.assertEqual(result["resume"]["name"], "么琳")
        self.assertEqual(result["resume"]["stage"], "博士在读")

    def test_call_llm_json_regenerates_when_local_repair_cannot_make_object(self) -> None:
        first = _response("not a json object")
        second = _response('{"resume": {"name": "么琳"}}')
        client = MagicMock()
        client.chat.completions.create.side_effect = [first, second]

        with (
            patch("agi_talent_radar.core.llm_client._client", return_value=client),
            patch.dict(
                os.environ,
                {
                    "OPENAI_MODEL": "test-model",
                    "OPENAI_TIMEOUT_SECONDS": "5",
                },
            ),
        ):
            result = call_llm_json("输出 JSON", {"resume": "input"})

        self.assertEqual(result["resume"]["name"], "么琳")
        self.assertEqual(client.chat.completions.create.call_count, 2)
        retry_messages = client.chat.completions.create.call_args_list[1].kwargs["messages"]
        self.assertIn("解析错误", retry_messages[-1]["content"])

    def test_call_llm_stream_retries_429_before_first_content(self) -> None:
        client = MagicMock()
        client.chat.completions.create.side_effect = [RuntimeError("429 rate limit"), [_chunk("ok")]]

        with (
            patch("agi_talent_radar.core.llm_client._client", return_value=client),
            patch("agi_talent_radar.core.llm_client.time.sleep") as sleep,
            patch.dict(os.environ, {"OPENAI_MODEL": "test-model", "OPENAI_TIMEOUT_SECONDS": "5"}),
        ):
            result = list(call_llm_stream("输出 JSONL", {"resume": "input"}))

        self.assertEqual(result, ["ok"])
        self.assertEqual(client.chat.completions.create.call_count, 2)
        sleep.assert_called_once_with(1.0)

    def test_call_llm_stream_does_not_retry_after_content_was_emitted(self) -> None:
        def broken_stream():
            yield _chunk("partial")
            raise RuntimeError("stream disconnected")

        client = MagicMock()
        client.chat.completions.create.return_value = broken_stream()
        with (
            patch("agi_talent_radar.core.llm_client._client", return_value=client),
            patch.dict(os.environ, {"OPENAI_MODEL": "test-model", "OPENAI_TIMEOUT_SECONDS": "5"}),
        ):
            with self.assertRaisesRegex(RuntimeError, "stream disconnected"):
                list(call_llm_stream("输出 JSONL", {"resume": "input"}))

        self.assertEqual(client.chat.completions.create.call_count, 1)


def _response(content: str):
    response = MagicMock()
    response.choices[0].message.content = content
    return response


def _chunk(content: str):
    chunk = MagicMock()
    chunk.choices = [MagicMock()]
    chunk.choices[0].delta.content = content
    return chunk


if __name__ == "__main__":
    unittest.main()
