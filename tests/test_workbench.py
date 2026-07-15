from __future__ import annotations

import io
import json
import threading
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from agi_talent_radar.web.workbench import create_app
from tests.resume_fixtures import make_resume_fixtures


ROOT = Path(__file__).resolve().parents[1]


class WorkbenchTest(unittest.TestCase):
    def setUp(self) -> None:
        self.app = create_app().test_client()

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
        response = self.app.get("/")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("AGI Talent Radar", html)
        self.assertIn("workbench-import.js", html)
        self.assertIn("workbench-publications.js", html)
        self.assertIn('id="import-file-input" type="file"', html)
        self.assertIn("multiple hidden", html)

    def test_publication_cards_mark_status_and_candidate_author(self) -> None:
        publication_script = (
            ROOT / "agi_talent_radar" / "web" / "static" / "workbench-publications.js"
        ).read_text(encoding="utf-8")
        workbench_script = (
            ROOT / "agi_talent_radar" / "web" / "static" / "workbench.js"
        ).read_text(encoding="utf-8")
        self.assertIn("inferCandidateKeys", publication_script)
        self.assertIn('label: "已发表"', publication_script)
        self.assertIn('label: "在投"', publication_script)
        self.assertIn("publication.positionLabel", workbench_script)
        self.assertIn("author.isCandidate", workbench_script)

    def test_resume_panel_renders_structured_work_experiences(self) -> None:
        script = (ROOT / "agi_talent_radar" / "web" / "static" / "workbench.js").read_text(encoding="utf-8")
        styles = (ROOT / "agi_talent_radar" / "web" / "static" / "workbench.css").read_text(encoding="utf-8")

        self.assertIn('section("实习 / 工作经历", experiencesBody', script)
        self.assertIn("experience.organization", script)
        self.assertIn("experience.role", script)
        self.assertIn("experience.details", script)
        self.assertIn(".resume-section-experiences", styles)
        self.assertIn(".experience-item", styles)

    def test_drawers_render_with_consistent_toggle_state(self) -> None:
        response = self.app.get("/")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn('aria-controls="list-pending"', html)
        self.assertIn('aria-controls="list-shortlisted"', html)
        self.assertIn('aria-controls="list-alternative"', html)
        self.assertIn('aria-controls="list-rejected"', html)
        self.assertIn('id="list-shortlisted" hidden', html)
        self.assertIn('id="list-alternative" hidden', html)
        self.assertIn('id="list-rejected" hidden', html)
        self.assertIn('id="bulk-evaluate-pending"', html)
        self.assertIn('id="bulk-confirm-dialog"', html)

    def test_evidence_is_rendered_as_inline_annotations(self) -> None:
        script = (ROOT / "agi_talent_radar" / "web" / "static" / "workbench.js").read_text(encoding="utf-8")
        self.assertIn("renderEvidenceText", script)
        self.assertIn("evidence-inline", script)
        self.assertNotIn("<h3>证据链</h3>", script)

    def test_candidate_switch_renders_before_detail_fetch(self) -> None:
        script = (ROOT / "agi_talent_radar" / "web" / "static" / "workbench.js").read_text(encoding="utf-8")
        start = script.index("async function selectCandidate")
        end = script.index("async function deleteCandidate")
        select_candidate = script[start:end]
        self.assertLess(select_candidate.index("renderResume(candidate);"), select_candidate.index("loadCandidateDetail(candidateId)"))
        self.assertLess(select_candidate.index("renderAgent(candidate);"), select_candidate.index("loadCandidateDetail(candidateId)"))
        self.assertIn("if (currentCandidateId !== candidateId) return;", select_candidate)

    def test_bulk_evaluation_uses_limited_concurrency_and_queue_state(self) -> None:
        script = (ROOT / "agi_talent_radar" / "web" / "static" / "workbench.js").read_text(encoding="utf-8")
        self.assertIn("const BULK_EVALUATION_CONCURRENCY = 3;", script)
        self.assertIn("function queueAgentRun", script)
        self.assertIn("等待批量调度", script)
        self.assertIn("async function runWithConcurrency", script)
        self.assertIn("runWithConcurrency(ids, BULK_EVALUATION_CONCURRENCY", script)
        self.assertNotIn("Promise.allSettled(\n    ids.map", script)

    def test_agent_panel_disallows_horizontal_scroll(self) -> None:
        styles = (ROOT / "agi_talent_radar" / "web" / "static" / "workbench.css").read_text(encoding="utf-8")
        self.assertIn(".agent-pane {\n  width: 420px;", styles)
        self.assertIn("overflow-x: hidden;", styles)
        self.assertIn(".agent-content {", styles)
        self.assertIn("word-break: break-word;", styles)
        self.assertIn("grid-template-columns: minmax(0, 130px) minmax(0, 1fr) 36px;", styles)

    def test_agent_node_panel_expands_without_internal_scroll(self) -> None:
        styles = (ROOT / "agi_talent_radar" / "web" / "static" / "workbench.css").read_text(encoding="utf-8")
        script = (ROOT / "agi_talent_radar" / "web" / "static" / "workbench.js").read_text(encoding="utf-8")
        self.assertIn(".node-feed {\n  max-height: none;\n  overflow-y: visible;", styles)
        self.assertNotIn("feed.scrollTop = feed.scrollHeight", script)

    def test_agent_graph_renders_multi_track_parallel_stages(self) -> None:
        graph_script = (
            ROOT / "agi_talent_radar" / "web" / "static" / "workbench-agent-graph.js"
        ).read_text(encoding="utf-8")
        html = self.app.get("/").get_data(as_text=True)
        self.assertLess(html.index("workbench-agent-graph.js"), html.index("workbench.js"))
        self.assertIn('key: "parallel"', graph_script)
        self.assertIn('"common_critic"', graph_script)
        self.assertIn('"base_track"', graph_script)
        self.assertIn('"agent_track"', graph_script)
        self.assertIn('"safety_track"', graph_script)
        self.assertIn('"multimodal_track"', graph_script)
        self.assertIn('"systems_track"', graph_script)
        self.assertIn('"ai4science_track"', graph_script)

    def test_candidates_group_returns_list(self) -> None:
        response = self.app.get("/api/candidates?group=pending")
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertIsInstance(data, list)

    def test_candidates_group_rejects_invalid_group(self) -> None:
        response = self.app.get("/api/candidates?group=invalid")
        self.assertEqual(response.status_code, 400)

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
        mock_eval.evaluation_mode = "deepseek_ai_only"
        mock_get.return_value = (mock_row, mock_eval)

        response = self.app.get("/api/candidates/candidate_01")
        self.assertEqual(response.status_code, 200)
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
            self.assertEqual(row.decision_method, "75 分按系统规则进入备选库。")

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
        self.assertEqual([event["type"] for event in events], ["stage", "stage", "candidate", "stage", "done"])
        candidate_event = events[2]
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

        def classify(resumes, persist):
            self.assertTrue(persist)
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

    def test_batch_import_frontend_renders_one_progress_line_per_resume(self) -> None:
        script = (ROOT / "agi_talent_radar" / "web" / "static" / "workbench.js").read_text(encoding="utf-8")
        progress_script = (
            ROOT / "agi_talent_radar" / "web" / "static" / "workbench-import.js"
        ).read_text(encoding="utf-8")

        self.assertIn('formData.append("files", file)', script)
        self.assertIn('class="import-file-row is-${item.status}"', script)
        self.assertIn('role="progressbar"', script)
        self.assertIn("state.items.find", progress_script)
        self.assertIn("failedFiles", progress_script)

    @patch("agi_talent_radar.web.workbench.run_import_agent_stream")
    @patch("agi_talent_radar.web.workbench.analyze_resume_pages")
    @patch("agi_talent_radar.web.workbench.render_pdf_pages")
    def test_upload_pdf_reports_real_import_stages(self, mock_render, mock_analyze, mock_stream) -> None:
        from agi_talent_radar.core.models import CandidateResume
        from agi_talent_radar.integrations.vision_mcp import VisionPage

        mock_render.return_value = [VisionPage(page_number=1, mime_type="image/png", data_base64="aW1hZ2U=")]
        mock_analyze.return_value = CandidateResume(
            id="pdf_candidate",
            name="PDF 候选人",
            source_format="pdf",
            document_analysis={"warnings": ["第 1 页局部模糊"]},
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
                ("rendering", "running"),
                ("rendering", "done"),
                ("vision", "running"),
                ("vision", "done"),
                ("classification", "running"),
                ("classification", "done"),
            ],
        )
        candidate = next(event["candidate"] for event in events if event["type"] == "candidate")
        self.assertEqual(candidate["source_format"], "pdf")
        self.assertEqual(candidate["document_analysis"]["warnings"], ["第 1 页局部模糊"])

    @patch("agi_talent_radar.web.workbench.run_candidate_stream")
    @patch("agi_talent_radar.core.database.record_node_event")
    @patch("agi_talent_radar.core.database.start_evaluation_run")
    @patch("agi_talent_radar.core.database.move_candidate_group")
    @patch("agi_talent_radar.core.database.save_evaluation")
    @patch("agi_talent_radar.core.database.get_candidate_with_latest_evaluation")
    @patch("agi_talent_radar.core.database.get_session")
    def test_evaluate_candidate(
        self,
        mock_session,
        mock_get,
        mock_save,
        mock_move,
        mock_start,
        mock_record,
        mock_run_stream,
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
        self.assertEqual(events[0]["type"], "node")
        self.assertEqual(events[-1]["type"], "result")
        self.assertEqual(events[-1]["result"]["overall_score"], 75)
        mock_save.assert_called_once()
        mock_record.assert_called_once()
        mock_move.assert_called_once_with(mock_session.return_value.__enter__.return_value, "candidate_01", "alternative")

    @patch("agi_talent_radar.web.workbench.run_candidate_stream")
    @patch("agi_talent_radar.core.database.start_evaluation_run")
    @patch("agi_talent_radar.core.database.move_candidate_group")
    @patch("agi_talent_radar.core.database.save_evaluation")
    @patch("agi_talent_radar.core.database.get_candidate_with_latest_evaluation")
    @patch("agi_talent_radar.core.database.get_session")
    def test_evaluate_candidate_group_thresholds(
        self,
        mock_session,
        mock_get,
        mock_save,
        mock_move,
        mock_start,
        mock_run_stream,
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

        for score, expected_group in [(85, "shortlisted"), (75, "alternative"), (55, "rejected")]:
            mock_move.reset_mock()
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
            mock_move.assert_called_once_with(mock_session.return_value.__enter__.return_value, "candidate_01", expected_group)

    @patch("agi_talent_radar.core.database.move_candidate_group")
    @patch("agi_talent_radar.core.database.get_candidate_with_latest_evaluation")
    def test_move_candidate(self, mock_get, mock_move) -> None:
        mock_row = MagicMock()
        mock_row.id = "candidate_01"
        mock_row.group = "rejected"
        mock_get.return_value = (mock_row, None)
        mock_move.return_value = mock_row

        response = self.app.post(
            "/api/candidates/candidate_01/move",
            json={"group": "rejected"},
        )
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data["group"], "rejected")


if __name__ == "__main__":
    unittest.main()
