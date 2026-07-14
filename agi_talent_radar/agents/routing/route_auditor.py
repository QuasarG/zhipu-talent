from __future__ import annotations

from agi_talent_radar.core.models import TrackAssignment


def run_route_auditor(state: dict) -> dict:
    assignments = [TrackAssignment.model_validate(item) for item in state.get("track_assignments", [])]
    flags: list[str] = []
    if not assignments:
        flags.append("没有生成有效 Track 路由。")
        return {"routing_flags": flags}
    if len(assignments) > 3:
        flags.append("Track 数量超过 3，需要人工收敛。")
    if abs(sum(item.weight for item in assignments) - 1) > 0.01:
        flags.append("Track 权重之和不为 1。")
    if assignments[0].weight < 0.5:
        flags.append("主 Track 权重低于 50%，候选人方向较分散。")
    for assignment in assignments[1:]:
        if assignment.weight >= 0.2 and len(assignment.evidence_ids) < 2:
            flags.append(f"{assignment.track} 作为第二 Track 但缺少两条独立证据。")
    if float(state.get("routing_confidence", 0)) < 0.7:
        flags.append("Track 路由置信度低于 0.7，建议人工复核。")
    return {"routing_flags": flags}
