from __future__ import annotations

import unittest
from unittest.mock import patch

from agi_talent_radar.core.connectors.base import ConnectorUnavailableError
from agi_talent_radar.core.connectors.web_search import search_web

HITS = [
    {"title": "南开实验室研讨会", "link": "https://cc.nankai.edu.cn/x", "content": "张向宇分享口令安全", "refer": "ref_1"},
    {"title": "", "link": "", "content": ""},
    "not-a-dict",
]


class WebSearchMcpTest(unittest.TestCase):
    def test_maps_mcp_hits_to_facts(self) -> None:
        with (
            patch.dict("os.environ", {"Z_AI_API_KEY": "test-key"}),
            patch("agi_talent_radar.core.connectors.web_search._fetch", return_value=HITS),
        ):
            facts = search_web("张向宇 南开大学")
        self.assertEqual(len(facts), 2)
        self.assertEqual(facts[0].source, "web_search")
        self.assertEqual(facts[0].payload["title"], "南开实验室研讨会")
        self.assertEqual(facts[0].payload["media"], "ref_1")
        self.assertEqual(facts[0].source_url, "https://cc.nankai.edu.cn/x")

    def test_missing_api_key_raises_unavailable(self) -> None:
        with patch.dict("os.environ", {"Z_AI_API_KEY": ""}):
            with self.assertRaises(ConnectorUnavailableError):
                search_web("query")

    def test_fetch_failure_wrapped_as_unavailable(self) -> None:
        with (
            patch.dict("os.environ", {"Z_AI_API_KEY": "test-key"}),
            patch("agi_talent_radar.core.connectors.web_search._fetch", side_effect=RuntimeError("boom")),
        ):
            with self.assertRaises(ConnectorUnavailableError):
                search_web("query")


if __name__ == "__main__":
    unittest.main()
