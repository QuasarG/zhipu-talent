from __future__ import annotations

from typing import Any

from agi_talent_radar.agents.common_potential.rubric import COMMON_RUBRIC
from agi_talent_radar.core import llm_client
from agi_talent_radar.core.models import DimensionScore, EvidenceItem, NormalizedResume


COMMON_SCORER_PROMPT = """
你是 AI 人才潜力评估系统里的【通用潜力评分 Agent】。
只输出 JSON 对象，顶层字段必须是 dimension_scores。

这部分只评价跨 Track 都成立的元能力，不评价具体方向熟练度，也不奖励 Agent、工程落地、学校或论文名气。
每个维度 score 为 0-5：0 无证据；1 只有关键词；2 参与但贡献不清；3 有方法、动作和基本验证；
4 有独立问题定义与完整验证；5 形成可迁移方法论并有强验证和清晰 ownership。

每项必须输出 key, label, score, rationale, evidence_ids, risk_notes。
rationale 必须引用存在的 evidence id；没有证据时给 0 分。
同一维度在不同 Track 的表现形式可以不同，但判断标准必须基于候选人的实际动作与可验证证据。
""".strip()


def run_common_scorer(state: dict[str, Any]) -> dict[str, Any]:
    normalized = NormalizedResume.model_validate(state["normalized"])
    evidence = [EvidenceItem.model_validate(item) for item in state.get("evidence", [])]
    response = llm_client.call_llm_json(
        COMMON_SCORER_PROMPT,
        {
            "rubric": [
                {
                    "key": item.key,
                    "label": item.label,
                    "max_points": item.max_points,
                    "evidence_rule": item.evidence_rule,
                }
                for item in COMMON_RUBRIC
            ],
            "track_assignments": state.get("track_assignments", []),
            "resume_brief": normalized.model_dump(exclude={"raw_text", "education_raw"}),
            "evidence": [item.model_dump() for item in evidence],
        },
        temperature=0.1,
    )
    by_key = {str(item.get("key")): item for item in response.get("dimension_scores", [])}
    scores = []
    for dimension in COMMON_RUBRIC:
        raw = by_key.get(dimension.key, {})
        score = max(0.0, min(5.0, round(float(raw.get("score", 0)), 1)))
        scores.append(
            DimensionScore(
                key=dimension.key,
                label=dimension.label,
                score=score,
                max_points=dimension.max_points,
                weighted_score=round(score / 5 * dimension.max_points, 2),
                rationale=str(raw.get("rationale", "该维度未返回有效理由。")),
                evidence_ids=[str(item) for item in raw.get("evidence_ids", [])],
                risk_notes=_string_list(raw.get("risk_notes", [])),
            )
        )
    return {
        "common_scores": [item.model_dump() for item in scores],
        "common_score": round(sum(item.weighted_score for item in scores), 2),
    }


def run_common_critic(state: dict[str, Any]) -> dict[str, Any]:
    evidence = {item.id: item for item in [EvidenceItem.model_validate(raw) for raw in state.get("evidence", [])]}
    calibrated: list[DimensionScore] = []
    flags: list[str] = []

    for raw in state.get("common_scores", []):
        item = DimensionScore.model_validate(raw)
        refs = [evidence[evidence_id] for evidence_id in item.evidence_ids if evidence_id in evidence]
        next_score = item.score
        risk_notes = list(item.risk_notes)
        if not refs and next_score > 1:
            next_score = 1
            message = f"{item.label} 缺少可追溯证据，封顶 1 分。"
            flags.append(message)
            risk_notes.append(message)
        elif next_score >= 4 and not any(_supports_high_score(ref) for ref in refs):
            next_score = 3.5
            message = f"{item.label} 缺少支持高分的动作、指标或 ownership 组合证据。"
            flags.append(message)
            risk_notes.append(message)
        calibrated.append(
            item.model_copy(
                update={
                    "score": next_score,
                    "weighted_score": round(next_score / 5 * item.max_points, 2),
                    "risk_notes": list(dict.fromkeys(risk_notes)),
                }
            )
        )
    return {
        "common_scores": [item.model_dump() for item in calibrated],
        "common_score": round(sum(item.weighted_score for item in calibrated), 2),
        "common_critic_flags": list(dict.fromkeys(flags)),
    }


def _supports_high_score(item: EvidenceItem) -> bool:
    return item.strength >= 4 and sum([item.has_metric, item.has_specific_tool, item.has_ownership]) >= 2


def _string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value]
    return []
