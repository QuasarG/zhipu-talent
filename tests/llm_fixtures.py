from __future__ import annotations

from contextlib import contextmanager
from typing import Any
from unittest.mock import patch

from agi_talent_radar.core.rubric import RUBRIC


@contextmanager
def mock_deepseek_json():
    with patch("agi_talent_radar.core.llm_client.call_llm_json", side_effect=_fake_llm_json):
        yield


def _fake_llm_json(system_prompt: str, payload: dict[str, Any], temperature: float = 0.1) -> dict[str, Any]:
    if "回顾确认 Agent" in system_prompt:
        return {
            "items": [
                {
                    "id": item["id"],
                    "name": item["name"],
                    "final_category": item["initial_category"],
                    "confidence": item["confidence"],
                    "review_notes": "分类与项目证据一致，保留候选人进入深评。",
                }
                for item in payload["initial_classifications"]
            ]
        }
    if "初评分类 Agent" in system_prompt:
        return {
            "items": [
                {
                    "id": item["id"],
                    "name": item["name"],
                    "initial_category": _category(item),
                    "confidence": 0.82,
                    "reason": "根据目标方向、项目名称和技能关键词进行初步分类。",
                }
                for item in payload["candidates"]
            ]
        }
    if "深度证据挖掘 Agent" in system_prompt:
        resume = payload["resume"]
        quotes = _quotes_from_resume(resume)
        return {
            "evidence": [
                {
                    "id": f"e{index:03d}",
                    "dimension": dimension,
                    "source": source,
                    "quote": quote,
                    "signals": ["动作:负责", "量化结果"] if index == 1 else ["技术栈:PyTorch"],
                    "strength": 4,
                    "has_metric": index == 1,
                    "has_specific_tool": index != 1,
                    "has_ownership": "负责" in quote or "设计" in quote or "提出" in quote,
                }
                for index, (dimension, source, quote) in enumerate(quotes, start=1)
            ]
        }
    if "跨领域对齐打分 Agent" in system_prompt:
        evidence = payload["evidence"]
        evidence_id = evidence[0]["id"]
        return {
            "overall_score": 82,
            "level": "A",
            "tier": "强烈建议沟通",
            "dimension_scores": [
                {
                    "key": item.key,
                    "label": item.label,
                    "score": 4.1,
                    "weighted_score": round(4.1 * item.weight * 20, 2),
                    "rationale": f"{evidence_id} 支撑该维度判断。",
                    "evidence_ids": [evidence_id],
                    "risk_notes": ["需面谈确认本人贡献。"],
                }
                for item in RUBRIC
            ],
        }
    if "逻辑判官与防幻觉节点" in system_prompt:
        return {"critic_flags": [], "needs_rescore": False}
    if "结构化组装与面谈生成器" in system_prompt:
        evidence = payload["evidence"]
        quote = evidence[0]["quote"]
        return {
            "one_liner": f"基于“{quote}”呈现出高潜力的 AI 候选人。",
            "core_strengths": [f"证据充分：{quote}"],
            "potential_risks": ["需要确认项目中本人贡献边界。"],
            "interview_questions": [f"请解释“{quote}”的 baseline、ablation 和失败案例。"],
            "cultivation_direction": ["进入短周期 AI 项目闭环验证。"],
        }
    raise AssertionError(f"未覆盖的 LLM prompt: {system_prompt[:80]}")


def _category(item: dict[str, Any]) -> str:
    text = " ".join(
        [
            item.get("target_role", ""),
            " ".join(item.get("directions", [])),
            " ".join(item.get("screening_tags", [])),
        ]
    ).lower()
    if "agent" in text:
        return "Agent / 工具杠杆型"
    if "系统" in text or "fp8" in text:
        return "工程闭环型"
    return "研究探索型"


def _quotes_from_resume(resume: dict[str, Any]) -> list[tuple[str, str, str]]:
    projects = resume.get("projects", [])
    first_project = projects[0] if projects else {"name": "项目", "details": [resume["target_role"]]}
    first_detail = first_project.get("details", [first_project.get("name", "")])[0]
    skill_quote = "、".join(resume.get("skills", []))
    return [
        ("problem_definition", f"项目：{first_project.get('name', '')}", first_detail),
        ("engineering_practice", "技能关键词", skill_quote),
        ("ownership", f"项目：{first_project.get('name', '')}", first_project.get("name", "")),
    ]
