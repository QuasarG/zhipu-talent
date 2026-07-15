from __future__ import annotations

import os
import unittest
from unittest.mock import MagicMock, patch

from agi_talent_radar.core.llm_client import _loads_json, call_llm_json


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


def _response(content: str):
    response = MagicMock()
    response.choices[0].message.content = content
    return response


if __name__ == "__main__":
    unittest.main()
