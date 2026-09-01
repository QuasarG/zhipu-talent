"""奖学金初筛模块测试：资格门槛 / 完整性 / 脱敏 / 评分 / 舆情调整。

sqlite 内存库 + fake LLM/search，不打外网。
"""
from __future__ import annotations

import json
import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from agi_talent_radar.core.db.orm import Base, ScholarshipEvaluationORM, ScholarshipMaterialORM
from agi_talent_radar.scholarship import ingest, pipeline
from agi_talent_radar.scholarship.anonymize import anonymize_text, build_identities, check_leak


class ScholarshipTestBase(unittest.TestCase):
    def setUp(self) -> None:
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        self.session = sessionmaker(bind=engine, expire_on_commit=False)()

    def tearDown(self) -> None:
        self.session.close()

    def make_app(self, **kwargs):
        defaults = {
            "name": "张三",
            "degree_type": "phd",
            "expected_graduation": "2028-06",
            "direction": "Agent Systems",
            "school": "某大学",
            "advisors": ["王教授"],
        }
        defaults.update(kwargs)
        return ingest.create_application(self.session, **defaults)

    def add_kinds(self, app, kinds) -> None:
        for i, kind in enumerate(kinds):
            ingest.add_material(self.session, app, f"{kind}{i}.txt", f"{kind} 内容".encode(), kind=kind)


class TestScreening(ScholarshipTestBase):
    def test_eligible_passes(self) -> None:
        app = self.make_app()
        self.add_kinds(app, ["resume", "supplementary", "achievement", "letter"])
        result = pipeline.screen_application(self.session, app)
        self.assertEqual(result["status"], "eligible")

    def test_missing_letter(self) -> None:
        app = self.make_app()
        self.add_kinds(app, ["resume", "supplementary", "achievement"])
        result = pipeline.screen_application(self.session, app)
        self.assertEqual(result["status"], "material_incomplete")
        self.assertIn("letter", result["missing"])

    def test_undergraduate_rejected(self) -> None:
        app = self.make_app(degree_type="bachelor")
        self.add_kinds(app, ["resume", "supplementary", "achievement", "letter"])
        result = pipeline.screen_application(self.session, app)
        self.assertEqual(result["status"], "ineligible")
        self.assertTrue(any("硕士或博士" in r for r in result["reasons"]))

    def test_early_graduation_rejected(self) -> None:
        app = self.make_app(expected_graduation="2026-06")
        self.add_kinds(app, ["resume", "supplementary", "achievement", "letter"])
        result = pipeline.screen_application(self.session, app)
        self.assertEqual(result["status"], "ineligible")
        self.assertTrue(any("2027-06" in r for r in result["reasons"]))

    def test_irrelevant_direction_rejected_by_llm(self) -> None:
        app = self.make_app(direction="中国古代文学")
        self.add_kinds(app, ["resume", "supplementary", "achievement", "letter"])
        fake = lambda prompt, payload: {"relevant": False, "reason": "纯文学方向"}
        result = pipeline.screen_application(self.session, app, llm_judge=fake)
        self.assertEqual(result["status"], "ineligible")
        self.assertTrue(any("不相关" in r for r in result["reasons"]))


class TestAnonymize(ScholarshipTestBase):
    def test_variants_replaced(self) -> None:
        app = self.make_app(name="李博杰（Bojie Li）")
        identities = build_identities(app)
        text = "李博杰（Bojie Li）在某大学师从王教授，Bojie Li 发表了论文。"
        out = anonymize_text(text, identities)
        self.assertNotIn("李博杰", out)
        self.assertNotIn("Bojie Li", out)
        self.assertNotIn("某大学", out)
        self.assertNotIn("王教授", out)
        self.assertEqual(check_leak(out, identities), [])

    def test_leak_check_finds_residue(self) -> None:
        app = self.make_app()
        identities = build_identities(app)
        self.assertIn("张三", check_leak("张三的成绩单", identities))


class TestScorerAgent(ScholarshipTestBase):
    def _fake_llm(self, calls, final_dims):
        def llm(messages, tools, **kw):
            n = len(calls); calls.append(n)
            if n == 0:
                return {"text": "", "tool_calls": [{"id": "c0", "name": "list_files", "arguments": "{}"}]}
            materials = [m for m in self.session.query(ScholarshipMaterialORM).all()]
            if n <= len(materials):
                mid = materials[n - 1].id
                return {"text": "", "tool_calls": [{"id": f"c{n}", "name": "read_file",
                        "arguments": json.dumps({"file_id": mid})}]}
            return {"text": "done", "tool_calls": [{"id": f"c{n}", "name": "submit_scores",
                    "arguments": json.dumps({"dimensions": final_dims, "recommend_tier": "recommend"})}]}
        return llm

    def test_agent_scores_and_blind_total(self) -> None:
        from unittest.mock import patch

        from agi_talent_radar.core import llm_client
        from agi_talent_radar.scholarship import scorer_agent

        app = self.make_app()
        self.add_kinds(app, ["resume", "supplementary", "achievement", "letter"])
        evaluation = ScholarshipEvaluationORM(application_id=app.id, status="running")
        self.session.add(evaluation)
        self.session.commit()
        dims = [
            {"key": "academic_impact", "score": 3.5, "reason": "论文经公开库查证存在", "evidence_level": "verified"},
            {"key": "originality", "score": 3, "reason": "框架内改进有初步佐证", "evidence_level": "supported"},
            {"key": "independence", "score": 3, "reason": "自主完成子课题闭环", "evidence_level": "supported"},
            {"key": "engineering", "score": 2, "reason": "课程级系统无工件佐证", "evidence_level": "claimed"},
            {"key": "letter_endorsement", "score": 3, "reason": "有具体事例与横向比较", "evidence_level": "supported"},
            {"key": "integrity_risk", "score": 9, "reason": "材料一致时间线合理", "evidence_level": "supported"},
        ]
        calls: list[int] = []
        with patch.object(llm_client, "call_llm_tools", self._fake_llm(calls, dims)):
            out = scorer_agent.run_scorer_agent(self.session, app, evaluation, lambda t, p: None)
        self.assertEqual(out.status, "completed")
        # 17.5+12+12+6+6+9 = 62.5
        self.assertEqual(out.blind_score, 62.5)
        self.assertTrue(any(s.get("type") == "final" for s in out.trace))
        # trace 不得泄漏申请人姓名
        self.assertNotIn("张三", json.dumps(out.trace, ensure_ascii=False))

    def test_agent_rejects_unread_materials(self) -> None:
        from unittest.mock import patch

        from agi_talent_radar.core import llm_client
        from agi_talent_radar.scholarship import scorer_agent

        app = self.make_app()
        self.add_kinds(app, ["resume", "achievement"])
        evaluation = ScholarshipEvaluationORM(application_id=app.id, status="running")
        self.session.add(evaluation)
        self.session.commit()
        dims = [
            {"key": "academic_impact", "score": 3, "reason": "ok 证据充分"},
            {"key": "originality", "score": 3, "reason": "ok 证据充分"},
            {"key": "independence", "score": 3, "reason": "ok 证据充分"},
            {"key": "engineering", "score": 3, "reason": "ok 证据充分"},
            {"key": "letter_endorsement", "score": 3, "reason": "ok 证据充分"},
            {"key": "integrity_risk", "score": 8, "reason": "ok 证据充分"},
        ]

        def llm(messages, tools, **kw):
            return {"text": "", "tool_calls": [{"id": "c1", "name": "list_files", "arguments": "{}"}]}

        with patch.object(llm_client, "call_llm_tools", llm):
            out = scorer_agent.run_scorer_agent(self.session, app, evaluation, lambda t, p: None)
        # 全程没读任何材料就到预算 → 未提交终态 → failed
        self.assertEqual(out.status, "failed")


class TestTotal(ScholarshipTestBase):
    def test_total_is_blind_score_only(self) -> None:
        app = self.make_app()
        app.brand_bonus = 8.0
        self.session.add(ScholarshipEvaluationORM(
            application_id=app.id,
            config_version="test",
            status="completed",
            blind_score=76.0,
        ))
        self.session.commit()
        self.assertEqual(pipeline.total_score(self.session, app), 76.0)


class TestIngest(ScholarshipTestBase):
    def test_classify_filename(self) -> None:
        self.assertEqual(ingest.classify_filename("张三_简历.pdf"), "resume")
        self.assertEqual(ingest.classify_filename("CV_Zhang.pdf"), "resume")
        self.assertEqual(ingest.classify_filename("推荐信1.pdf"), "letter")
        self.assertEqual(ingest.classify_filename("申请补充表.pdf"), "supplementary")
        self.assertEqual(ingest.classify_filename("Z.AI申请表.pdf"), "form")
        self.assertEqual(ingest.classify_filename("论文合集.pdf"), "achievement")

    def test_letter_limit(self) -> None:
        app = self.make_app()
        self.add_kinds(app, ["letter", "letter"])
        with self.assertRaises(ValueError):
            ingest.add_material(self.session, app, "推荐信3.txt", b"x", kind="letter")


if __name__ == "__main__":
    unittest.main()
