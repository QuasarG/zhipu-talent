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


FORMATTER_PROMPT = """
你是 AI 人才潜力初评系统里的【结构化组装与面谈生成器】。
只输出 JSON 对象，字段必须是：
one_liner, core_strengths, potential_risks, interview_questions, cultivation_direction。

要求：
1. 输出给 HR / 技术面试官使用，语言要具体、可追问。
2. 每个优势必须绑定 evidence 中的原文证据，不写空话。
3. 风险要指出待验证点，尤其是论文拟投、贡献边界、指标真实性、项目复现难度。
4. 面谈问题要尖锐，优先追问 baseline、ablation、本人贡献、失败案例、数据/评测闭环。
5. 培养方向要对应候选人最适合参与的小闭环项目。
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
    evaluation = CandidateEvaluation(
        id=normalized.id,
        name=normalized.name,
        target_role=normalized.target_role,
        stage=normalized.stage,
        overall_score=int(ai_assessment["overall_score"]),
        level=ai_assessment["level"],
        tier=ai_assessment["tier"],
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
