"""领域契约测试（阶段 0 子集）。

四条边界契约（与计划 §阶段 0 / CONTEXT.md / backend_use_case_decisions.md 对齐）：

1. ``test_import_does_not_admit_to_talent_pool`` —
   导入路径不允许在评估成功前把简历推进人才库。
   通过 ``talent_service`` 接口签名 + NotImplementedError 固化预期。
2. ``test_evaluation_score_does_not_drive_engagement_status`` —
   HR 跟进状态函数不允许基于 overall_score / level / automatic 切换；
   强制要求 ``changed_by`` 与 ``note``。
3. ``test_known_person_investigation_does_not_create_candidate`` —
   ``run_guest_check`` 现状不写 ``CandidateORM`` 也不写 ``EvaluationORM``；
   防止未来有人不小心加 ``session.add(CandidateORM)``。
4. ``test_external_paper_failure_does_not_fail_core_evaluation`` —
   ``run_resume_academic_check`` 在 OpenAlex 抛 ``ConnectorUnavailableError``
   时仍返回报告（带 warning），不破坏 state。

测试以 unittest 形式编写，与现有 93 passed 测试共存。
"""
from __future__ import annotations

import inspect
import unittest
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from agi_talent_radar.agents.academic.nodes import run_resume_academic_check
from agi_talent_radar.agents.reputation.models import ReputationReport
from agi_talent_radar.core.connectors.base import ConnectorUnavailableError
from agi_talent_radar.core.db.orm import (
    Base,
    CandidateORM,
    EvaluationORM,
)
from agi_talent_radar.core.domain_models import (
    ClaimedPublicationStatus,
    EngagementStatus,
    ExternalFactVerification,
    IdentityDecision,
    PublicationVerificationStatus,
    ResearchGroupMatchingStatus,
)
from agi_talent_radar.core.reputation_service import run_guest_check
from agi_talent_radar.services import talent_service


class TestServiceContracts(unittest.TestCase):
    """talent_service 接口签名契约。"""

    def test_import_does_not_admit_to_talent_pool(self) -> None:
        """导入不允许直接绕过评估写入人才库。

        阶段 0：函数体 raise NotImplementedError；
        阶段 1+：函数体已实装，对无效 evaluation_id 抛 ValueError。
        两种行为都被视为契约合规，但都不允许"自动隐式触发"。
        """
        admit_sig = inspect.signature(talent_service.admit_candidate_after_evaluation)
        param_names = list(admit_sig.parameters)
        self.assertEqual(param_names, ["evaluation_id"])
        # 不接受 automatic / overall_score 这种隐式入参。
        for name in param_names:
            self.assertNotIn(
                name.lower(),
                {"automatic", "auto", "overall_score", "level"},
                msg=f"admit_candidate_after_evaluation 不应暴露隐式入参: {name!r}",
            )
        with self.assertRaises((NotImplementedError, ValueError)):
            talent_service.admit_candidate_after_evaluation(1)

    def test_evaluation_score_does_not_drive_engagement_status(self) -> None:
        """HR 跟进状态不允许基于分数、舆情或其他自动规则切换。

        阶段 0 检查 docstring 含关键词；阶段 1+ 直接验证函数签名 + 调用
        缺 changed_by 时抛 ValueError。
        """
        update_sig = inspect.signature(talent_service.update_engagement_status)
        param_names = [name for name in update_sig.parameters]

        # 必须出现 changed_by 和 note 命名形参（按计划 2.3 / 2.1）。
        self.assertIn("changed_by", param_names)
        self.assertIn("note", param_names)
        self.assertIn("status", param_names)

        # 不允许出现自动切换相关的隐式入参。
        forbidden = {"overall_score", "level", "automatic", "auto_score", "auto_switch"}
        for name in param_names:
            self.assertNotIn(
                name.lower(),
                {value.lower() for value in forbidden},
                msg=f"update_engagement_status 不应暴露隐式入参: {name!r}",
            )

        # 模块文档必须显式声明禁止按评分切换（兼容老 docstring 与新版本）。
        module_source = inspect.getsource(talent_service)
        self.assertTrue(
            "overall_score" in module_source
            or "不得基于分数" in module_source
            or "自动规则切换" in module_source,
            msg="talent_service 模块应显式声明禁止按评分 / 自动规则切换。",
        )

        # 函数体仍未实装或实装后拒绝参数，均视为合规。
        with self.assertRaises((NotImplementedError, ValueError)):
            talent_service.update_engagement_status(
                "candidate-1",
                EngagementStatus.CONTACTED,
                changed_by="",
                note="电话联系确认意向",
            )


class TestDomainEnums(unittest.TestCase):
    """新领域枚举成员稳定性。"""

    def test_engagement_status_members(self) -> None:
        self.assertEqual(
            EngagementStatus.all(),
            (
                "newly_admitted",
                "screening",
                "interviewing",
                "offer_pending",
                "offered",
                "hired",
                "departed",
                "rejected",
            ),
        )

    def test_publication_status_members(self) -> None:
        self.assertEqual(
            ClaimedPublicationStatus.all(),
            (
                "draft",
                "submitted",
                "in_review",
                "accepted",
                "published",
                "unknown",
            ),
        )
        self.assertEqual(
            PublicationVerificationStatus.all(),
            ("verified", "pending", "conflict"),
        )

    def test_identity_decision_members(self) -> None:
        self.assertEqual(
            IdentityDecision.all(),
            ("new", "matched", "needs_review", "conflict"),
        )

    def test_external_fact_verification_members(self) -> None:
        self.assertEqual(
            ExternalFactVerification.all(),
            ("confirmed", "pending", "conflict", "disproved", "superseded"),
        )

    def test_research_group_matching_members(self) -> None:
        self.assertEqual(
            ResearchGroupMatchingStatus.all(),
            ("not_configured", "configured", "disabled"),
        )


class TestKnownPersonInvestigationBehavior(unittest.TestCase):
    """已知人物调查现状行为契约。"""

    def setUp(self) -> None:
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)

    def tearDown(self) -> None:
        self.engine.dispose()

    def test_known_person_investigation_does_not_create_candidate(self) -> None:
        """已知人物调查后必须不创建 CandidateORM 也不创建 EvaluationORM。"""
        empty_report = ReputationReport(
            level="green",
            events=[],
            hits=[],
            rationale="无事件",
            warnings=[],
        )
        with self.Session() as session:
            with patch(
                "agi_talent_radar.core.reputation_service.run_reputation_check",
                return_value=empty_report,
            ):
                result = run_guest_check(
                    session,
                    name="张三",
                    org="某大学",
                    direction="Agent",
                )
            self.assertEqual(
                session.query(CandidateORM).count(),
                0,
                msg="已知人物调查不应在数据库中创建候选人才。",
            )
            self.assertEqual(
                session.query(EvaluationORM).count(),
                0,
                msg="已知人物调查不应在数据库中创建评估记录。",
            )
            self.assertIn("person_id", result)


class TestCoreEvaluationDecoupling(unittest.TestCase):
    """核心评估与外部核验链路解耦契约。"""

    def test_external_paper_failure_does_not_fail_core_evaluation(self) -> None:
        """OpenAlex 抛错时学术节点必须返回降级报告，不能破坏 state。"""

        def boom(*_args, **_kwargs):
            raise ConnectorUnavailableError("OpenAlex 调用失败: 模拟网络异常")

        state = {
            "normalized": {
                "id": "resume-1",
                "name": "李四",
                "stage": "博士在读",
                "publications": ["A. Author. Title. NeurIPS 2024."],
                "raw_text": "",
            }
        }
        with patch(
            "agi_talent_radar.agents.academic.nodes.search_works", side_effect=boom
        ):
            result = run_resume_academic_check(state)

        self.assertIn("academic_report", result)
        report = result["academic_report"]
        self.assertTrue(
            report.get("alignments") is not None or report.get("warnings"),
            msg="失败降级报告必须包含 alignments 或 warnings。",
        )
        # 降级时不应让 normalized 数据被破坏。
        self.assertEqual(state["normalized"]["name"], "李四")
        self.assertEqual(state["normalized"]["publications"], ["A. Author. Title. NeurIPS 2024."])
        self.assertIsInstance(result, dict)


if __name__ == "__main__":
    unittest.main()
