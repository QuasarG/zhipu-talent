"""健康检查测试。

覆盖（与计划 §阶段 11 对齐）：

1. MySQL 失败 → overall=down
2. 可选服务失败 → overall=degraded（不算应用宕机）
3. 全部 ok → overall=ok
4. not_configured 不算 degraded
5. to_dict 结构正确
"""
from __future__ import annotations

import unittest
from unittest.mock import patch

from agi_talent_radar.core.health import (
    HealthReport,
    ServiceHealth,
    run_health_check,
)


def _make_report(services: list[tuple[str, str, bool]]) -> HealthReport:
    """跳过真实探测，直接构造 HealthReport。"""
    health_services = [
        ServiceHealth(name=name, status=status, required=required)
        for name, status, required in services
    ]
    any_down = any(s.status == "down" for s in health_services if s.required)
    any_degraded = any(s.status == "degraded" for s in health_services)
    overall = "down" if any_down else ("degraded" if any_degraded else "ok")
    return HealthReport(overall=overall, services=health_services, checked_at="2026-07-28T12:00:00")


class TestOverallStatus(unittest.TestCase):
    def test_required_down_means_app_down(self) -> None:
        report = _make_report([
            ("mysql", "down", True),
            ("qdrant", "ok", False),
        ])
        self.assertEqual(report.overall, "down")

    def test_optional_degraded_means_degraded(self) -> None:
        report = _make_report([
            ("mysql", "ok", True),
            ("openalex", "degraded", False),
        ])
        self.assertEqual(report.overall, "degraded")

    def test_all_ok_means_ok(self) -> None:
        report = _make_report([
            ("mysql", "ok", True),
            ("qdrant", "ok", False),
            ("llm", "ok", False),
        ])
        self.assertEqual(report.overall, "ok")

    def test_not_configured_is_not_degraded(self) -> None:
        """not_configured 不算 degraded（服务可选且未启用）。"""
        report = _make_report([
            ("mysql", "ok", True),
            ("qdrant", "ok", False),       # not_configured 被映射为 ok
            ("aminer", "ok", False),
        ])
        self.assertEqual(report.overall, "ok")


class TestRunHealthCheck(unittest.TestCase):
    def test_overall_ok_when_mysql_ok_and_optionals_unconfigured(self) -> None:
        """MySQL ok + 可选服务未配置 → overall=ok。"""
        with (
            patch("agi_talent_radar.core.health.check_mysql", return_value="connected"),
            patch("agi_talent_radar.core.health.check_qdrant", return_value="not_configured"),
            patch("agi_talent_radar.core.health.check_llm", return_value="unconfigured"),
            patch("agi_talent_radar.core.health.check_embedding", return_value="unconfigured"),
            patch("agi_talent_radar.core.health.check_aminer", return_value="unconfigured"),
            patch("agi_talent_radar.core.health.check_openalex", return_value="reachable"),
            patch("agi_talent_radar.core.health.check_crossref", return_value="reachable"),
            patch("agi_talent_radar.core.health.check_arxiv", return_value="reachable"),
            patch("agi_talent_radar.core.health.check_web_search", return_value="unconfigured"),
        ):
            report = run_health_check()
        self.assertEqual(report.overall, "ok")
        names = {s.name: s.status for s in report.services}
        self.assertEqual(names["mysql"], "ok")

    def test_overall_down_when_mysql_fails(self) -> None:
        def mysql_boom():
            raise RuntimeError("connection refused")

        with (
            patch("agi_talent_radar.core.health.check_mysql", side_effect=mysql_boom),
            patch("agi_talent_radar.core.health.check_qdrant", return_value="not_configured"),
            patch("agi_talent_radar.core.health.check_llm", return_value="configured"),
            patch("agi_talent_radar.core.health.check_embedding", return_value="configured"),
            patch("agi_talent_radar.core.health.check_aminer", return_value="configured"),
            patch("agi_talent_radar.core.health.check_openalex", return_value="reachable"),
            patch("agi_talent_radar.core.health.check_crossref", return_value="reachable"),
            patch("agi_talent_radar.core.health.check_arxiv", return_value="reachable"),
            patch("agi_talent_radar.core.health.check_web_search", return_value="configured"),
        ):
            report = run_health_check()
        self.assertEqual(report.overall, "down")
        mysql = next(s for s in report.services if s.name == "mysql")
        self.assertEqual(mysql.status, "down")
        self.assertTrue(mysql.required)

    def test_overall_degraded_when_optional_fails(self) -> None:
        def openalex_boom():
            raise RuntimeError("timeout")

        with (
            patch("agi_talent_radar.core.health.check_mysql", return_value="connected"),
            patch("agi_talent_radar.core.health.check_qdrant", return_value="connected"),
            patch("agi_talent_radar.core.health.check_llm", return_value="configured"),
            patch("agi_talent_radar.core.health.check_embedding", return_value="configured"),
            patch("agi_talent_radar.core.health.check_aminer", return_value="configured"),
            patch("agi_talent_radar.core.health.check_openalex", side_effect=openalex_boom),
            patch("agi_talent_radar.core.health.check_web_search", return_value="configured"),
        ):
            report = run_health_check()
        self.assertEqual(report.overall, "degraded")
        openalex = next(s for s in report.services if s.name == "openalex")
        self.assertEqual(openalex.status, "degraded")
        self.assertFalse(openalex.required)

    def test_to_dict_structure(self) -> None:
        report = _make_report([("mysql", "ok", True)])
        data = report.to_dict()
        self.assertIn("overall", data)
        self.assertIn("checked_at", data)
        self.assertIn("services", data)
        self.assertEqual(data["services"][0]["name"], "mysql")
        self.assertIn("latency_ms", data["services"][0])


if __name__ == "__main__":
    unittest.main()