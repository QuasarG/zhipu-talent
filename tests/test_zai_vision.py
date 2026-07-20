from __future__ import annotations

import os
import unittest
from unittest.mock import MagicMock, patch

from agi_talent_radar.integrations.zai_vision import (
    VisionModelResponseError,
    VisionPage,
    ZaiVisionClient,
    _response_content,
    get_vision_client,
)


class ZaiVisionTest(unittest.TestCase):
    def test_default_client_uses_zai_sdk_configuration(self) -> None:
        with (
            patch.dict(
                os.environ,
                {
                    "Z_AI_API_KEY": "test.test",
                    "Z_AI_VISION_MODEL": "glm-5v-turbo",
                    "VISION_MODEL_ADAPTER": "",
                },
            ),
            patch("zai.ZhipuAiClient") as sdk_client,
        ):
            client = get_vision_client()

        self.assertIsInstance(client, ZaiVisionClient)
        self.assertEqual(client.model, "glm-5v-turbo")
        sdk_client.assert_called_once_with(api_key="test.test", timeout=180.0, max_retries=2)

    def test_analyze_resume_sends_all_pages_in_one_native_request(self) -> None:
        sdk_client = MagicMock()
        sdk_client.chat.completions.create.return_value = _response(
            '{"resume":{"name":"候选人"},"document_analysis":{}}'
        )
        with patch.dict(
            os.environ,
            {
                "Z_AI_VISION_MODEL": "glm-5v-turbo",
                "Z_AI_VISION_THINKING": "enabled",
            },
        ):
            client = ZaiVisionClient(timeout_seconds=30, sdk_client=sdk_client)

        result = client.analyze_resume(
            [
                VisionPage(page_number=1, mime_type="image/png", data_base64="aW1hZ2U="),
                VisionPage(page_number=2, mime_type="image/jpeg", data_base64="aW1hZ2Uy"),
            ],
            "返回简历 JSON",
        )

        self.assertEqual(result["resume"]["name"], "候选人")
        sdk_client.chat.completions.create.assert_called_once()
        request = sdk_client.chat.completions.create.call_args.kwargs
        self.assertEqual(request["model"], "glm-5v-turbo")
        self.assertEqual(request["thinking"], {"type": "enabled"})
        self.assertEqual(request["response_format"], {"type": "json_object"})
        content = request["messages"][0]["content"]
        self.assertEqual([item["type"] for item in content], ["image_url", "image_url", "text"])
        self.assertEqual(content[0]["image_url"]["url"], "data:image/png;base64,aW1hZ2U=")
        self.assertIn("第 1、2 页", content[-1]["text"])

    def test_analyze_resume_rejects_invalid_page_base64_before_request(self) -> None:
        sdk_client = MagicMock()
        client = ZaiVisionClient(sdk_client=sdk_client)

        with self.assertRaisesRegex(ValueError, "不是有效 Base64"):
            client.analyze_resume(
                [VisionPage(page_number=1, mime_type="image/png", data_base64="not-base64!")],
                "返回 JSON",
            )

        sdk_client.chat.completions.create.assert_not_called()

    def test_response_content_rejects_missing_message(self) -> None:
        with self.assertRaises(VisionModelResponseError):
            _response_content(MagicMock(choices=[]))


def _response(content: str):
    response = MagicMock()
    response.choices[0].message.content = content
    return response


if __name__ == "__main__":
    unittest.main()
