from __future__ import annotations

import json
import threading
import unittest
from unittest.mock import patch

from agi_talent_radar.agents.interview_admission.contracts import AssessmentCard, TaskAssessment
from agi_talent_radar.agents.interview_admission.evaluator import (
    CHAIR_REVIEW_PROMPT,
    calculate_total_score,
    decide_admission,
    evaluate_candidate_for_job,
)
from agi_talent_radar.core.models import CandidateResume

LLM = "agi_talent_radar.core.llm_client"
CHAIR_SYSTEM_PREFIX = "你是面试准入评估的主 agent"

TASK_TITLES = {
    "agent_system": "Agent 系统研发",
    "evaluation_loop": "评测与数据闭环",
    "research_transfer": "研究成果迁移",
}


def _score_response(task_id: str, level: int, quote: str) -> dict:
    return {
        "task_id": task_id,
        "level": level,
        "confidence": "high",
        "reasoning_summary": "项目内容与当前核心任务直接对应。",
        "transfer_boundary": "具体边界需通过面试验证。",
        "evidence": [{
            "quote": quote,
            "evidence_type": "direct",
            "confidence": "high",
            "relevance": "直接体现该任务的实际工作与成果。",
        }],
        "risks": [],
    }


def _quote_for(task_id: str) -> str:
    return {
        "agent_system": "构建 Coding Agent benchmark",
        "evaluation_loop": "大规模评测平台",
        "research_transfer": "发表 WWW、ACL、CVPR、IJCAI",
    }[task_id]


def _assessment(task_id: str, level: int, quote: str) -> TaskAssessment:
    return TaskAssessment.model_validate(_score_response(task_id, level, quote))


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
        self.assertEqual(decision, "no_interview")

        assessments[0] = _assessment("agent_system", 1, "Coding Agent benchmark")
        decision, reason = decide_admission(
            self.card,
            assessments,
            calculate_total_score(self.card, assessments),
        )
        self.assertEqual(decision, "no_interview")
        self.assertIn("首要任务", reason)

    def test_full_workflow_repairs_via_continuation_and_keeps_audit(self) -> None:
        """坏引用 → 主席续命同一个子 agent（上下文保留、轮数重置）修正；过程段齐全。"""
        state = {"evaluation_loop_final": 0, "mission_rounds": 0, "final_calls": 0}
        continuation_seen = []

        def llm_tools(messages, tools, **kwargs):
            last = [m for m in messages if m["role"] == "user"][-1]["content"]
            if not tools:
                # 任务评分 JSON 通道：按合同里的 task_id 路由
                state["final_calls"] += 1
                for tid in TASK_TITLES:
                    if f'"task_id":"{tid}"' in last:
                        if tid == "evaluation_loop":
                            state["evaluation_loop_final"] += 1
                            if state["evaluation_loop_final"] == 1:
                                bad = _score_response(tid, 2, "模型凭空生成的评测结果")
                                return {"text": json.dumps(bad, ensure_ascii=False)}
                            good = _score_response(tid, 2, "大规模评测平台")
                            return {"text": json.dumps(good, ensure_ascii=False)}
                        return {"text": json.dumps(_score_response(tid, 3, _quote_for(tid)), ensure_ascii=False)}
                return {"text": json.dumps({"summary": "证据充分。"}, ensure_ascii=False)}
            # 子 agent 工作轮：narration（无工具调用，循环即止）
            state["mission_rounds"] += 1
            if "续命指令" in last:
                continuation_seen.append(last)
                return {"text": "已剔除坏引用并复核，结论不变。", "tool_calls": []}
            return {"text": "先核对简历中对应项目的原文。", "tool_calls": []}

        review = {
            "corrections": [{
                "task_id": "agent_system",
                "original_level": 3,
                "revised_level": 3,
                "reason": "等级与锚点一致",
                "evidence": ["负责 verifier 与 20 万条训练数据闭环"],
            }],
            "interview_focus": [{"task_id": "evaluation_loop", "focus": "验证评测失败案例"}],
            "summary": "证据充分，重点验证评测方法。",
        }
        with patch(f"{LLM}.call_llm_tools", side_effect=llm_tools), \
             patch(f"{LLM}.call_llm_json", return_value=review):
            result = evaluate_candidate_for_job(self.resume, "jd-agent", self.card)

        self.assertEqual(result.decision, "interview")
        self.assertTrue(result.review_corrections)

        spawns = [s for s in result.run_trace if s["type"] == "spawn"]
        self.assertEqual(sorted(s["spawn_id"] for s in spawns),
                         sorted(f"task_score:{t.id}" for t in self.card.core_tasks))
        self.assertTrue(all(s["status"] == "done" for s in spawns))

        evaluation_loop = next(s for s in spawns if s["spawn_id"] == "task_score:evaluation_loop")
        self.assertEqual(state["evaluation_loop_final"], 2)  # 第一次坏引用 → 续命后修正
        children_keys = [c.get("_key") for c in evaluation_loop["children"]]
        self.assertIn("prompt", children_types(children_keys))  # spawn prompt 展示
        self.assertIn("report", children_types(children_keys))
        self.assertIn("prompt:1", children_types(children_keys))  # 续命指令
        self.assertTrue(any("续命指令" in c.get("text", "")
                            for c in evaluation_loop["children"] if c["type"] == "text"))
        # 主流程叙述存在（主 agent 文本段）
        self.assertTrue(any(s["type"] == "text" and "总审" in s["text"] for s in result.run_trace))

    def test_missing_evidence_fields_are_normalized_without_retry(self) -> None:
        """GLM 偶发漏字段：宽容归一吸收，不打断 run、不触发重试。"""
        json_calls: dict[str, int] = {}
        mission_calls: dict[str, int] = {}
        lock = threading.Lock()

        def llm_tools(messages, tools, **kwargs):
            last = [m for m in messages if m["role"] == "user"][-1]["content"]
            if not tools:
                for tid in TASK_TITLES:
                    if f'"task_id":"{tid}"' in last:
                        with lock:
                            json_calls[tid] = json_calls.get(tid, 0) + 1
                        if tid == "evaluation_loop":
                            malformed = {
                                "task_id": tid, "level": 2, "confidence": "medium",
                                "reasoning_summary": "大规模评测平台对应评测闭环任务。",
                                "evidence": [{"quote": _quote_for(tid)}],
                            }
                            return {"text": json.dumps(malformed, ensure_ascii=False)}
                        return {"text": json.dumps(_score_response(tid, 3, _quote_for(tid)), ensure_ascii=False)}
            for tid in TASK_TITLES:
                if "评估核心任务" in last and TASK_TITLES[tid] in last:
                    with lock:
                        mission_calls[tid] = mission_calls.get(tid, 0) + 1
                    return {"text": "先核对简历中对应项目的原文。", "tool_calls": []}
            raise AssertionError("unexpected tools call")

        review = {"corrections": [], "interview_focus": [], "summary": "总审无异议"}
        with patch(f"{LLM}.call_llm_tools", side_effect=llm_tools), \
             patch(f"{LLM}.call_llm_json", return_value=review):
            result = evaluate_candidate_for_job(self.resume, "jd-agent", self.card)

        self.assertEqual(mission_calls.get("evaluation_loop"), 1)  # 无重试
        target = next(a for a in result.task_assessments if a.task_id == "evaluation_loop")
        self.assertEqual(len(target.evidence), 1)
        self.assertEqual(target.evidence[0].evidence_type, "background")
        self.assertEqual(target.evidence[0].confidence, "low")
        self.assertEqual(target.evidence[0].relevance, "未说明支撑关系")
        self.assertEqual(result.decision, "interview")

    def test_persistently_empty_scoring_fails_after_retries(self) -> None:
        """模型持续返回空内容：重试穷尽后按技术故障落失败态，而不是静默评 0 分。"""
        json_calls: dict[str, int] = {}
        lock = threading.Lock()

        def llm_tools(messages, tools, **kwargs):
            last = [m for m in messages if m["role"] == "user"][-1]["content"]
            if not tools:
                for tid in TASK_TITLES:
                    if f'"task_id":"{tid}"' in last:
                        with lock:
                            json_calls[tid] = json_calls.get(tid, 0) + 1
                        if tid == "evaluation_loop":
                            return {"text": ""}
                        return {"text": json.dumps(_score_response(tid, 2, _quote_for(tid)), ensure_ascii=False)}
            for tid in TASK_TITLES:
                if "评估核心任务" in last and TASK_TITLES[tid] in last:
                    return {"text": "先核对简历原文。", "tool_calls": []}
            return {"text": "继续。", "tool_calls": []}

        review = {"corrections": [], "interview_focus": [], "summary": "总审无异议"}
        with self.assertRaises(RuntimeError) as ctx, \
             patch(f"{LLM}.call_llm_tools", side_effect=llm_tools), \
             patch(f"{LLM}.call_llm_json", return_value=review):
            evaluate_candidate_for_job(self.resume, "jd-agent", self.card)

        self.assertIn("evaluation_loop", str(ctx.exception))
        # 空响应重试穷尽：至少一次 JSON 通道调用后按技术故障落失败态
        self.assertGreaterEqual(json_calls.get("evaluation_loop", 0), 1)

    def test_publications_and_projects_are_capability_evidence_without_skill_keyword(self) -> None:
        def llm_tools(messages, tools, **kwargs):
            serialized = str(messages)
            self.assertNotIn("仲奕杰", serialized)
            last = [m for m in messages if m["role"] == "user"][-1]["content"]
            if not tools:
                for tid in TASK_TITLES:
                    if f'"task_id":"{tid}"' in last:
                        levels = {"agent_system": 3, "evaluation_loop": 3, "research_transfer": 4}
                        return {"text": json.dumps(_score_response(tid, levels[tid], _quote_for(tid)), ensure_ascii=False)}
            for tid in TASK_TITLES:
                if "评估核心任务" in last and TASK_TITLES[tid] in last:
                    return {"text": "先核对简历中对应项目的原文。", "tool_calls": []}
            return {"text": "继续。", "tool_calls": []}

        review = {"corrections": [], "interview_focus": [], "summary": "能力证据完整"}
        with patch(f"{LLM}.call_llm_tools", side_effect=llm_tools), \
             patch(f"{LLM}.call_llm_json", return_value=review):
            result = evaluate_candidate_for_job(self.resume, "jd-agent", self.card)

        self.assertEqual(result.decision, "interview")
        self.assertGreaterEqual(result.total_score, 75)
        self.assertNotIn("PyTorch", result.model_dump_json())
        self.assertNotIn("unknown", result.model_dump_json())


def children_types(keys: list) -> list:
    return keys


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
        "evidence": [{
            "quote": quote,
            "evidence_type": "direct",
            "confidence": "high",
            "relevance": "直接体现该任务的实际工作与成果。",
        }],
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
