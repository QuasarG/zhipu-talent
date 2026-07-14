from __future__ import annotations

from typing import Any

from agi_talent_radar.core import llm_client
from agi_talent_radar.agents.scoring_normalization import dimension_items, score_value, string_list
from agi_talent_radar.core.models import DimensionScore, EvidenceItem, NormalizedResume, TrackAssignment, TrackEvaluation
from agi_talent_radar.agents.tracks.shared.spec import TrackDimensionSpec, TrackSpec


TRACK_SCORER_PROMPT = """
你是 AI 人才潜力评估系统里的【{track_label} 专业评估 Agent】。
只输出 JSON 对象，顶层字段必须是 dimension_scores。

你只评价当前 Track 的专业能力，不重复评价学校、GPA、通用成长潜力，也不因为候选人使用热门术语而加分。
每个维度 score 为 0-5：
- 0：没有证据。
- 1：只有关键词、方向或论文标题。
- 2：参与过相关工作，但贡献、方法或验证不清。
- 3：有具体方法、本人动作和基本验证。
- 4：有原创问题定义以及完整实验或工程闭环。
- 5：形成可迁移方法论，并有强验证、实际影响和清晰 ownership。

每项必须输出 key, label, score, rationale, evidence_ids, risk_notes。
rationale 必须引用存在的 evidence id。没有证据时 score 必须为 0，不要硬凑。
Track 证据重点：{evidence_focus}
高分规则：{high_score_rule}
""".strip()


def run_track_chain(state: dict[str, Any], spec: TrackSpec) -> dict[str, Any]:
    assignment = _assignment_for_track(state, spec)
    if assignment is None:
        return {"track_results": []}

    normalized = NormalizedResume.model_validate(state["normalized"])
    evidence = [EvidenceItem.model_validate(item) for item in state.get("evidence", [])]
    selected = _select_track_evidence(evidence, assignment, spec)
    response = llm_client.call_llm_json(
        TRACK_SCORER_PROMPT.format(
            track_label=spec.label,
            evidence_focus=spec.evidence_focus,
            high_score_rule=spec.high_score_rule,
        ),
        {
            "track": spec.as_prompt_dict(),
            "assignment": assignment.model_dump(),
            "resume_brief": normalized.model_dump(exclude={"raw_text", "education_raw"}),
            "evidence": [item.model_dump() for item in selected],
        },
        temperature=0.1,
    )
    scores = _normalize_scores(response.get("dimension_scores", []), spec)
    calibrated, critic_flags = _calibrate_scores(scores, selected, spec)
    raw_score = round(sum(item.weighted_score for item in scores), 2)
    calibrated_score = round(sum(item.weighted_score for item in calibrated), 2)
    risk_notes = [note for item in calibrated for note in item.risk_notes]
    result = TrackEvaluation(
        track=spec.key,
        label=spec.label,
        weight=assignment.weight,
        confidence=assignment.confidence,
        raw_score=raw_score,
        calibrated_score=calibrated_score,
        dimension_scores=calibrated,
        evidence_ids=sorted({evidence_id for item in calibrated for evidence_id in item.evidence_ids}),
        risk_notes=list(dict.fromkeys(risk_notes)),
        critic_flags=critic_flags,
    )
    return {"track_results": [result.model_dump()]}


def _assignment_for_track(state: dict[str, Any], spec: TrackSpec) -> TrackAssignment | None:
    for item in state.get("track_assignments", []):
        assignment = TrackAssignment.model_validate(item)
        if assignment.track == spec.key and assignment.weight > 0:
            return assignment
    return None


def _select_track_evidence(
    evidence: list[EvidenceItem],
    assignment: TrackAssignment,
    spec: TrackSpec,
) -> list[EvidenceItem]:
    assigned_ids = set(assignment.evidence_ids)
    selected = [item for item in evidence if item.id in assigned_ids or spec.key in item.track_hints]
    return selected or evidence


def _normalize_scores(raw_scores: Any, spec: TrackSpec) -> list[DimensionScore]:
    by_key = {str(item.get("key")): item for item in dimension_items(raw_scores)}
    result: list[DimensionScore] = []
    for dimension in spec.dimensions:
        raw = by_key.get(dimension.key, {})
        score = score_value(raw.get("score", 0))
        result.append(
            DimensionScore(
                key=dimension.key,
                label=dimension.label,
                score=score,
                max_points=dimension.max_points,
                weighted_score=round(score / 5 * dimension.max_points, 2),
                rationale=str(raw.get("rationale", "该维度未返回有效理由。")),
                evidence_ids=string_list(raw.get("evidence_ids", [])),
                risk_notes=string_list(raw.get("risk_notes", [])),
            )
        )
    return result


def _calibrate_scores(
    scores: list[DimensionScore],
    evidence: list[EvidenceItem],
    spec: TrackSpec,
) -> tuple[list[DimensionScore], list[str]]:
    evidence_by_id = {item.id: item for item in evidence}
    dimension_specs = {item.key: item for item in spec.dimensions}
    calibrated: list[DimensionScore] = []
    critic_flags: list[str] = []

    for item in scores:
        refs = [evidence_by_id[evidence_id] for evidence_id in item.evidence_ids if evidence_id in evidence_by_id]
        next_score = item.score
        risk_notes = list(item.risk_notes)
        if not refs and next_score > 1:
            next_score = 1
            message = f"{item.label} 缺少可追溯证据，按规则封顶 1 分。"
            risk_notes.append(message)
            critic_flags.append(message)
        elif next_score >= 4 and not any(_is_strong_evidence(ref) for ref in refs):
            next_score = 3.5
            message = f"{item.label} 的高分缺少量化、工具或 ownership 组合证据，封顶 3.5 分。"
            risk_notes.append(message)
            critic_flags.append(message)

        dimension = dimension_specs[item.key]
        calibrated.append(
            item.model_copy(
                update={
                    "score": next_score,
                    "weighted_score": round(next_score / 5 * dimension.max_points, 2),
                    "risk_notes": list(dict.fromkeys(risk_notes)),
                }
            )
        )
    return calibrated, list(dict.fromkeys(critic_flags))


def _is_strong_evidence(item: EvidenceItem) -> bool:
    hard_signals = sum([item.has_metric, item.has_specific_tool, item.has_ownership])
    return item.strength >= 4 and hard_signals >= 2
