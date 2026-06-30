from __future__ import annotations

from collections import defaultdict

from agi_talent_radar.core.models import DimensionScore, EvidenceItem
from agi_talent_radar.core.rubric import RUBRIC


def run_scorer(state: dict) -> dict:
    evidence = [EvidenceItem.model_validate(item) for item in state.get("evidence", [])]
    evidence_by_dimension: dict[str, list[EvidenceItem]] = defaultdict(list)
    for item in evidence:
        evidence_by_dimension[item.dimension].append(item)

    scores: list[DimensionScore] = []
    for dimension in RUBRIC:
        items = evidence_by_dimension.get(dimension.key, [])
        if dimension.key == "cultivation_value" and len(items) < 2:
            score, rationale, refs, risks = _score_cultivation(evidence_by_dimension)
        else:
            score, rationale, refs, risks = _score_dimension(items)

        if state.get("critic_needs_rescore") and score > 4.35 and len(items) < 2:
            score = 4.15
            risks.append("Critic 回炉：高分维度证据数量不足，已封顶。")

        scores.append(
            DimensionScore(
                key=dimension.key,
                label=dimension.label,
                score=round(score, 2),
                weighted_score=round(score * dimension.weight * 20, 2),
                rationale=rationale,
                evidence_ids=[item.id for item in refs[:4]],
                risk_notes=risks,
            )
        )

    return {**state, "scores": [score.model_dump() for score in scores]}


def _score_dimension(items: list[EvidenceItem]) -> tuple[float, str, list[EvidenceItem], list[str]]:
    if not items:
        return 2.0, "简历中没有足够直接证据，按保守分处理。", [], ["缺少可核验证据。"]

    selected = sorted(items, key=lambda item: (-item.strength, item.id))[:5]
    avg_strength = sum(item.strength for item in selected) / len(selected)
    count_bonus = min(len(items), 4) * 0.22
    metric_bonus = 0.22 if any(item.has_metric for item in selected) else 0
    tool_bonus = 0.20 if any(item.has_specific_tool for item in selected) else 0
    owner_bonus = 0.22 if any(item.has_ownership for item in selected) else 0
    score = 1.55 + avg_strength * 0.48 + count_bonus + metric_bonus + tool_bonus + owner_bonus
    risks: list[str] = []
    if not any(item.has_metric for item in selected):
        risks.append("缺少量化结果，需面谈确认真实效果。")
    if not any(item.has_ownership for item in selected):
        risks.append("ownership 信号不够强，需确认本人贡献。")
    if len(items) == 1:
        risks.append("该维度只有单条证据，稳定性偏弱。")
    rationale = _rationale(selected)
    return max(1, min(5, score)), rationale, selected, risks


def _score_cultivation(groups: dict[str, list[EvidenceItem]]) -> tuple[float, str, list[EvidenceItem], list[str]]:
    keys = ["research_exploration", "engineering_practice", "ai_agent_leverage", "problem_definition", "ownership"]
    selected: list[EvidenceItem] = []
    dimension_scores: list[float] = []
    for key in keys:
        items = sorted(groups.get(key, []), key=lambda item: (-item.strength, item.id))[:2]
        selected.extend(items)
        if items:
            dimension_scores.append(sum(item.strength for item in items) / len(items))
    if not selected:
        return 2.0, "长期培养价值缺少跨维度证据，按保守分处理。", [], ["缺少跨维度证据。"]
    breadth = len({item.dimension for item in selected})
    avg_strength = sum(dimension_scores) / len(dimension_scores)
    score = 1.45 + avg_strength * 0.50 + min(breadth, 5) * 0.22
    if any(item.has_metric for item in selected):
        score += 0.18
    if any("闭环" in item.quote or "平台" in item.quote or "系统" in item.quote for item in selected):
        score += 0.22
    risks = [] if breadth >= 4 else ["长期潜力证据广度不足，需要更多真实项目验证。"]
    return max(1, min(5, score)), _rationale(selected[:5]), selected, risks


def _rationale(items: list[EvidenceItem]) -> str:
    if not items:
        return "未找到直接证据。"
    parts = []
    for item in items[:3]:
        signals = "、".join(item.signals[:3]) if item.signals else "简历直接描述"
        parts.append(f"{item.id} 体现 {signals}")
    return "；".join(parts) + "。"
