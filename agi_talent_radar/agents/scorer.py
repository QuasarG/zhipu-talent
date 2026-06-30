from __future__ import annotations

from pydantic import BaseModel, Field

from agi_talent_radar.core import llm_client
from agi_talent_radar.core.models import DimensionScore, EvidenceItem, NormalizedResume
from agi_talent_radar.core.rubric import RUBRIC


class ScoringOutput(BaseModel):
    overall_score: int = Field(ge=0, le=100)
    level: str
    tier: str
    dimension_scores: list[DimensionScore]

    @classmethod
    def model_validate(cls, obj, **kwargs):
        if isinstance(obj, dict):
            obj = dict(obj)
            obj["overall_score"] = int(round(float(obj.get("overall_score", 0))))
        return super().model_validate(obj, **kwargs)


SCORER_PROMPT = """
你是 AI 人才潜力初评系统里的【跨领域对齐打分 Agent】。
只输出 JSON 对象，字段必须是 overall_score, level, tier, dimension_scores。

评分目标：
识别长期培养价值，不是传统履历排序。不要直接按学校、GPA、论文名气给高分。

评分规则：
- 每个维度 score 为 1-5 分。
- weighted_score = score × weight × 20。
- overall_score = 所有维度 weighted_score 之和，四舍五入到整数。
- 潜力维度（learning_growth, research_exploration, engineering_practice, ai_agent_leverage, problem_definition, ownership, cultivation_value）是核心，必须基于具体 evidence 判断，不能只看背景。
- 履历维度（education_signal, academic_output, project_richness, impact_visibility, direction_fit）是辅助，低权重参考，不要给满分，除非有特别突出的外部证据。

1-5 分含义：
- 5：有明确、具体、可验证的强证据，且候选人展现了独立闭环能力。
- 4：有具体证据，但缺少部分闭环或本人贡献边界待确认。
- 3：有证据但偏泛化，或只有参与/了解类描述。
- 2：证据薄弱，只有背景信号或间接描述。
- 1：几乎无证据或明显不匹配。

等级规则：
- S: overall_score >= 90
- A: 80 <= overall_score <= 89
- B: 70 <= overall_score <= 79
- C: overall_score < 70

分层规则：
- 强烈建议沟通：overall_score >= 80 且核心潜力维度有具体证据
- 建议沟通：70 <= overall_score <= 79
- 暂缓 / 需补充信息：overall_score < 70，或关键潜力维度证据严重不足

dimension_scores 每项必须包含：
key, label, score(1-5), weighted_score, rationale, evidence_ids, risk_notes。
- rationale 必须引用 evidence id，解释为什么是这个分数。
- risk_notes 必须是字符串列表，指出该维度的待验证点；如果没有风险，给空列表 []。
- 不要给所有维度相同分数，要根据 evidence 区分强弱。
""".strip()


def run_scorer(state: dict) -> dict:
    normalized = NormalizedResume.model_validate(state["normalized"])
    evidence = [EvidenceItem.model_validate(item) for item in state.get("evidence", [])]
    response = llm_client.call_llm_json(
        SCORER_PROMPT,
        {
            "rubric": [item.model_dump() for item in RUBRIC],
            "resume_brief": normalized.model_dump(exclude={"raw_text"}),
            "evidence": [item.model_dump() for item in evidence],
            "critic_feedback": state.get("critic_flags", []),
            "rescore_instruction": "如果 critic_feedback 非空，请降低证据不足维度分数，并在 risk_notes 中解释。",
        },
        temperature=0.1,
    )
    _normalize_risk_notes(response.get("dimension_scores", []))
    scoring = ScoringOutput.model_validate(response)
    return {
        **state,
        "scores": [item.model_dump() for item in scoring.dimension_scores],
        "ai_assessment": {
            **state.get("ai_assessment", {}),
            "overall_score": scoring.overall_score,
            "level": scoring.level,
            "tier": scoring.tier,
        },
    }


def _normalize_risk_notes(scores: list[dict]) -> None:
    for item in scores:
        risk_notes = item.get("risk_notes", [])
        if isinstance(risk_notes, str):
            item["risk_notes"] = [risk_notes] if risk_notes.strip() else []
        elif not isinstance(risk_notes, list):
            item["risk_notes"] = []
