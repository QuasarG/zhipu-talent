from __future__ import annotations

from pydantic import BaseModel, Field

from agi_talent_radar.core import llm_client
from agi_talent_radar.core.models import CandidateEvaluation, DimensionScore, EvidenceItem, NormalizedResume


class FormatterOutput(BaseModel):
    one_liner: str
    core_strengths: list[str] = Field(default_factory=list)
    potential_risks: list[str] = Field(default_factory=list)
    interview_questions: list[str] = Field(default_factory=list)
    cultivation_direction: list[str] = Field(default_factory=list)

    @classmethod
    def model_validate(cls, obj, **kwargs):
        if isinstance(obj, dict):
            obj = dict(obj)
            obj["core_strengths"] = _stringify_items(obj.get("core_strengths", []))
            obj["potential_risks"] = _stringify_items(obj.get("potential_risks", []))
            obj["interview_questions"] = _stringify_items(obj.get("interview_questions", []))
            obj["cultivation_direction"] = _stringify_items(obj.get("cultivation_direction", []))
        return super().model_validate(obj, **kwargs)


FORMATTER_PROMPT = """
你是 AI 人才潜力初评系统里的【结构化组装与面谈生成器】。
只输出 JSON 对象，字段必须是：
one_liner, core_strengths, potential_risks, interview_questions, cultivation_direction。

输入包含：
- resume_brief：候选人基本信息
- evidence：已提取的结构化证据（含 dimension, quote, signals, strength）
- dimension_scores：12 个维度的得分和 rationale
- score_summary：overall_score, level, tier
- critic_flags：Critic 复核发现的问题

输出要求：
1. one_liner：一句话人才画像，必须点出最突出的 1-2 个维度 + 代表性证据。
2. core_strengths：3-5 条核心优势，每条必须绑定具体 evidence id 或原文 quote，不写空话。
3. potential_risks：4-6 条风险与待验证点，必须包括：
   - 论文/项目是否拟投、未发表
   - 指标真实性（baseline、评测集、消融设计）
   - 本人贡献边界（团队成果 vs 个人贡献）
   - 方向匹配度或能力短板
   - Critic 指出的问题
4. interview_questions：3-5 个尖锐追问，优先追问：baseline 设计、ablation、本人贡献、失败案例、数据/评测闭环、指标真实性。
5. cultivation_direction：2-4 条具体培养建议，对应候选人最适合参与的小闭环项目或培养路径。

语言风格：给 HR / 技术面试官使用，具体、可追问、不奉承。
""".strip()


def run_formatter(state: dict) -> dict:
    normalized = NormalizedResume.model_validate(state["normalized"])
    evidence = [EvidenceItem.model_validate(item) for item in state.get("evidence", [])]
    scores = [DimensionScore.model_validate(item) for item in state.get("scores", [])]
    ai_assessment = state.get("ai_assessment", {})
    response = llm_client.call_llm_json(
        FORMATTER_PROMPT,
        {
            "resume_brief": normalized.model_dump(exclude={"raw_text"}),
            "evidence": [item.model_dump() for item in evidence],
            "dimension_scores": [item.model_dump() for item in scores],
            "score_summary": ai_assessment,
            "critic_flags": state.get("critic_flags", []),
        },
        temperature=0.2,
    )
    formatted = FormatterOutput.model_validate(response)
    level = _normalize_level(ai_assessment.get("level", "C"), ai_assessment.get("overall_score", 0))
    tier = _normalize_tier(ai_assessment.get("tier", "暂缓 / 需补充信息"))
    evaluation = CandidateEvaluation(
        id=normalized.id,
        name=normalized.name,
        target_role=normalized.target_role,
        stage=normalized.stage,
        overall_score=int(ai_assessment["overall_score"]),
        level=level,
        tier=tier,
        one_liner=formatted.one_liner,
        core_strengths=formatted.core_strengths,
        potential_risks=formatted.potential_risks,
        interview_questions=formatted.interview_questions,
        cultivation_direction=formatted.cultivation_direction,
        dimension_scores=scores,
        evidence=evidence,
        critic_flags=state.get("critic_flags", []),
        normalized_education=normalized.education_blind,
        screening_tags=normalized.screening_tags,
    )
    return {**state, "final_output": evaluation.model_dump()}


def _normalize_level(value: str, overall_score: int = 0) -> str:
    text = str(value).strip()
    if "强烈" in text:
        return "A" if overall_score < 90 else "S"
    if "建议沟通" in text and "暂缓" not in text:
        return "B"
    if "暂缓" in text:
        return "C"
    mapping = {"s": "S", "a": "A", "b": "B", "c": "C"}
    normalized = mapping.get(text.lower(), text.upper())
    if normalized in {"S", "A", "B", "C"}:
        return normalized
    if overall_score >= 90:
        return "S"
    if overall_score >= 80:
        return "A"
    if overall_score >= 70:
        return "B"
    return "C"


def _normalize_tier(value: str) -> str:
    mapping = {
        "强烈建议沟通": "强烈建议沟通",
        "建议沟通": "建议沟通",
        "暂缓/需补充信息": "暂缓 / 需补充信息",
        "暂缓 / 需补充信息": "暂缓 / 需补充信息",
        "暂缓": "暂缓 / 需补充信息",
    }
    return mapping.get(str(value).strip(), "暂缓 / 需补充信息")


def _stringify_items(value):
    if isinstance(value, str):
        return [value] if value.strip() else []
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for item in value:
        if isinstance(item, str):
            if item.strip():
                result.append(item)
        elif isinstance(item, dict):
            text = item.get("text") or item.get("description") or item.get("strength") or item.get("direction") or " ".join(str(v) for v in item.values() if isinstance(v, str))
            if text.strip():
                result.append(text.strip())
        else:
            text = str(item).strip()
            if text:
                result.append(text)
    return result
