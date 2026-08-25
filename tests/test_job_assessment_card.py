from __future__ import annotations

import unittest

from agi_talent_radar.agents.interview_admission.job_card import (
    CARD_GENERATION_PROMPT,
    CARD_REVIEW_PROMPT,
    generate_assessment_card,
)


class JobAssessmentCardTests(unittest.TestCase):
    def test_card_is_revised_once_from_quality_feedback(self) -> None:
        calls: list[tuple[str, dict]] = []
        review_count = 0

        def llm(prompt: str, payload: dict) -> dict:
            nonlocal review_count
            calls.append((prompt, payload))
            if prompt == CARD_REVIEW_PROMPT:
                review_count += 1
                if review_count == 1:
                    return {
                        "passed": False,
                        "issues": ["任务一和任务二重复"],
                        "revision_instructions": ["合并重复任务并补足工程任务"],
                    }
                return {"passed": True, "issues": [], "revision_instructions": []}
            return _card("revised" if "quality_issues" in payload else "initial")

        events: list[dict] = []
        card = generate_assessment_card(
            "Agent 研发",
            "模型团队",
            "负责 Agent 训练、评测和工程落地，要求硕士，可长期实习一年。",
            ["重点关注复杂工具调用"],
            llm=llm,
            on_event=events.append,
        )

        self.assertEqual(card.role_summary, "revised 岗位核心使命")
        self.assertEqual(len(calls), 4)
        revision_payload = calls[2][1]
        self.assertEqual(revision_payload["quality_issues"], ["任务一和任务二重复"])
        self.assertEqual(events[-1]["status"], "completed")

    def test_prompt_defines_background_and_availability_boundaries(self) -> None:
        self.assertIn("学历和专业只能作为背景证据", CARD_GENERATION_PROMPT)
        self.assertIn("实习时长", CARD_GENERATION_PROMPT)
        self.assertIn("未写某工具不等于不会", CARD_GENERATION_PROMPT)


def _card(prefix: str) -> dict:
    return {
        "role_summary": f"{prefix} 岗位核心使命",
        "core_tasks": [
            _task("agent_design", "Agent 方案设计", "primary"),
            _task("agent_evaluation", "Agent 评测闭环", "major"),
            _task("engineering_delivery", "工程交付", "supporting"),
        ],
        "background_evidence_guidance": "学历与研究方向只辅助理解知识迁移基础。",
        "excluded_requirements": ["长期实习一年"],
    }


def _task(task_id: str, title: str, importance: str) -> dict:
    return {
        "id": task_id,
        "title": title,
        "description": f"围绕{title}完成方案、实现、验证与交付闭环。",
        "importance": importance,
        "evaluation_focus": "根据真实项目中的问题难度、本人贡献、技术判断和最终结果评价。",
        "anchors": {
            "level_2": "实际参与任务并独立完成清晰的局部工作。",
            "level_3": "能够独立完成核心任务并解决关键问题。",
            "level_4": "在复杂约束下成熟交付并形成可复用成果。",
        },
    }


if __name__ == "__main__":
    unittest.main()
