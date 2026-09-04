from __future__ import annotations

import io
import json
import os
import threading
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from agi_talent_radar.core.db.orm import Base
from agi_talent_radar.web.workbench import create_app
from tests.resume_fixtures import make_resume_fixtures


ROOT = Path(__file__).resolve().parents[1]


class WorkbenchTest(unittest.TestCase):
    _saved_url: str | None = None

    @classmethod
    def setUpClass(cls) -> None:
        # 无 MySQL 的环境也能跑：StaticPool 内存 sqlite（跨线程共享同一份数据）
        cls._saved_url = os.environ.get("DATABASE_URL")
        cls._engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(cls._engine)
        os.environ["DATABASE_URL"] = "sqlite://"

        import agi_talent_radar.core.db.runtime as runtime

        runtime._ENGINES["sqlite://"] = cls._engine

    @classmethod
    def tearDownClass(cls) -> None:
        import agi_talent_radar.core.db.runtime as runtime

        runtime._ENGINES.pop("sqlite://", None)
        cls._engine.dispose()
        if cls._saved_url is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = cls._saved_url

    def setUp(self) -> None:
        # 阶段 8 之后 create_app 注册了鉴权 middleware；
        # 既有 workbench 测试关注路由行为而非鉴权，统一放行。
        self._auth_patch = patch(
            "agi_talent_radar.web.auth.is_authenticated",
            return_value=True,
        )
        self._auth_patch.start()
        self.app = create_app().test_client()

    def tearDown(self) -> None:
        self._auth_patch.stop()

    def _parse_sse(self, response) -> list[dict]:
        events: list[dict] = []
        for line in response.data.decode("utf-8").splitlines():
            if line.startswith("data: "):
                payload = line[6:]
                if payload == "[DONE]":
                    events.append({"done": True})
                else:
                    events.append(json.loads(payload))
        return events

    def test_index_loads(self) -> None:
        """React SPA shell：GET / 返回 index.html（React Router 接管）。"""
        response = self.app.get("/")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("root", html)

    def test_spa_fallback_serves_deep_links(self) -> None:
        """SPA 历史路由兜底：刷新 / 直链任意页面路径都返回 SPA shell，不再 404。"""
        for path in (
            "/talent-evaluation/admission",
            "/talent-evaluation",
            "/chat",
            "/jd-pool",
            "/scholarship/1",
            "/settings",
        ):
            response = self.app.get(path)
            self.assertEqual(response.status_code, 200, path)
            self.assertIn("root", response.get_data(as_text=True))

    def test_spa_fallback_keeps_api_404(self) -> None:
        """未知 API 路径不落入 SPA 兜底，保持 JSON 404。"""
        response = self.app.get("/api/not-a-real-endpoint")
        self.assertEqual(response.status_code, 404)
        self.assertIn("detail", response.get_json())

    def test_resume_original_metadata_and_pdf_headers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "candidate-pdf.pdf").write_bytes(b"%PDF-1.4\nvalid")
            with patch("agi_talent_radar.core.pdf_storage._ROOT", root):
                metadata = self.app.get("/api/candidates/candidate-pdf/original-metadata")
                preview = self.app.get("/api/candidates/candidate-pdf/original-file")
                download = self.app.get("/api/candidates/candidate-pdf/original-file?download=1")
                preview.close()
                download.close()

        self.assertEqual(metadata.status_code, 200)
        self.assertTrue(metadata.get_json()["previewable"])
        self.assertEqual(metadata.get_json()["mime_type"], "application/pdf")
        self.assertEqual(preview.status_code, 200)
        self.assertEqual(preview.content_type, "application/pdf")
        self.assertIn("inline", preview.headers["Content-Disposition"])
        self.assertEqual(preview.headers["X-Frame-Options"], "SAMEORIGIN")
        self.assertEqual(preview.headers["Content-Security-Policy"], "frame-ancestors 'self'")
        self.assertIn("attachment", download.headers["Content-Disposition"])

    def test_resume_original_metadata_handles_missing_empty_and_corrupt_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch("agi_talent_radar.core.pdf_storage._ROOT", root):
                missing = self.app.get("/api/candidates/missing/original-metadata").get_json()
                (root / "empty.pdf").write_bytes(b"")
                empty = self.app.get("/api/candidates/empty/original-metadata").get_json()
                (root / "corrupt.pdf").write_bytes(b"not a pdf")
                corrupt = self.app.get("/api/candidates/corrupt/original-metadata").get_json()

        self.assertFalse(missing["exists"])
        self.assertFalse(empty["previewable"])
        self.assertIn("为空", empty["error"])
        self.assertTrue(corrupt["exists"])
        self.assertFalse(corrupt["previewable"])
        self.assertIn("文件头无效", corrupt["error"])
        self.assertTrue(corrupt["download_url"].endswith("download=1"))

    @patch(
        "agi_talent_radar.web.workbench._list_dist_assets",
        side_effect=[["assets/index-old.js"], ["assets/index-current.js"]],
    )
    def test_spa_shell_refreshes_built_asset_names(self, mock_assets) -> None:
        client = create_app().test_client()

        first = client.get("/").get_data(as_text=True)
        second = client.get("/").get_data(as_text=True)

        self.assertIn("index-old.js", first)
        self.assertIn("index-current.js", second)
        self.assertEqual(mock_assets.call_count, 2)

    @patch("agi_talent_radar.core.database.get_candidate_with_latest_evaluation")
    def test_candidate_detail_returns_resume_card_fields(self, mock_get) -> None:
        mock_row = MagicMock()
        mock_row.id = "candidate_01"
        mock_row.name = "候选人01"
        mock_row.target_role = "大模型研究员"
        mock_row.stage = "博士一年级"
        mock_row.group = "pending"
        mock_row.import_level = "A"
        mock_row.import_category = "研究探索型"
        mock_row.import_confidence = 0.92
        mock_row.raw_text = "raw"
        mock_row.education = json.dumps(["博士，计算机科学"], ensure_ascii=False)
        mock_row.directions = json.dumps(["LLM Agent"], ensure_ascii=False)
        # 阶段 1 新字段 mock
        mock_row.person_id = None
        mock_row.engagement_status = "newly_admitted"
        mock_row.admitted_at = None
        mock_row.sources = []
        mock_row.academic_check_status = "none"
        mock_row.academic_report = {}
        mock_row.experiences = json.dumps(
            [{"organization": "某技术公司", "role": "Agent 研发实习生", "details": ["构建评测闭环"]}],
            ensure_ascii=False,
        )
        mock_row.projects = json.dumps([{"name": "AgentBench", "details": ["构建评测框架"]}], ensure_ascii=False)
        mock_row.publications = json.dumps(["ACL 论文"], ensure_ascii=False)
        mock_row.skills = json.dumps(["Python", "PyTorch"], ensure_ascii=False)
        mock_row.screening_tags = json.dumps(["强工程闭环"], ensure_ascii=False)
        mock_eval = MagicMock()
        mock_eval.overall_score = 75
        mock_eval.level = "A"
        mock_eval.tier = "强烈建议沟通"
        mock_eval.decision_method = "75 分按系统规则进入备选库。"
        mock_eval.one_liner = "高潜候选人"
        mock_eval.core_strengths = ["工程闭环强"]
        mock_eval.potential_risks = []
        mock_eval.interview_questions = []
        mock_eval.cultivation_direction = []
        mock_eval.dimension_scores = []
        mock_eval.evidence = []
        mock_eval.critic_flags = []
        mock_eval.normalized_education = ["学校层级=强研究型；具体学校/GPA/排名已折叠。"]
        mock_eval.screening_tags = ["强工程闭环"]
        mock_eval.evaluation_mode = "glm_ai_only"
        mock_get.return_value = (mock_row, mock_eval)

        response = self.app.get("/api/candidates/candidate_01")
        self.assertEqual(response.status_code, 200, response.get_json())
        data = response.get_json()
        self.assertEqual(data["education"], ["博士，计算机科学"])
        self.assertEqual(data["directions"], ["LLM Agent"])
        self.assertEqual(data["experiences"][0]["role"], "Agent 研发实习生")
        self.assertEqual(data["projects"][0]["name"], "AgentBench")
        self.assertEqual(data["publications"], ["ACL 论文"])
        self.assertEqual(data["skills"], ["Python", "PyTorch"])
        self.assertEqual(data["screening_tags"], ["强工程闭环"])
        self.assertEqual(data["evaluation"]["decision_method"], "75 分按系统规则进入备选库。")
        self.assertEqual(data["evaluation"]["normalized_education"], ["学校层级=强研究型；具体学校/GPA/排名已折叠。"])
        self.assertEqual(data["latest_evaluation"]["screening_tags"], ["强工程闭环"])

    def test_candidate_detail_applies_human_publication_verdict(self) -> None:
        from agi_talent_radar.web.workbench import _orm_to_detail

        row = SimpleNamespace(
            id="candidate-reviewed",
            name="人工已核验",
            target_role="研究员",
            stage="博士候选人",
            group="pending",
            import_level="",
            import_category="研究探索型",
            import_confidence=0.9,
            raw_text="Paper A",
            education="[]",
            directions="[]",
            experiences="[]",
            projects="[]",
            publications='["Paper A"]',
            skills="[]",
            screening_tags="[]",
            source_format="text",
            document_analysis="{}",
            academic_check_status="done",
            academic_report={
                "alignments": [
                    {
                        "claim": {"title": "Paper A"},
                        "verdict": "unverifiable",
                        "human_status": "confirmed",
                    }
                ],
                "warnings": [],
            },
            person_id=None,
            engagement_status="newly_admitted",
            admitted_at=None,
            sources=[],
        )

        detail = _orm_to_detail(row)

        alignment = detail["academic_report"]["alignments"][0]
        self.assertEqual(alignment["verdict"], "verified")
        self.assertEqual(alignment["machine_verdict"], "unverifiable")
        self.assertEqual(detail["verification_result"], "verified")
        self.assertTrue(detail["evaluable"])

    def test_save_candidate_persists_resume_card_fields(self) -> None:
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker

        from agi_talent_radar.core.database import Base, CandidateORM, save_candidate
        from agi_talent_radar.core.models import CandidateResume, ImportClassification, ResumeExperience, ResumeProject

        engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine)
        resume = CandidateResume(
            id="candidate_99",
            name="候选人99",
            target_role="Agent 工程师",
            stage="博士二年级",
            education=["博士，计算机科学"],
            directions=["LLM Agent"],
            experiences=[
                ResumeExperience(
                    organization="某技术公司",
                    role="Agent 研发实习生",
                    period="2025.01 - 2025.06",
                    details=["构建工具调用闭环"],
                )
            ],
            projects=[ResumeProject(name="AgentBench", details=["构建评测框架"])],
            publications=["ACL 论文"],
            skills=["Python", "PyTorch"],
            screening_tags=["强工程闭环"],
            raw_text="raw",
        )
        classification = ImportClassification(
            id="candidate_99",
            name="候选人99",
            category="工程闭环型",
            level="A",
            confidence=0.91,
            reason="项目闭环完整",
        )

        with Session() as session:
            save_candidate(session, resume, classification)
            row = session.query(CandidateORM).filter_by(id="candidate_99").one()
            self.assertEqual(json.loads(row.education), ["博士，计算机科学"])
            self.assertEqual(json.loads(row.directions), ["LLM Agent"])
            self.assertEqual(json.loads(row.experiences)[0]["role"], "Agent 研发实习生")
            self.assertEqual(json.loads(row.projects)[0]["name"], "AgentBench")
            self.assertEqual(json.loads(row.publications), ["ACL 论文"])
            self.assertEqual(json.loads(row.skills), ["Python", "PyTorch"])
            self.assertEqual(json.loads(row.screening_tags), ["强工程闭环"])

    def test_save_evaluation_persists_normalized_card_fields(self) -> None:
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker

        from agi_talent_radar.core.database import Base, CandidateORM, EvaluationORM, save_evaluation
        from agi_talent_radar.core.models import CandidateEvaluation

        engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine)
        evaluation = CandidateEvaluation(
            id="candidate_99",
            name="候选人99",
            target_role="Agent 工程师",
            stage="博士二年级",
            overall_score=75,
            one_liner="高潜候选人",
            core_strengths=[],
            potential_risks=[],
            interview_questions=[],
            cultivation_direction=[],
            dimension_scores=[],
            evidence=[],
            critic_flags=["需验证指标真实性"],
            normalized_education=["学校层级=强研究型；具体学校/GPA/排名已折叠。"],
            screening_tags=["强工程闭环"],
        )

        with Session() as session:
            session.add(CandidateORM(id="candidate_99", name="候选人99", group="pending"))
            session.commit()
            save_evaluation(session, evaluation)
            row = session.query(EvaluationORM).filter_by(candidate_id="candidate_99").one()
            self.assertEqual(row.normalized_education, ["学校层级=强研究型；具体学校/GPA/排名已折叠。"])
            self.assertEqual(row.screening_tags, ["强工程闭环"])
            self.assertEqual(row.critic_flags, ["需验证指标真实性"])
            self.assertEqual(row.decision_method, "")

    def _post_jsonl_import(self, source, classification) -> list[dict]:
        with patch(
            "agi_talent_radar.web.workbench.run_import_agent_stream",
            return_value=iter([classification]),
        ):
            response = self.app.post(
                "/api/import-file",
                data={"file": (io.BytesIO((source.model_dump_json() + "\n").encode("utf-8")), "guard.jsonl")},
                content_type="multipart/form-data",
            )
            self.assertEqual(response.status_code, 200)
            # SSE 生成器在消费时才执行，必须在 patch 生效期内解析
            return self._parse_sse(response)

    def _make_same_person_classification(self, source, matched_id: str):
        classification = MagicMock()
        classification.id = source.id
        classification.name = source.name
        classification.category = "研究探索型"
        classification.level = "A"
        classification.confidence = 0.98
        classification.reason = "测试身份护栏"
        classification.identity_decision = "same_person"
        classification.matched_candidate_id = matched_id
        classification.identity_confidence = 0.98
        classification.identity_evidence = []
        classification.identity_conflicts = []
        return classification

    def test_import_never_merges_when_names_differ(self) -> None:
        """身份护栏：same_person 判定遇到姓名不一致，强制新建，不覆盖旧候选人。"""
        from agi_talent_radar.core.database import get_session, save_candidate
        from agi_talent_radar.core.db.orm import CandidateORM
        from agi_talent_radar.core.models import CandidateResume

        with get_session() as session:
            save_candidate(session, CandidateResume(id="guard_target", name="吴语乐天", raw_text="原始内容"))
        source = make_resume_fixtures()[0].model_copy(update={"id": "guard_source", "name": "张三"})
        try:
            events = self._post_jsonl_import(source, self._make_same_person_classification(source, "guard_target"))
            candidate_event = next(e for e in events if e["type"] == "candidate")
            self.assertEqual(candidate_event["candidate"]["id"], "guard_source")
            with get_session() as session:
                target = session.get(CandidateORM, "guard_target")
                self.assertEqual(target.name, "吴语乐天")
                self.assertEqual(target.raw_text, "原始内容")
                self.assertIsNotNone(session.get(CandidateORM, "guard_source"))
        finally:
            with get_session() as session:
                for cid in ("guard_target", "guard_source"):
                    row = session.get(CandidateORM, cid)
                    if row:
                        session.delete(row)
                session.commit()

    def test_import_never_merges_when_name_unreadable(self) -> None:
        """身份护栏：OCR 读不出姓名时无法核验身份，强制新建，不允许并档。"""
        from agi_talent_radar.core.database import get_session, save_candidate
        from agi_talent_radar.core.db.orm import CandidateORM
        from agi_talent_radar.core.models import CandidateResume

        with get_session() as session:
            save_candidate(session, CandidateResume(id="guard_target2", name="吴语乐天", raw_text="原始内容"))
        source = make_resume_fixtures()[0].model_copy(update={"id": "guard_source2", "name": ""})
        try:
            events = self._post_jsonl_import(source, self._make_same_person_classification(source, "guard_target2"))
            candidate_event = next(e for e in events if e["type"] == "candidate")
            self.assertEqual(candidate_event["candidate"]["id"], "guard_source2")
            with get_session() as session:
                target = session.get(CandidateORM, "guard_target2")
                self.assertEqual(target.name, "吴语乐天")
                self.assertEqual(target.raw_text, "原始内容")
        finally:
            with get_session() as session:
                for cid in ("guard_target2", "guard_source2"):
                    row = session.get(CandidateORM, cid)
                    if row:
                        session.delete(row)
                session.commit()

    def test_new_person_with_reused_source_id_does_not_overwrite_existing_candidate(self) -> None:
        """不同人的简历文件同名时，必须分配新 ID，不能覆盖已有档案。"""
        from agi_talent_radar.core.database import get_session, save_candidate
        from agi_talent_radar.core.db.orm import CandidateORM
        from agi_talent_radar.core.models import CandidateResume, ImportClassification

        shared_id = "generic_resume_filename"
        with get_session() as session:
            save_candidate(session, CandidateResume(id=shared_id, name="旧候选人", raw_text="旧简历内容"))
        source = CandidateResume(id=shared_id, name="新候选人", raw_text="新简历内容")
        classification = ImportClassification(
            id=shared_id,
            name=source.name,
            category="工程闭环型",
            confidence=0.9,
            reason="不同人员",
            identity_decision="new_person",
            identity_confidence=0.9,
        )
        created_id = ""
        try:
            events = self._post_jsonl_import(source, classification)
            candidate_event = next(e for e in events if e["type"] == "candidate")
            created_id = candidate_event["candidate"]["id"]
            self.assertNotEqual(created_id, shared_id)
            with get_session() as session:
                existing = session.get(CandidateORM, shared_id)
                created = session.get(CandidateORM, created_id)
                self.assertEqual(existing.name, "旧候选人")
                self.assertEqual(existing.raw_text, "旧简历内容")
                self.assertEqual(created.name, "新候选人")
                self.assertEqual(created.raw_text, "新简历内容")
        finally:
            with get_session() as session:
                for candidate_id in (shared_id, created_id):
                    row = session.get(CandidateORM, candidate_id) if candidate_id else None
                    if row:
                        session.delete(row)
                session.commit()

    @patch("agi_talent_radar.web.workbench.run_import_agent_stream")
    def test_upload_jsonl_sse_stream(self, mock_stream) -> None:
        source = make_resume_fixtures()[0]
        classification = MagicMock()
        classification.id = source.id
        classification.name = source.name
        classification.category = "研究探索型"
        classification.level = "A"
        classification.confidence = 0.92
        classification.reason = "方向契合度高"
        mock_stream.return_value = iter([classification])
        content = (source.model_dump_json() + "\n").encode("utf-8")
        response = self.app.post(
            "/api/import-file",
            data={"file": (io.BytesIO(content), "resumes.jsonl")},
            content_type="multipart/form-data",
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/event-stream", response.content_type)
        events = self._parse_sse(response)
        self.assertEqual(
            [event["type"] for event in events],
            ["stage", "stage", "stage", "stage", "stage", "candidate", "done"],
        )
        candidate_event = events[5]
        self.assertEqual(candidate_event["candidate"]["id"], source.id)
        self.assertIn("education", candidate_event["candidate"])
        self.assertIn("directions", candidate_event["candidate"])
        self.assertIn("experiences", candidate_event["candidate"])
        self.assertIn("projects", candidate_event["candidate"])
        self.assertIn("publications", candidate_event["candidate"])
        self.assertIn("skills", candidate_event["candidate"])
        self.assertIn("screening_tags", candidate_event["candidate"])
        self.assertIn("source_format", candidate_event["candidate"])
        self.assertIn("document_analysis", candidate_event["candidate"])
        self.assertEqual(candidate_event["index"], 1)
        self.assertEqual(candidate_event["total"], 1)

    @patch("agi_talent_radar.web.workbench.run_import_agent_stream")
    def test_batch_upload_isolates_file_failures(self, mock_stream) -> None:
        first, second = make_resume_fixtures()[:2]

        def classify(resumes, persist, identity_candidates=None):
            self.assertFalse(persist)
            self.assertIsInstance(identity_candidates, list)
            results = []
            for resume in resumes:
                classification = MagicMock()
                classification.id = resume.id
                classification.name = resume.name
                classification.category = "研究探索型"
                classification.level = "A"
                classification.confidence = 0.9
                classification.reason = "方向契合"
                results.append(classification)
            return iter(results)

        mock_stream.side_effect = classify
        response = self.app.post(
            "/api/import-file",
            data={
                "files": [
                    (io.BytesIO((first.model_dump_json() + "\n").encode("utf-8")), "first.jsonl"),
                    (io.BytesIO((second.model_dump_json() + "\n").encode("utf-8")), "second.jsonl"),
                    (io.BytesIO(b"unsupported"), "invalid.exe"),
                ]
            },
            content_type="multipart/form-data",
        )

        self.assertEqual(response.status_code, 200)
        events = self._parse_sse(response)
        candidates = [event for event in events if event["type"] == "candidate"]
        errors = [event for event in events if event["type"] == "error"]
        done = events[-1]
        self.assertEqual({event["file_id"] for event in candidates}, {"file-1", "file-2"})
        self.assertEqual(errors[0]["file_id"], "file-3")
        self.assertEqual(errors[0]["stage"], "validation")
        self.assertEqual(done["type"], "done")
        self.assertEqual(done["imported_files"], 2)
        self.assertEqual(done["failed_files"], 1)
        self.assertEqual(done["total"], 2)

    @patch("agi_talent_radar.web.workbench._stream_import_upload")
    def test_batch_upload_runs_at_most_five_files_in_parallel(self, mock_import) -> None:
        barrier = threading.Barrier(5)
        lock = threading.Lock()
        active = 0
        max_active = 0

        def fake_import(file_id, filename, file_bytes, suffix, file_index, file_total):
            nonlocal active, max_active
            with lock:
                active += 1
                max_active = max(max_active, active)
            if file_index <= 5:
                barrier.wait(timeout=2)
            yield {
                "type": "stage",
                "file_id": file_id,
                "file_name": filename,
                "file_index": file_index,
                "file_total": file_total,
                "stage": "classification",
                "status": "done",
                "message": "完成",
            }
            with lock:
                active -= 1

        mock_import.side_effect = fake_import
        response = self.app.post(
            "/api/import-file",
            data={
                "files": [
                    (io.BytesIO(f"resume-{index}".encode()), f"resume-{index}.txt")
                    for index in range(7)
                ]
            },
            content_type="multipart/form-data",
        )

        events = self._parse_sse(response)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(max_active, 5)
        self.assertEqual(events[-1]["imported_files"], 7)
        self.assertEqual(events[-1]["failed_files"], 0)

    @patch("agi_talent_radar.web.workbench.run_import_agent_stream")
    @patch("agi_talent_radar.web.workbench.text_resume")
    @patch("agi_talent_radar.web.workbench.extract_pdf_text")
    def test_upload_pdf_reports_real_import_stages(self, mock_extract, mock_text_resume, mock_stream) -> None:
        from agi_talent_radar.core.models import CandidateResume

        mock_extract.return_value = ("[第 1 页]\nPDF 候选人 简历文本", [])
        mock_text_resume.return_value = CandidateResume(
            id="pdf_candidate",
            name="PDF 候选人",
            source_format="pdf",
            raw_text="[第 1 页]\nPDF 候选人 简历文本",
        )
        classification = MagicMock()
        classification.id = "pdf_candidate"
        classification.name = "PDF 候选人"
        classification.category = "多模态型"
        classification.level = "A"
        classification.confidence = 0.9
        classification.reason = "方向匹配"
        mock_stream.return_value = iter([classification])

        response = self.app.post(
            "/api/import-file",
            data={"file": (io.BytesIO(b"%PDF fake"), "candidate.pdf")},
            content_type="multipart/form-data",
        )
        events = self._parse_sse(response)
        stages = [(event.get("stage"), event.get("status")) for event in events if event["type"] == "stage"]
        self.assertEqual(
            stages,
            [
                ("validation", "done"),
                ("extracting", "running"),
                ("extracting", "done"),
                ("structuring", "running"),
                ("structuring", "done"),
                ("classification", "running"),
                ("classification", "done"),
            ],
        )
        candidate = next(event["candidate"] for event in events if event["type"] == "candidate")
        self.assertEqual(candidate["source_format"], "pdf")
        mock_text_resume.assert_called_once_with("[第 1 页]\nPDF 候选人 简历文本", "candidate.pdf", ocr_pages=[])

    @patch("agi_talent_radar.services.talent_service.admit_candidate_after_evaluation")
    @patch("agi_talent_radar.web.workbench.run_candidate_stream")
    @patch("agi_talent_radar.core.database.record_node_event")
    @patch("agi_talent_radar.core.database.start_evaluation_run")
    @patch("agi_talent_radar.core.database.save_evaluation")
    @patch("agi_talent_radar.core.database.get_candidate_with_latest_evaluation")
    @patch("agi_talent_radar.core.database.get_session")
    def test_evaluate_candidate(
        self,
        mock_session,
        mock_get,
        mock_save,
        mock_start,
        mock_record,
        mock_run_stream,
        mock_admit,
    ) -> None:
        mock_session.return_value.__enter__.return_value = MagicMock()
        mock_start.return_value.id = 101
        mock_row = MagicMock()
        mock_row.id = "candidate_01"
        mock_row.name = "候选人01"
        mock_row.target_role = "大模型研究员"
        mock_row.stage = "博士一年级"
        mock_row.raw_text = ""
        mock_row.education = "[]"
        mock_row.directions = "[]"
        mock_row.projects = "[]"
        mock_row.publications = "[]"
        mock_row.skills = "[]"
        mock_row.screening_tags = "[]"
        mock_get.return_value = (mock_row, None)

        from agi_talent_radar.core.models import CandidateEvaluation

        evaluation = CandidateEvaluation(
            id="candidate_01",
            name="候选人01",
            target_role="大模型研究员",
            stage="博士一年级",
            overall_score=75,
            level="A",
            tier="强烈建议沟通",
            decision_method="75 分按系统规则进入备选库。",
            one_liner="高潜候选人",
            core_strengths=[],
            potential_risks=[],
            interview_questions=[],
            cultivation_direction=[],
            dimension_scores=[],
            evidence=[],
        )
        mock_run_stream.return_value = iter([
            {"type": "node", "node": "normalizer", "label": "标准化", "status": "done", "message": "标准化完成"},
            {"type": "result", "result": evaluation.model_dump()},
        ])

        response = self.app.post("/api/candidates/candidate_01/evaluate")
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/event-stream", response.content_type)
        events = self._parse_sse(response)
        self.assertEqual(events[0]["type"], "started")
        self.assertEqual(events[0]["evaluation_id"], 101)
        self.assertEqual(events[1]["type"], "node")
        self.assertEqual(events[-1]["type"], "result")
        self.assertEqual(events[-1]["result"]["overall_score"], 75)
        mock_save.assert_called_once()
        mock_record.assert_called_once()
        # 评估成功统一走 talent_service.admit_candidate_after_evaluation。
        mock_admit.assert_called_once_with(101)

    def test_evaluation_continues_after_sse_disconnect(self) -> None:
        from agi_talent_radar.core.models import CandidateEvaluation

        worker_started = threading.Event()
        release_worker = threading.Event()
        evaluation_saved = threading.Event()
        row = MagicMock()
        row.id = "candidate_detached"
        row.name = "后台评估候选人"
        row.target_role = "研究员"
        row.stage = "博士候选人"
        row.raw_text = ""
        row.education = "[]"
        row.directions = "[]"
        row.experiences = "[]"
        row.projects = "[]"
        row.publications = "[]"
        row.skills = "[]"
        row.screening_tags = "[]"
        row.source_format = "text"
        row.document_analysis = "{}"
        row.academic_check_status = "done"
        row.academic_report = {"alignments": []}
        evaluation = CandidateEvaluation(
            id=row.id,
            name=row.name,
            target_role=row.target_role,
            stage=row.stage,
            overall_score=80,
            level="A",
            tier="建议沟通",
            decision_method="规则评分",
            one_liner="后台任务测试",
            core_strengths=[],
            potential_risks=[],
            interview_questions=[],
            cultivation_direction=[],
            dimension_scores=[],
            evidence=[],
        )

        def delayed_stream(*_args, **_kwargs):
            worker_started.set()
            release_worker.wait(2)
            yield {"type": "result", "result": evaluation.model_dump()}

        with (
            patch("agi_talent_radar.core.database.get_session") as mock_session,
            patch("agi_talent_radar.core.database.get_candidate_with_latest_evaluation", return_value=(row, None)),
            patch("agi_talent_radar.core.database.get_latest_evaluation_run", return_value=None),
            patch("agi_talent_radar.core.database.start_evaluation_run") as mock_start,
            patch("agi_talent_radar.core.database.save_evaluation", side_effect=lambda *_a, **_kw: evaluation_saved.set()),
            patch("agi_talent_radar.web.workbench.run_candidate_stream", side_effect=delayed_stream),
            patch("agi_talent_radar.services.talent_service.admit_candidate_after_evaluation"),
        ):
            mock_session.return_value.__enter__.return_value = MagicMock()
            mock_start.return_value.id = 104
            response = self.app.post("/api/candidates/candidate_detached/evaluate", buffered=False)
            first_event = json.loads(next(response.response).decode("utf-8").strip()[6:])
            self.assertEqual(first_event["type"], "started")
            self.assertTrue(worker_started.wait(1))

            response.close()
            release_worker.set()
            self.assertTrue(evaluation_saved.wait(2), "浏览器断开后后台评估应继续保存结果")

    @patch("agi_talent_radar.web.workbench.run_candidate_stream")
    @patch("agi_talent_radar.core.database.start_evaluation_run")
    @patch("agi_talent_radar.core.database.get_candidate_with_latest_evaluation")
    @patch("agi_talent_radar.core.database.get_session")
    def test_evaluate_candidate_injects_publication_mismatch(
        self,
        mock_session,
        mock_get,
        mock_start,
        mock_run_stream,
    ) -> None:
        report = {
            "alignments": [
                {
                    "claim": {"title": "Paper A"},
                    "verdict": "mismatch",
                    "discrepancies": ["作者顺序不一致"],
                }
            ],
            "warnings": [],
        }
        mock_session.return_value.__enter__.return_value = MagicMock()
        mock_start.return_value.id = 103
        mock_row = MagicMock()
        mock_row.id = "candidate_mismatch"
        mock_row.name = "候选人"
        mock_row.target_role = "研究员"
        mock_row.stage = "博士候选人"
        mock_row.raw_text = "Paper A"
        mock_row.education = "[]"
        mock_row.directions = "[]"
        mock_row.experiences = "[]"
        mock_row.projects = "[]"
        mock_row.publications = '["Paper A"]'
        mock_row.skills = "[]"
        mock_row.screening_tags = "[]"
        mock_row.source_format = "text"
        mock_row.document_analysis = "{}"
        mock_row.academic_check_status = "done"
        mock_row.academic_report = report
        mock_get.return_value = (mock_row, None)
        mock_run_stream.return_value = iter([])

        response = self.app.post("/api/candidates/candidate_mismatch/evaluate")
        self.assertEqual(response.status_code, 200)
        response.get_data()

        _, kwargs = mock_run_stream.call_args
        self.assertEqual(kwargs["academic_report"], report)

    @patch("agi_talent_radar.core.db.runtime.get_session")
    def test_review_unverifiable_publication_unlocks_evaluation(self, mock_session) -> None:
        session = mock_session.return_value.__enter__.return_value
        for action, expected_result in (("confirmed", "verified"), ("dismissed", "rejected")):
            with self.subTest(action=action):
                candidate = MagicMock()
                candidate.id = "candidate_review"
                candidate.academic_check_status = "done"
                candidate.academic_report = {
                    "alignments": [
                        {
                            "claim": {"title": "Paper A"},
                            "verdict": "unverifiable",
                            "note": "公开数据库未检索到",
                        }
                    ],
                    "warnings": [],
                }
                session.get.return_value = candidate
                session.commit.reset_mock()

                response = self.app.post(
                    "/api/candidates/candidate_review/publications/0/review",
                    json={
                        "action": action,
                        "reviewer": "HR",
                        "note": "已核对原文与作者主页",
                    },
                )

                self.assertEqual(response.status_code, 200)
                data = response.get_json()
                self.assertEqual(data["verification_result"], expected_result)
                self.assertTrue(data["evaluable"])
                self.assertEqual(candidate.academic_report["alignments"][0]["human_status"], action)
                session.commit.assert_called_once()

    def test_person_payload_uses_linked_candidate_and_dominant_evaluated_track(self) -> None:
        from agi_talent_radar.web.workbench import _person_to_brief, _person_to_detail

        evaluation = SimpleNamespace(
            id=8,
            status="completed",
            overall_score=80,
            level="",
            track_assignments=[
                SimpleNamespace(track="agent", weight=0.3529),
                SimpleNamespace(track="safety", weight=0.6471),
            ],
        )
        person = SimpleNamespace(
            id="person-1",
            name="候选人",
            org="某大学",
            direction="移动端侧智能体安全",
            person_type="student",
            group_id=None,
            created_at=None,
            updated_at=None,
            evaluations=[evaluation],
            reputation_reports=[],
        )
        candidate = SimpleNamespace(
            id="candidate-1",
            engagement_status="contacted",
            sources=[SimpleNamespace(source_kind="resume_evaluation")],
        )

        brief = _person_to_brief(person, candidate)
        detail_person = SimpleNamespace(**{**person.__dict__, "evaluations": []})
        detail = _person_to_detail(detail_person, candidate)

        self.assertEqual(brief["candidate_id"], "candidate-1")
        self.assertEqual(brief["engagement_status"], "contacted")
        self.assertEqual(brief["dominant_track"], "safety")
        self.assertAlmostEqual(brief["dominant_track_weight"], 0.6471)
        self.assertEqual(detail["candidate_id"], "candidate-1")
        self.assertEqual(detail["source_kinds"], ["resume_evaluation"])

    @patch("agi_talent_radar.services.talent_service.admit_candidate_after_evaluation")
    @patch("agi_talent_radar.web.workbench.run_candidate_stream")
    @patch("agi_talent_radar.core.database.start_evaluation_run")
    @patch("agi_talent_radar.core.database.save_evaluation")
    @patch("agi_talent_radar.core.database.get_candidate_with_latest_evaluation")
    @patch("agi_talent_radar.core.database.get_session")
    def test_evaluate_candidate_group_thresholds(
        self,
        mock_session,
        mock_get,
        mock_save,
        mock_start,
        mock_run_stream,
        mock_admit,
    ) -> None:
        mock_session.return_value.__enter__.return_value = MagicMock()
        mock_start.return_value.id = 102
        mock_row = MagicMock()
        mock_row.id = "candidate_01"
        mock_row.name = "候选人01"
        mock_row.target_role = "大模型研究员"
        mock_row.stage = "博士一年级"
        mock_row.raw_text = ""
        mock_row.education = "[]"
        mock_row.directions = "[]"
        mock_row.projects = "[]"
        mock_row.publications = "[]"
        mock_row.skills = "[]"
        mock_row.screening_tags = "[]"
        mock_get.return_value = (mock_row, None)

        from agi_talent_radar.core.models import CandidateEvaluation

        for score in (85, 75, 55):
            mock_admit.reset_mock()
            evaluation = CandidateEvaluation(
                id="candidate_01",
                name="候选人01",
                target_role="大模型研究员",
                stage="博士一年级",
                overall_score=score,
                level="A" if score >= 80 else "B" if score >= 60 else "C",
                tier="强烈建议沟通" if score >= 80 else "建议沟通" if score >= 60 else "暂缓 / 需补充信息",
                decision_method=f"{score} 分按系统规则进入测试库。",
                one_liner="高潜候选人",
                core_strengths=[],
                potential_risks=[],
                interview_questions=[],
                cultivation_direction=[],
                dimension_scores=[],
                evidence=[],
            )
            mock_run_stream.return_value = iter([{"type": "result", "result": evaluation.model_dump()}])

            response = self.app.post("/api/candidates/candidate_01/evaluate")
            self.assertEqual(response.status_code, 200)
            self._parse_sse(response)
            # 全部走 talent_service.admit_candidate_after_evaluation。
            mock_admit.assert_called_once_with(102)


class VerificationGateTest(unittest.TestCase):
    """门禁修复回归：有论文但报告缺失（核验失败）不应判 verified。"""

    def _row(self, status="done", report=None, publications=None):
        return SimpleNamespace(
            academic_check_status=status,
            academic_report=json.dumps(report) if report is not None else "",
            publications=json.dumps(publications) if publications is not None else "",
        )

    def test_empty_report_with_pubs_is_needs_review(self) -> None:
        """核验状态仍按 needs_review 标记,但不再阻断评估。"""
        from agi_talent_radar.web.workbench import _verification_result, _is_evaluable

        row = self._row(status="done", report={}, publications=["Paper A", "Paper B"])
        self.assertEqual(_verification_result(row), "needs_review")
        self.assertTrue(_is_evaluable(row))

    def test_empty_report_no_pubs_is_verified(self) -> None:
        """真无论文 → verified 可评估"""
        from agi_talent_radar.web.workbench import _verification_result, _is_evaluable

        row = self._row(status="done", report={}, publications=[])
        self.assertEqual(_verification_result(row), "verified")
        self.assertTrue(_is_evaluable(row))

    def test_unverifiable_unreviewed_blocks_evaluation(self) -> None:
        """未裁决的 unverifiable 仍标记 needs_review,但不再阻断评估"""
        from agi_talent_radar.web.workbench import _verification_result, _is_evaluable

        row = self._row(
            report={"alignments": [{"verdict": "unverifiable", "human_status": "unreviewed"}]},
            publications=["Paper A"],
        )
        self.assertEqual(_verification_result(row), "needs_review")
        self.assertTrue(_is_evaluable(row))

    def test_unverifiable_confirmed_releases_gate(self) -> None:
        """已裁决（confirmed）的 unverifiable → verified 放行"""
        from agi_talent_radar.web.workbench import _verification_result, _is_evaluable

        row = self._row(
            report={"alignments": [{"verdict": "unverifiable", "human_status": "confirmed"}]},
            publications=["Paper A"],
        )
        self.assertEqual(_verification_result(row), "verified")
        self.assertTrue(_is_evaluable(row))

    def test_mismatch_unreviewed_still_evaluable(self) -> None:
        """mismatch 不强制人工平反，可评估（rejected 状态可进入评估）"""
        from agi_talent_radar.web.workbench import _verification_result, _is_evaluable

        row = self._row(
            report={"alignments": [{"verdict": "mismatch", "human_status": "unreviewed"}]},
            publications=["Paper A"],
        )
        self.assertEqual(_verification_result(row), "rejected")
        self.assertTrue(_is_evaluable(row))

    def test_mixed_mismatch_and_unverifiable_blocks_on_unverifiable(self) -> None:
        """mismatch + 未裁决 unverifiable 共存时,核验状态取 needs_review,但不再阻断评估。

        核验状态优先级:unverifiable 未裁决仍标记 needs_review,比 mismatch 强。
        顺序不能反——否则 mismatch 短路让 unverifiable 不被检查。
        评估门禁已解除:needs_review 也可评估,核验冲突只进风险提示。
        """
        from agi_talent_radar.web.workbench import _verification_result, _is_evaluable

        row = self._row(
            report={"alignments": [
                {"verdict": "mismatch", "human_status": "unreviewed"},
                {"verdict": "verified", "human_status": "unreviewed"},
                {"verdict": "unverifiable", "human_status": "unreviewed"},
            ]},
            publications=["Paper A", "Paper B", "Paper C"],
        )
        self.assertEqual(_verification_result(row), "needs_review")
        self.assertTrue(_is_evaluable(row))


if __name__ == "__main__":
    unittest.main()
