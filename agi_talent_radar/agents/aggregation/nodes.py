from __future__ import annotations

from agi_talent_radar.core.models import TrackAssignment, TrackEvaluation
from agi_talent_radar.core.scoring_config import DEFAULT as CFG


def run_portfolio_aggregator(state: dict) -> dict:
    assignments = [TrackAssignment.model_validate(item) for item in state.get("track_assignments", [])]
    results = [TrackEvaluation.model_validate(item) for item in state.get("track_results", [])]
    result_by_track = {item.track: item for item in results}
    common_score = max(0.0, min(CFG.aggregate_bounds.common_max, float(state.get("common_score", 0))))

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

    total = max(CFG.aggregate_bounds.overall_min, min(CFG.aggregate_bounds.overall_max, common_score + track_total))
    overall = int(round(total))
    return {
        "portfolio_assessment": {
            "overall_score": overall,
            "raw_total": round(total, 2),
            "common_score": round(common_score, 2),
            "track_score": round(track_total, 2),
            "document_score": 0.0,
            "track_contributions": contributions,
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
    flags.extend(_academic_verification_flags(state.get("academic_report", {})))
    portfolio = state.get("portfolio_assessment", {})
    if not CFG.aggregate_bounds.overall_min <= float(portfolio.get("overall_score", -1)) <= CFG.aggregate_bounds.overall_max:
        flags.append("最终分数超出 0-100 范围。")
    return {"global_critic_flags": list(dict.fromkeys(flags))}


def _academic_verification_flags(report: dict) -> list[str]:
    """把论文核验冲突转成风险提示(只提示,不改分)。

    信任优先:mismatch/unverifiable 只进风险,人工已确认的不再提示。
    """
    if not report:
        return []
    flags: list[str] = []
    for align in report.get("alignments", []) or []:
        if not isinstance(align, dict):
            continue
        # 人工已确认的,不再当作风险
        if str(align.get("human_status", "")).strip() == "confirmed":
            continue
        claim = align.get("claim") or {}
        title = str(claim.get("title", "")).strip()
        title_ref = f"《{title}》" if title else "某论文"
        verdict = str(align.get("verdict", "")).strip()
        if verdict == "mismatch":
            discrepancies = align.get("discrepancies") or []
            detail = "; ".join(str(d) for d in discrepancies if d) if discrepancies else "详见核验记录"
            flags.append(f"论文{title_ref}外部核验与自述不符,建议人工确认:{detail}")
        elif verdict == "unverifiable":
            flags.append(f"论文{title_ref}未能外部核验,真实性按自述处理")
    for warning in report.get("warnings", []) or []:
        if warning:
            flags.append(str(warning))
    return flags
