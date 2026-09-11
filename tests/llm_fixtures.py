from __future__ import annotations

import json
import re
from contextlib import contextmanager
from typing import Any
from unittest.mock import patch

from agi_talent_radar.core.rubric import RUBRIC


@contextmanager
def mock_llm_json():
    """全链路 Fake：对话/结构化/导入等走 prompt 分支；评审团链路走脚本化 Fake。"""
    panel = _PanelScripted()
    with (
        patch("agi_talent_radar.core.llm_client.call_llm_json", side_effect=panel.llm_json),
        patch("agi_talent_radar.core.llm_client.call_llm_stream", side_effect=_fake_llm_stream),
        patch("agi_talent_radar.core.llm_client.call_llm_tools", side_effect=panel.llm_tools),
    ):
        yield


class _PanelScripted:
    """评审团脚本：主席首轮按 JD 派 jd_match + 一个 deep_read，次轮收队；
    评审员零工具轮直接交 4 分 findings（jd_match 引文取自当前简历，保证反查存活）。"""

    def __init__(self) -> None:
        self.resume: dict[str, Any] = {}
        self.jobs: list[dict[str, Any]] = []

    # ---- 主席（call_llm_json；其余 prompt 交给通用 _fake_llm_json）----
    def llm_json(self, system_prompt: str, payload: dict[str, Any], temperature: float = 0.1, **_kw: Any) -> dict[str, Any]:
        if "评审团的主席" not in system_prompt:
            return _fake_llm_json(system_prompt, payload, temperature, **_kw)
        self.resume = payload.get("resume") or {}
        self.jobs = payload.get("jobs") or []
        if payload.get("missions_done"):
            return {"action": "synthesize", "per_jd": [
                {"jd_id": j["jd_id"], "confidence": 0.85,
                 "strengths": [], "risks": [],
                 "interview_questions": [f"请展开 {j['jd_id']} 核心项目的本人贡献。"],
                 "missing_information": [], "assessment_summary": "证据达到面试验证门槛"}
                for j in self.jobs
            ]}
        missions = [
            {"mission_id": f"jm_{j['jd_id']}", "type": "jd_match",
             "goal": f"对照 {j['jd_id']} 判硬门槛", "jd_id": j["jd_id"]}
            for j in self.jobs
        ]
        missions.append({"mission_id": "dr_core", "type": "deep_read", "goal": "深读项目材料",
                         "dimensions": ["technical_depth", "ownership", "engineering_scale"]})
        return {"action": "dispatch", "missions": missions}

    # ---- 评审员（call_llm_tools；tools 非空=工具轮，tools==[]=findings 通道）----
    def llm_tools(self, messages: list, tools: list, **_kw: Any) -> dict[str, Any]:
        if tools:
            return {"text": "", "tool_calls": []}
        system = str(messages[0]["content"])
        quote = self._quote()
        if "岗位对照评审员" in system:
            jd_id = self._jd_from_system(system)
            return {"text": json.dumps({"assessments": [{
                "jd_id": jd_id,
                "hard_requirements": [
                    {"requirement": f"{jd_id} 核心任务经验", "status": "met",
                     "evidence": [quote], "rationale": "简历明确写出对应项目事实"},
                ],
                "dimensions": [
                    {"key": "direct_task_match", "score": 4,
                     "rationale": "简历项目覆盖岗位核心任务的要求充分", "evidence": [quote]},
                    {"key": "transferability", "score": 4,
                     "rationale": "相邻经历可迁移到岗位核心任务的完成", "evidence": [quote]},
                ],
            }]}, ensure_ascii=False), "tool_calls": []}
        if "深读评审员" in system:
            jd_ids = re.findall(r"jd_id=(\S+?)｜", system) or [j["jd_id"] for j in self.jobs]
            return {"text": json.dumps({"assessments": [
                {"jd_id": jd_id, "dimensions": [
                    {"key": key, "score": 4,
                     "rationale": "材料显示方法细节与本人贡献充分", "evidence": [quote]}
                    for key in ("technical_depth", "ownership", "engineering_scale")
                ]}
                for jd_id in jd_ids
            ]}, ensure_ascii=False), "tool_calls": []}
        raise AssertionError(f"未覆盖的评审员工种: {system[:80]}")

    def _jd_from_system(self, system: str) -> str:
        match = re.search(r"# 目标 JD：(\S+?)｜", system)
        if match:
            return match.group(1)
        return self.jobs[0]["jd_id"] if self.jobs else "jd"

    def _quote(self) -> str:
        projects = self.resume.get("projects") or []
        details = (projects[0].get("details") if projects else None) or []
        return details[0] if details else str(self.resume.get("raw_text") or "简历未提供项目细节")[:40]


def _fake_llm_stream(system_prompt: str, payload: dict[str, Any], temperature: float = 0.1):
    """模拟 LLM 流式输出，将原本一次性返回的 JSON 拆成多行 JSON Lines 推送。"""
    if "简历一次流式结构化 Agent" in system_prompt:
        lines = [line.strip() for line in payload.get("raw_text", "").splitlines() if line.strip()]
        first_line = lines[0] if lines else "候选人"
        events = [
            {
                "section": "basic",
                "fields": {
                    "name": "候选人",
                    "target_role": "AI 研究员",
                    "stage": "博士在读",
                    "directions": [],
                    "screening_tags": [],
                },
            },
            {"section": "education", "fields": {"education": []}},
            {"section": "experiences", "fields": {"experiences": []}},
            {
                "section": "projects",
                "fields": {"projects": [{"name": first_line[:40], "details": ["从文本解析的项目摘要"]}]},
            },
            {"section": "publications", "fields": {"publications": []}},
            {"section": "skills", "fields": {"skills": []}},
        ]
        for event in events:
            yield json.dumps(event, ensure_ascii=False) + "\n"
        return
    response = _fake_llm_json(system_prompt, payload, temperature)
    if "人才库批量导入 Agent" in system_prompt:
        for candidate in response.get("candidates", []):
            yield json.dumps(candidate, ensure_ascii=False) + "\n"
        return
    # 其他 agent 仍一次性返回完整 JSON（当前只有导入需要流式）
    yield json.dumps(response, ensure_ascii=False)


def _fake_llm_json(
    system_prompt: str,
    payload: dict[str, Any],
    temperature: float = 0.1,
    **_kwargs: Any,
) -> dict[str, Any]:
    if "简历解析 Agent" in system_prompt:
        # 从 raw_text 中简单提取第一段作为 name/title 的 fallback
        lines = [line.strip() for line in payload.get("raw_text", "").splitlines() if line.strip()]
        first_line = lines[0] if lines else "候选人"
        return {
            "name": "候选人",
            "target_role": "AI 研究员",
            "stage": "博士在读",
            "education": [],
            "directions": [],
            "projects": [{"name": first_line[:40], "details": ["从文本解析的项目摘要"]}],
            "publications": [],
            "skills": [],
            "screening_tags": [],
        }
    if "人才库批量导入 Agent" in system_prompt:
        return {
            "candidates": [
                {
                    "id": item["id"],
                    "name": item["name"],
                    "target_role": item.get("target_role", ""),
                    "stage": item.get("stage", ""),
                    "category": _category(item),
                    "level": _level(item),
                    "confidence": 0.82,
                    "reason": "根据目标方向、项目名称和技能关键词进行初步分类。",
                }
                for item in payload["candidates"]
            ]
        }
    if "背景信号标准化 Agent" in system_prompt:
        rule_guess = payload["rule_guess"]
        return {
            "background_signal_tiers": {
                **rule_guess,
                "rationale": "教育背景已折叠为分级信号，仅作低权重参考。",
            },
            "education_notes": [
                "学校层级、成绩与排名已折叠为背景档位。",
                "后续评分应优先依据项目证据。",
            ],
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
                    "signals": _signals_for_quote(quote),
                    "strength": 4,
                    "has_metric": _has_metric(quote),
                    "has_specific_tool": _has_specific_tool(quote),
                    "has_ownership": "负责" in quote or "设计" in quote or "提出" in quote,
                    "track_hints": [],
                    "page": None,
                    "bbox": [],
                    "extraction_confidence": 1.0,
                }
                for index, (dimension, source, quote) in enumerate(quotes, start=1)
            ]
        }
    if "多 Track 路由 Agent" in system_prompt:
        evidence_ids = [item["id"] for item in payload.get("evidence", [])]
        resume_text = " ".join(
            [
                payload.get("resume", {}).get("target_role", ""),
                " ".join(payload.get("resume", {}).get("directions", [])),
                " ".join(payload.get("resume", {}).get("skills", [])),
            ]
        ).lower()
        if "agent" in resume_text or "智能体" in resume_text:
            assignments = [("agent", 0.7), ("ai_infra", 0.3)]
        elif "多模态" in resume_text or "视觉" in resume_text or "3d" in resume_text:
            assignments = [("multimodal", 0.7), ("base", 0.3)]
        elif "安全" in resume_text:
            assignments = [("safety", 0.8), ("base", 0.2)]
        elif "生物" in resume_text or "science" in resume_text:
            assignments = [("ai4science", 0.7), ("multimodal", 0.3)]
        else:
            assignments = [("base", 0.65), ("ai_infra", 0.35)]
        return {
            "assignments": [
                {
                    "track": track,
                    "weight": weight,
                    "confidence": 0.86,
                    "rationale": "根据项目工作分布和研究方向进行路由。",
                    "evidence_ids": evidence_ids,
                }
                for track, weight in assignments
            ]
        }
    if "通用潜力评分 Agent" in system_prompt:
        evidence = payload.get("evidence", [])
        evidence_ids = [item["id"] for item in evidence] or ["e001"]
        return {
            "dimension_scores": [
                {
                    "key": item["key"],
                    "label": item["label"],
                    "score": 3.5,
                    "rationale": f"{evidence_ids[0]} 支撑该通用潜力判断。",
                    "evidence_ids": evidence_ids[:2],
                    "risk_notes": ["需面谈确认贡献边界。"],
                }
                for item in payload["rubric"]
            ]
        }
    if "专业评估 Agent" in system_prompt:
        evidence = payload.get("evidence", [])
        evidence_ids = [item["id"] for item in evidence] or ["e001"]
        return {
            "dimension_scores": [
                {
                    "key": item["key"],
                    "label": item["label"],
                    "score": 3.5,
                    "rationale": f"{evidence_ids[0]} 支撑该 Track 专业判断。",
                    "evidence_ids": evidence_ids[:2],
                    "risk_notes": ["需补充该 Track 的复现实验。"],
                }
                for item in payload["track"]["dimensions"]
            ]
        }
    if "跨领域对齐打分 Agent" in system_prompt:
        evidence = payload["evidence"]
        evidence_by_dimension = {item["dimension"]: item["id"] for item in evidence}
        return {
            "overall_score": 82,
            "level": "A",
            "tier": "强烈建议沟通",
            "dimension_scores": [
                {
                    "key": item.key,
                    "label": item.label,
                    "score": _fixture_score(item.key),
                    "weighted_score": round(_fixture_score(item.key) * item.weight * 20, 2),
                    "rationale": f"{evidence_by_dimension.get(item.key, evidence[0]['id'])} 支撑该维度判断。",
                    "evidence_ids": [evidence_by_dimension.get(item.key, evidence[0]["id"])],
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


def _level(item: dict[str, Any]) -> str:
    text = " ".join(
        [
            item.get("target_role", ""),
            " ".join(item.get("directions", [])),
            " ".join(item.get("screening_tags", [])),
        ]
    ).lower()
    if "agent" in text or "系统" in text:
        return "A"
    return "B"


def _quotes_from_resume(resume: dict[str, Any]) -> list[tuple[str, str, str]]:
    projects = resume.get("projects", [])
    first_project = projects[0] if projects else {"name": "项目", "details": [resume["target_role"]]}
    first_detail = first_project.get("details", [first_project.get("name", "")])[0]
    second_project = projects[1] if len(projects) > 1 else first_project
    second_detail = second_project.get("details", [second_project.get("name", "")])[0]
    third_project = projects[2] if len(projects) > 2 else first_project
    third_detail = third_project.get("details", [third_project.get("name", "")])[-1]
    skill_quote = "、".join(resume.get("skills", []))
    return [
        ("problem_definition", f"项目：{first_project.get('name', '')}", first_detail),
        ("engineering_practice", "技能关键词", skill_quote),
        ("ai_agent_leverage", f"项目：{second_project.get('name', '')}", second_detail),
        ("ownership", f"项目：{third_project.get('name', '')}", third_detail),
        ("research_exploration", f"项目：{first_project.get('name', '')}", first_detail),
        ("cultivation_value", f"项目：{third_project.get('name', '')}", third_detail),
    ]


def _fixture_score(key: str) -> float:
    return {
        "learning_growth": 3.2,
        "research_exploration": 4.1,
        "engineering_practice": 4.2,
        "ai_agent_leverage": 4.1,
        "problem_definition": 4.1,
        "ownership": 4.2,
        "cultivation_value": 4.0,
        "education_signal": 3.2,
        "academic_output": 3.4,
        "project_richness": 3.5,
        "impact_visibility": 3.0,
        "direction_fit": 3.4,
    }.get(key, 3.0)


def _signals_for_quote(quote: str) -> list[str]:
    signals: list[str] = []
    if _has_specific_tool(quote):
        signals.append("技术栈:PyTorch")
    if any(word in quote for word in ["负责", "设计", "提出", "构建", "维护"]):
        signals.append("动作:负责")
    if _has_metric(quote):
        signals.append("量化结果")
    if any(word in quote.lower() for word in ["agent", "智能体", "workflow", "工作流", "rag", "路由"]):
        signals.append("AI杠杆:Agent")
    if any(word in quote for word in ["验证", "评测", "复现", "闭环", "修复", "错误归因"]):
        signals.append("验证闭环")
    return signals or ["项目事实"]


def _has_metric(quote: str) -> bool:
    return any(marker in quote for marker in ["%", "倍", "300+", "提升", "降低", "减少", "覆盖"])


def _has_specific_tool(quote: str) -> bool:
    return any(tool.lower() in quote.lower() for tool in ["pytorch", "triton", "docker", "playwright", "sympy", "rag", "agent", "ray"])
