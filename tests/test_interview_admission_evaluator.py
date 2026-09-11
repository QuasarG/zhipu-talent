from __future__ import annotations

import threading
import unittest

from agi_talent_radar.agents.interview_admission.contracts import AssessmentCard, TaskAssessment
from agi_talent_radar.agents.interview_admission.evaluator import (
    CHAIR_REVIEW_PROMPT,
    calculate_total_score,
    decide_admission,
    evaluate_candidate_for_job,
)
from agi_talent_radar.core.models import CandidateResume

SCORER_SYSTEM_PREFIX = "你是面试准入评估的任务评估 agent"
CHAIR_SYSTEM_PREFIX = "你是面试准入评估的主 agent"


class InterviewAdmissionEvaluatorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.card = AssessmentCard.model_validate(_card())
        self.resume = CandidateResume(
            id="candidate-1",
            name="仲奕杰",
            raw_text=(
                "仲奕杰，同济大学人工智能博士、南京大学计算机硕士。"
                "构建 Coding Agent benchmark，负责 verifier 与 20 万条训练数据闭环。"
                "发表 WWW、ACL、CVPR、IJCAI 等 18 篇论文，其中 10 篇一作。"
                "完成 RAG 长期记忆系统和大规模评测平台。"
            ),
        )

    def test_weighted_score_and_primary_gate_are_deterministic(self) -> None:
        assessments = [
            _assessment("agent_system", 3, "构建 Coding Agent benchmark"),
            _assessment("evaluation_loop", 2, "大规模评测平台"),
            _assessment("research_transfer", 1, "发表 WWW、ACL、CVPR、IJCAI"),
        ]
        total = calculate_total_score(self.card, assessments)
        decision, _ = decide_admission(self.card, assessments, total)

        self.assertEqual(total, 58.3)
        # 准入线 50→60：58.3 分不再直接进入面试
        self.assertEqual(decision, "no_interview")

        assessments[0] = _assessment("agent_system", 1, "Coding Agent benchmark")
        decision, reason = decide_admission(
            self.card,
            assessments,
            calculate_total_score(self.card, assessments),
        )
        self.assertEqual(decision, "no_interview")
        self.assertIn("首要任务", reason)

    def test_full_workflow_repairs_only_bad_task_and_keeps_audit(self) -> None:
        score_calls: dict[str, int] = {}
        lock = threading.Lock()

        def llm(prompt: str, payload: dict) -> dict:
            if prompt.startswith(SCORER_SYSTEM_PREFIX):
                task_id = payload["current_task"]["id"]
                with lock:
                    score_calls[task_id] = score_calls.get(task_id, 0) + 1
                    count = score_calls[task_id]
                quote = _quote_for(task_id)
                if task_id == "evaluation_loop" and count == 1:
                    quote = "模型凭空生成的评测结果"
                return _score_response(task_id, 2, quote)
            if prompt.startswith(CHAIR_SYSTEM_PREFIX):
                return {
                    "corrections": [
                        {
                            "task_id": "agent_system",
                            "original_level": 2,
                            "revised_level": 3,
                            "reason": "verifier 与数据闭环已经体现独立交付",
                            "evidence": ["负责 verifier 与 20 万条训练数据闭环"],
                        }
                    ],
                    "interview_focus": [
                        {"task_id": "evaluation_loop", "focus": "验证评测失败案例与指标选择"}
                    ],
                    "summary": "证据充分，重点验证评测方法。",
                }
            raise AssertionError("unexpected prompt")

        result = evaluate_candidate_for_job(self.resume, "jd-agent", self.card, llm=llm)

        self.assertEqual(score_calls["evaluation_loop"], 2)
        self.assertEqual(score_calls["agent_system"], 1)
        self.assertEqual(result.review_corrections[0].revised_level, 3)
        self.assertEqual(result.decision, "interview")
        self.assertNotIn("hold", result.model_dump_json())

        # trace = 聊天段：主席文本 + 每个任务一个 spawn 段（repair 归并进同一 spawn）
        spawns = [s for s in result.run_trace if s["type"] == "spawn"]
        self.assertEqual(sorted(s["spawn_id"] for s in spawns),
                         sorted(f"task_score:{t.id}" for t in self.card.core_tasks))
        self.assertTrue(all(s["status"] == "done" for s in spawns))
        self.assertTrue(any("证据修正" in (s.get("summary") or "") or s["status"] == "done" for s in spawns))
        self.assertTrue(any(s["type"] == "text" and "总审" in s["text"] for s in result.run_trace))
        evaluation_loop = spawns[1]
        self.assertIn("评定 2 级", evaluation_loop["summary"])

    def test_missing_evidence_fields_are_normalized_without_retry(self) -> None:
        """GLM 偶发漏字段：宽容归一吸收，不打断 run、不触发重试。"""
        score_calls: dict[str, int] = {}
        lock = threading.Lock()

        def llm(prompt: str, payload: dict) -> dict:
            if prompt.startswith(SCORER_SYSTEM_PREFIX):
                task_id = payload["current_task"]["id"]
                with lock:
                    score_calls[task_id] = score_calls.get(task_id, 0) + 1
                if task_id == "evaluation_loop":
                    # 只回了 quote，漏了 relevance/evidence_type/confidence
                    return {
                        "task_id": task_id,
                        "level": 2,
                        "confidence": "medium",
                        "reasoning_summary": "大规模评测平台对应评测闭环任务。",
                        "evidence": [{"quote": _quote_for(task_id)}],
                    }
                return _score_response(task_id, 3, _quote_for(task_id))
            return {"corrections": [], "interview_focus": [], "summary": "总审无异议"}

        result = evaluate_candidate_for_job(self.resume, "jd-agent", self.card, llm=llm)

        self.assertEqual(score_calls["evaluation_loop"], 1)
        target = next(a for a in result.task_assessments if a.task_id == "evaluation_loop")
        self.assertEqual(len(target.evidence), 1)
        self.assertEqual(target.evidence[0].evidence_type, "background")
        self.assertEqual(target.evidence[0].confidence, "low")
        self.assertEqual(target.evidence[0].relevance, "未说明支撑关系")
        self.assertEqual(result.decision, "interview")

    def test_persistently_empty_scoring_fails_after_retries(self) -> None:
        """模型持续返回空内容：重试穷尽后按技术故障落失败态，而不是静默评 0 分。"""
        score_calls: dict[str, int] = {}
        lock = threading.Lock()

        def llm(prompt: str, payload: dict) -> dict:
            if prompt.startswith(SCORER_SYSTEM_PREFIX):
                task_id = payload["current_task"]["id"]
                with lock:
                    score_calls[task_id] = score_calls.get(task_id, 0) + 1
                if task_id == "evaluation_loop":
                    return {}
                return _score_response(task_id, 2, _quote_for(task_id))
            return {"corrections": [], "interview_focus": [], "summary": "总审无异议"}

        with self.assertRaises(RuntimeError) as ctx:
            evaluate_candidate_for_job(self.resume, "jd-agent", self.card, llm=llm)

        self.assertIn("evaluation_loop", str(ctx.exception))
        self.assertEqual(score_calls["evaluation_loop"], 3)

    def test_publications_and_projects_are_capability_evidence_without_skill_keyword(self) -> None:
        def llm(prompt: str, payload: dict) -> dict:
            serialized = str(payload)
            self.assertNotIn("仲奕杰", serialized)
            if prompt.startswith(SCORER_SYSTEM_PREFIX):
                task_id = payload["current_task"]["id"]
                levels = {"agent_system": 3, "evaluation_loop": 3, "research_transfer": 4}
                return _score_response(task_id, levels[task_id], _quote_for(task_id))
            return {"corrections": [], "interview_focus": [], "summary": "能力证据完整"}

        result = evaluate_candidate_for_job(self.resume, "jd-agent", self.card, llm=llm)

        self.assertEqual(result.decision, "interview")
        self.assertGreaterEqual(result.total_score, 75)
        self.assertNotIn("PyTorch", result.model_dump_json())
        self.assertNotIn("unknown", result.model_dump_json())


def _card() -> dict:
    return {
        "role_summary": "建设可训练、可评测并能稳定交付的 Agent 系统。",
        "core_tasks": [
            _task("agent_system", "Agent 系统研发", "primary"),
            _task("evaluation_loop", "评测与数据闭环", "major"),
            _task("research_transfer", "研究成果迁移", "supporting"),
        ],
        "background_evidence_guidance": "学历和专业只用于理解理论基础。",
        "excluded_requirements": ["长期实习一年"],
    }


def _task(task_id: str, title: str, importance: str) -> dict:
    return {
        "id": task_id,
        "title": title,
        "description": f"独立完成{title}中的方案、实现、验证和交付。",
        "importance": importance,
        "evaluation_focus": "结合真实项目难度、技术判断、本人贡献和成果进行评价。",
        "anchors": {
            "level_2": "实际参与并完成边界清楚的局部工作。",
            "level_3": "独立完成核心任务并解决关键问题。",
            "level_4": "复杂约束下成熟交付并沉淀通用能力。",
        },
    }


def _assessment(task_id: str, level: int, quote: str) -> TaskAssessment:
    return TaskAssessment.model_validate(_score_response(task_id, level, quote))


def _score_response(task_id: str, level: int, quote: str) -> dict:
    return {
        "task_id": task_id,
        "level": level,
        "confidence": "high",
        "reasoning_summary": "项目内容与当前核心任务直接对应。",
        "transfer_boundary": "具体边界需通过面试验证。",
        "evidence": [
            {
                "quote": quote,
                "evidence_type": "direct",
                "confidence": "high",
                "relevance": "直接体现该任务的实际工作与成果。",
            }
        ],
        "risks": [],
    }


def _quote_for(task_id: str) -> str:
    return {
        "agent_system": "构建 Coding Agent benchmark",
        "evaluation_loop": "大规模评测平台",
        "research_transfer": "发表 WWW、ACL、CVPR、IJCAI",
    }[task_id]


if __name__ == "__main__":
    unittest.main()
