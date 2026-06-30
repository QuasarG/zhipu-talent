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
只允许根据 evidence 列表打分，不允许使用 evidence 之外的信息编造理由。

等级规则：
- S: 90-100
- A: 80-89
- B: 70-79
- C: 0-69

分层规则：
- 强烈建议沟通：80 分及以上，且证据具体
- 建议沟通：74-79 分
- 暂缓 / 需补充信息：73 分及以下，或关键证据薄弱

dimension_scores 每项必须包含：
key, label, score(1-5), weighted_score, rationale, evidence_ids, risk_notes。
rationale 必须引用 evidence id，不要写空泛评价。
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
