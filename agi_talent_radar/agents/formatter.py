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
必须只输出一个合法 JSON 对象，不要 markdown 代码块，不要任何解释文字。

必填字段及类型：
- one_liner: string（一句话人才画像）
- core_strengths: list[string]（3-5 条核心优势）
- potential_risks: list[string]（4-6 条风险与待验证点）
- interview_questions: list[string]（3-5 个尖锐追问）
- cultivation_direction: list[string]（2-4 条培养建议）

输入包含：
- resume_brief：候选人基本信息
- evidence：已提取的结构化证据（含 dimension, quote, signals, strength）
- dimension_scores：12 个维度的得分和 rationale
- score_summary：overall_score, level, tier
- critic_flags：Critic 复核发现的问题

输出要求：
1. one_liner：一句话人才画像，必须点出最突出的 1-2 个维度 + 代表性证据。
2. core_strengths：每条必须绑定具体 evidence id 或原文 quote，不写空话。
3. potential_risks：必须包括论文/项目状态、指标真实性、本人贡献边界、方向匹配度或能力短板、Critic 指出的问题。
4. interview_questions：优先追问 baseline 设计、ablation、本人贡献、失败案例、数据/评测闭环、指标真实性。
5. cultivation_direction：对应候选人最适合参与的小闭环项目或培养路径。
6. 不输出具体学校名、GPA 数值或排名数值；如需提及教育背景，只能引用分级信号。

输出示例（严格遵循此结构，数组元素用中文）：
{
  "one_liner": "某博士候选人，在线性注意力与长上下文方向有扎实预训练证据，但项目真实性需验证。",
  "core_strengths": [
    "提出低秩衰减线性注意力机制，在4B参数模型上完成预训练消融（evidence_e001）。",
    "使用Triton实现分块并行扫描，128K上下文下显存降低约35%（evidence_e003）。"
  ],
  "potential_risks": [
    "论文《Efficient Decay Memory...》状态为'拟投NeurIPS 2026'，尚未接收。",
    "长上下文检索提升6.8%的baseline和评测集未说明，需验证指标真实性。",
    "4B模型实验是否为个人独立完成，还是团队成果，贡献边界需追问。"
  ],
  "interview_questions": [
    "请详细说明6.8%提升的baseline模型、评测数据集和主要消融实验设计。",
    "低秩衰减矩阵的灵感来源是什么？与现有线性注意力工作的核心差异在哪里？"
  ],
  "cultivation_direction": [
    "建议先参与现有大模型长上下文优化的小闭环项目，验证工程落地能力。",
    "若论文接收，可独立负责一条高效注意力方向的预训练实验线。"
  ]
}

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
            "resume_brief": normalized.model_dump(exclude={"raw_text", "education_raw"}),
            "evidence": [item.model_dump() for item in evidence],
            "dimension_scores": [item.model_dump() for item in scores],
            "score_summary": ai_assessment,
            "critic_flags": state.get("critic_flags", []),
        },
        temperature=0.2,
    )
    formatted = FormatterOutput.model_validate(response)
    overall_score = int(ai_assessment["overall_score"])
    level = _normalize_level(ai_assessment.get("level", "C"), overall_score)
    tier = _normalize_tier(ai_assessment.get("tier", "暂缓 / 需补充信息"), overall_score)
    evaluation = CandidateEvaluation(
        id=normalized.id,
        name=normalized.name,
        target_role=normalized.target_role,
        stage=normalized.stage,
        overall_score=overall_score,
        level=level,
        tier=tier,
        decision_method=_decision_method(overall_score, tier),
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


def _decision_method(overall_score: int, tier: str) -> str:
    if overall_score >= 80:
        pool = "优选库"
    elif overall_score >= 60:
        pool = "备选库"
    else:
        pool = "不建议后续沟通"
    return (
        f"{overall_score} 分按系统规则进入{pool}；"
        f"下一轮沟通建议为「{tier}」。评分优先依据项目证据、技术动作、量化结果和 ownership，"
        "学校/GPA/排名仅作为低权重分级背景信号。"
    )


def _normalize_level(value: str, overall_score: int = 0) -> str:
    if overall_score >= 90:
        return "S"
    if overall_score >= 80:
        return "A"
    if overall_score >= 60:
        return "B"
    return "C"


def _normalize_tier(value: str, overall_score: int = 0) -> str:
    if overall_score >= 80:
        return "强烈建议沟通"
    if overall_score >= 60:
        return "建议沟通"
    return "暂缓 / 需补充信息"


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
