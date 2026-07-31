from __future__ import annotations

import unittest
from unittest.mock import patch

from agi_talent_radar.core.connectors.aminer_rest import (
    get_aminer_papers_info,
    search_aminer_papers_by_title,
)

SEARCH_RESPONSE = {
    "code": 200,
    "data": [
        {
            "id": "abc123",
            "title": "GlassWing",
            "authors": [{"name": "Xiangyu Zhang"}],
            "venue_name": "ASE",
            "year": 2025,
        }
    ],
}

INFO_RESPONSE = {
    "code": 200,
    "data": [
        {
            "id": "abc123",
            "title": "GlassWing",
            "author_count": 5,
            "authors": [
                {"name": "Xiangyu Zhang"},
                {"name": "Yucheng Su"},
                {"name": "Lingling Fan"},
                {"name": "Miaoying Cai"},
                {"name": "Sen Chen"},
            ],
            "venue": {"raw": "IEEE TSE"},
            "issue": "12",
            "year": 2025,
        }
    ],
}


class AminerPaperInfoTest(unittest.TestCase):
    def test_get_papers_info_returns_map_by_id(self) -> None:
        with patch(
            "agi_talent_radar.core.connectors.aminer_rest._request",
            return_value=INFO_RESPONSE,
        ) as req:
            info = get_aminer_papers_info(["abc123"])
        self.assertEqual(info["abc123"]["author_count"], 5)
        # 走 POST 且带 ids 参数
        self.assertEqual(req.call_args.kwargs.get("method"), "POST")
        self.assertEqual(req.call_args.kwargs.get("body"), {"ids": ["abc123"]})

    def test_get_papers_info_empty_ids_short_circuits(self) -> None:
        with patch("agi_talent_radar.core.connectors.aminer_rest._request") as req:
            self.assertEqual(get_aminer_papers_info([]), {})
            req.assert_not_called()

    def test_search_enriches_sparse_authors_with_paper_info(self) -> None:
        def fake_request(path, params=None, method="GET", body=None):
            if path == "/api/paper/search":
                return SEARCH_RESPONSE
            if path == "/api/paper/info":
                return INFO_RESPONSE
            raise AssertionError(f"unexpected path: {path}")

        with patch(
            "agi_talent_radar.core.connectors.aminer_rest._request",
            side_effect=fake_request,
        ):
            facts = search_aminer_papers_by_title("GlassWing")

        self.assertEqual(len(facts), 1)
        payload = facts[0].payload
        self.assertEqual(len(payload["authors"]), 5)
        self.assertEqual(payload["authors"][0], "Xiangyu Zhang")
        self.assertEqual(payload["venue"], "IEEE TSE")
        self.assertEqual(payload["issue"], "12")
        self.assertEqual(facts[0].source_url, "https://www.aminer.cn/pub/abc123")

    def test_search_survives_paper_info_failure(self) -> None:
        from agi_talent_radar.core.connectors.base import ConnectorUnavailableError

        def fake_request(path, params=None, method="GET", body=None):
            if path == "/api/paper/search":
                return SEARCH_RESPONSE
            raise ConnectorUnavailableError("详情接口挂了")

        with patch(
            "agi_talent_radar.core.connectors.aminer_rest._request",
            side_effect=fake_request,
        ):
            facts = search_aminer_papers_by_title("GlassWing")

        # 详情失败时保留搜索结果（只回首作者），不抛异常
        self.assertEqual(len(facts), 1)
        self.assertEqual(facts[0].payload["authors"], ["Xiangyu Zhang"])


if __name__ == "__main__":
    unittest.main()
