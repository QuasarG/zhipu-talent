from __future__ import annotations

from collections import defaultdict

from agi_talent_radar.core.models import DimensionScore, EvidenceItem, NormalizedResume


def run_critic(state: dict) -> dict:
    normalized = NormalizedResume.model_validate(state["normalized"])
    evidence = [EvidenceItem.model_validate(item) for item in state.get("evidence", [])]
    scores = [DimensionScore.model_validate(item) for item in state.get("scores", [])]
    flags: list[str] = []

    for item in evidence:
        if item.quote not in normalized.raw_text:
            flags.append(f"疑似幻觉证据：{item.id} 的引文未出现在原简历。")

    evidence_by_dimension: dict[str, list[EvidenceItem]] = defaultdict(list)
    for item in evidence:
        evidence_by_dimension[item.dimension].append(item)

    for score in scores:
        items = evidence_by_dimension.get(score.key, [])
        if score.score >= 4.5:
            concrete = [
                item
                for item in items
                if item.has_metric or item.has_specific_tool or item.has_ownership or item.strength >= 4
            ]
            if len(items) < 2 or not concrete:
                flags.append(f"{score.label} 给到 {score.score} 分，但证据数量或硬信号不足。")
        if score.score >= 4.8 and not any(item.has_metric for item in items):
            flags.append(f"{score.label} 接近满分，但没有量化结果支撑。")

    loop_count = int(state.get("loop_count", 0))
    needs_rescore = bool(flags) and loop_count < 1
    return {
        **state,
        "critic_flags": flags,
        "critic_needs_rescore": needs_rescore,
        "loop_count": loop_count + 1 if needs_rescore else loop_count,
    }


def route_after_critic(state: dict) -> str:
    return "scorer" if state.get("critic_needs_rescore") else "formatter"
