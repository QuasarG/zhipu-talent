"""奖学金初筛模块测试：资格门槛 / 完整性 / 脱敏 / 评分 / 舆情调整。

sqlite 内存库 + fake LLM/search，不打外网。
"""
from __future__ import annotations

import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from agi_talent_radar.core.db.orm import Base, ScholarshipEvaluationORM
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


class TestEvaluate(ScholarshipTestBase):
    def test_evaluate_with_fake_llm(self) -> None:
        app = self.make_app()
        self.add_kinds(app, ["resume", "supplementary", "achievement", "letter"])
        pipeline.screen_application(self.session, app)
        fake_llm = lambda prompt, payload: {
            "dimensions": [
                {"key": "research_capability", "score": 4, "reason": "ok"},
                {"key": "originality", "score": 3, "reason": "ok"},
                {"key": "achievement_quality", "score": 5, "reason": "ok"},
                {"key": "engineering", "score": 2, "reason": "ok"},
                {"key": "letter_endorsement", "score": 4, "reason": "ok"},
                {"key": "direction_fit", "score": 5, "reason": "ok"},
            ],
            "highlights": ["强"],
            "risks": ["弱"],
        }
        evaluation = pipeline.evaluate_application(self.session, app, llm=fake_llm)
        self.assertEqual(evaluation.status, "completed")
        # 4/5*25 + 3/5*20 + 5/5*20 + 2/5*15 + 4/5*10 + 5/5*10 = 20+12+20+6+8+10
        self.assertEqual(evaluation.blind_score, 76.0)
        self.assertEqual(app.status, "scored")
        # 评分用的是脱敏文本
        self.assertNotIn("张三", app.materials[0].anonymized_text)

    def test_missing_dimension_zero_filled(self) -> None:
        app = self.make_app()
        self.add_kinds(app, ["resume", "supplementary", "achievement", "letter"])
        fake_llm = lambda prompt, payload: {"dimensions": [], "highlights": [], "risks": []}
        evaluation = pipeline.evaluate_application(self.session, app, llm=fake_llm)
        self.assertEqual(len(evaluation.dimensions), 6)
        self.assertEqual(evaluation.blind_score, 0.0)


class _FakeFact:
    def __init__(self, title, content, url):
        self.payload = {"title": title, "content": content}
        self.source_url = url


class TestReputation(ScholarshipTestBase):
    def _fake_search(self, query, count=5):
        if "争议" in query:
            return [_FakeFact("张三 被指数据造假", "张三 卷入争议", "http://x/1"),
                    _FakeFact("无关新闻", "别人的事", "http://x/2")]
        return [_FakeFact("张三 获优秀学生奖", "张三 被表彰", "http://x/3")]

    def test_scan_review_and_total(self) -> None:
        app = self.make_app()
        items = pipeline.run_reputation_scan(self.session, app, search_fn=self._fake_search)
        # 无关条目被降噪滤掉：申请人负面 1 + 正面 1；导师两轨无命中（fake 只认张三）
        self.assertEqual(len(items), 2)
        neg = next(i for i in items if i.sentiment == "negative")
        pos = next(i for i in items if i.sentiment == "positive")
        pipeline.review_reputation_item(self.session, neg.id, "confirmed", reviewer="hr")
        pipeline.review_reputation_item(self.session, pos.id, "dismissed", reviewer="hr")
        self.session.refresh(app)
        self.assertEqual(pipeline.reputation_adjustment(self.session, app), -5.0)

    def test_adjustment_capped(self) -> None:
        app = self.make_app()
        from agi_talent_radar.core.db.orm import ScholarshipReputationItemORM

        for i in range(4):
            item = ScholarshipReputationItemORM(
                application_id=app.id, subject="张三", sentiment="negative",
                title=f"负面{i}", review_status="confirmed", adjustment=-5.0,
            )
            self.session.add(item)
        self.session.commit()
        self.session.refresh(app)
        self.assertEqual(pipeline.reputation_adjustment(self.session, app), -10.0)

    def test_legacy_brand_bonus_does_not_affect_total(self) -> None:
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
