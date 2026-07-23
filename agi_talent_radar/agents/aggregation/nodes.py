from __future__ import annotations

from agi_talent_radar.core.models import TrackAssignment, TrackEvaluation


def run_portfolio_aggregator(state: dict) -> dict:
    assignments = [TrackAssignment.model_validate(item) for item in state.get("track_assignments", [])]
    results = [TrackEvaluation.model_validate(item) for item in state.get("track_results", [])]
    result_by_track = {item.track: item for item in results}
    common_score = max(0.0, min(40.0, float(state.get("common_score", 0))))

    contributions = []
    track_total = 0.0
    for assignment in assignments:
        result = result_by_track.get(assignment.track)
        specialist_score = result.calibrated_score if result else 0.0
        contribution = round(assignment.weight * specialist_score, 2)
        track_total += contribution
        contributions.append(
            {
                "track": assignment.track,
                "weight": assignment.weight,
                "specialist_score": specialist_score,
                "contribution": contribution,
                "available": result is not None,
            }
        )

    total = max(0.0, min(100.0, common_score + track_total))
    overall = int(round(total))
    return {
        "portfolio_assessment": {
            "overall_score": overall,
            "raw_total": round(total, 2),
            "common_score": round(common_score, 2),
            "track_score": round(track_total, 2),
            "document_score": 0.0,
            "track_contributions": contributions,
            "level": _level_for_score(overall),
            "tier": _tier_for_score(overall),
        }
    }


def run_global_critic(state: dict) -> dict:
    assignments = [TrackAssignment.model_validate(item) for item in state.get("track_assignments", [])]
    results = [TrackEvaluation.model_validate(item) for item in state.get("track_results", [])]
    result_tracks = {item.track for item in results}
    flags = list(state.get("routing_flags", []))
    flags.extend(state.get("common_critic_flags", []))

    for assignment in assignments:
        if assignment.track not in result_tracks:
            flags.append(f"{assignment.track} 已分配权重但没有生成 Track 专业评分。")
    for result in results:
        flags.extend(result.critic_flags)
    portfolio = state.get("portfolio_assessment", {})
    if not 0 <= float(portfolio.get("overall_score", -1)) <= 100:
        flags.append("最终分数超出 0-100 范围。")
    return {"global_critic_flags": list(dict.fromkeys(flags))}


def _level_for_score(score: int) -> str:
    if score >= 90:
        return "S"
    if score >= 80:
        return "A"
    if score >= 60:
        return "B"
    return "C"


def _tier_for_score(score: int) -> str:
    if score >= 80:
        return "强烈建议沟通"
    if score >= 60:
        return "建议沟通"
    return "暂缓 / 需补充信息"
