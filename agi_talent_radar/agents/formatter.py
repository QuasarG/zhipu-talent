from __future__ import annotations

from pydantic import BaseModel, Field

from agi_talent_radar.core import llm_client
from agi_talent_radar.core.stage_profile import profile_for_stage
from agi_talent_radar.core.models import (
    CandidateEvaluation,
    DimensionScore,
    DirectionRecommendation,
    EvidenceItem,
    NormalizedResume,
    TrackAssignment,
    TrackEvaluation,
)


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
你是 AI 人才潜力评估系统里的【多 Track 结构化组装与面谈生成器】。
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
- common_scores：跨 Track 通用潜力维度
- track_assignments：候选人的 Track 权重与路由证据
- track_evaluations：各 Track 专业得分、风险和维度
- score_summary：overall_score, common_score, track_score
- critic_flags：路由、通用评分、专业评分和全局 Critic 发现的问题

输出要求：
1. one_liner：一句话人才画像，必须点出主 Track、次 Track、最突出能力与代表性证据。
2. core_strengths：每条必须绑定具体 evidence id 或原文 quote，不写空话。
3. potential_risks：必须包括论文/项目状态、指标真实性、本人贡献边界、方向匹配度或能力短板、Critic 指出的问题。
4. interview_questions：至少覆盖主 Track 专业风险、次 Track 边界、本人贡献和验证闭环。
5. cultivation_direction：对应候选人的主 Track 培养方向，并说明跨 Track 发展可能性。
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
    common_scores = [DimensionScore.model_validate(item) for item in state.get("common_scores", [])]
    assignments = [TrackAssignment.model_validate(item) for item in state.get("track_assignments", [])]
    track_evaluations = [TrackEvaluation.model_validate(item) for item in state.get("track_results", [])]
    assessment = state.get("portfolio_assessment", {})
    critic_flags = list(state.get("global_critic_flags", []))
    response = llm_client.call_llm_json(
        FORMATTER_PROMPT,
        {
            "resume_brief": normalized.model_dump(exclude={"raw_text", "education_raw", "experiences_raw"}),
            "evidence": [item.model_dump() for item in evidence],
            "common_scores": [item.model_dump() for item in common_scores],
            "track_assignments": [item.model_dump() for item in assignments],
            "track_evaluations": [item.model_dump() for item in track_evaluations],
            "score_summary": assessment,
            "critic_flags": critic_flags,
        },
        temperature=0.2,
    )
    formatted = FormatterOutput.model_validate(response)
    stage_profile = profile_for_stage(normalized.stage)
    cultivation_direction = list(formatted.cultivation_direction)
    if stage_profile.evidence_expectation not in cultivation_direction:
        cultivation_direction.append(stage_profile.evidence_expectation)
    overall_score = int(assessment["overall_score"])
    recommendations = _recommend_tracks(track_evaluations, assignments)
    evaluation = CandidateEvaluation(
        id=normalized.id,
        name=normalized.name,
        target_role=normalized.target_role,
        stage=normalized.stage,
        overall_score=overall_score,
        one_liner=formatted.one_liner,
        core_strengths=formatted.core_strengths,
        potential_risks=formatted.potential_risks,
        interview_questions=formatted.interview_questions,
        cultivation_direction=cultivation_direction,
        dimension_scores=common_scores,
        evidence=evidence,
        critic_flags=critic_flags,
        normalized_education=normalized.education_blind,
        screening_tags=normalized.screening_tags,
        common_score=float(assessment.get("common_score", 0)),
        document_score=0.0,
        track_assignments=assignments,
        track_evaluations=track_evaluations,
        recommended_tracks=recommendations,
        stage_profile=stage_profile.label,
        academic_report=state.get("academic_report", {}),
        routing_confidence=float(state.get("routing_confidence", 0)),
    )
    return {**state, "final_output": evaluation.model_dump()}


def _recommend_tracks(
    evaluations: list[TrackEvaluation],
    assignments: list[TrackAssignment],
) -> list[DirectionRecommendation]:
    assignment_by_track = {item.track: item for item in assignments}
    ranked = sorted(
        evaluations,
        key=lambda item: (item.calibrated_score, item.confidence, item.weight),
        reverse=True,
    )
    recommendations: list[DirectionRecommendation] = []
    for item in ranked:
        assignment = assignment_by_track.get(item.track)
        evidence_ids = item.evidence_ids or (assignment.evidence_ids if assignment else [])
        recommendations.append(
            DirectionRecommendation(
                track=item.track,
                label=item.label,
                score=item.calibrated_score,
                weight=assignment.weight if assignment else item.weight,
                confidence=item.confidence,
                evidence_ids=evidence_ids,
                rationale=(
                    f"{item.label} 专业证据得分 {item.calibrated_score:.1f}/60；"
                    f"路由置信度 {item.confidence:.0%}。"
                ),
            )
        )
    return recommendations


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
