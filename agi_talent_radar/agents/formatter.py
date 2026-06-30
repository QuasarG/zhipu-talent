from __future__ import annotations

from collections import Counter

from agi_talent_radar.core.models import (
    CandidateEvaluation,
    DimensionScore,
    EvidenceItem,
    NormalizedResume,
)
from agi_talent_radar.core.rubric import DIMENSION_LABELS


def run_formatter(state: dict) -> dict:
    normalized = NormalizedResume.model_validate(state["normalized"])
    evidence = [EvidenceItem.model_validate(item) for item in state.get("evidence", [])]
    scores = [DimensionScore.model_validate(item) for item in state.get("scores", [])]
    evidence_by_id = {item.id: item for item in evidence}
    overall_score = max(0, min(100, round(sum(item.weighted_score for item in scores))))
    level = _level(overall_score)
    tier = _tier(overall_score)
    top_scores = sorted(scores, key=lambda item: item.score, reverse=True)[:3]
    weak_scores = sorted(scores, key=lambda item: item.score)[:2]
    selected_evidence = _selected_evidence(top_scores, evidence_by_id)

    evaluation = CandidateEvaluation(
        id=normalized.id,
        name=normalized.name,
        target_role=normalized.target_role,
        stage=normalized.stage,
        overall_score=overall_score,
        level=level,
        tier=tier,
        one_liner=_one_liner(normalized, top_scores, selected_evidence),
        core_strengths=_core_strengths(top_scores, evidence_by_id),
        potential_risks=_risks(normalized, weak_scores, scores, state.get("critic_flags", [])),
        interview_questions=_questions(top_scores, weak_scores, evidence_by_id, normalized),
        cultivation_direction=_cultivation_direction(normalized, top_scores),
        dimension_scores=scores,
        evidence=_display_evidence(evidence),
        critic_flags=state.get("critic_flags", []),
        normalized_education=normalized.education_blind,
        screening_tags=normalized.screening_tags,
    )
    return {**state, "final_output": evaluation.model_dump()}


def _level(score: int) -> str:
    if score >= 90:
        return "S"
    if score >= 82:
        return "A"
    if score >= 72:
        return "B"
    return "C"


def _tier(score: int) -> str:
    if score >= 80:
        return "强烈建议沟通"
    if score >= 74:
        return "建议沟通"
    return "暂缓 / 需补充信息"


def _selected_evidence(top_scores: list[DimensionScore], evidence_by_id: dict[str, EvidenceItem]) -> list[EvidenceItem]:
    items: list[EvidenceItem] = []
    for score in top_scores:
        for evidence_id in score.evidence_ids:
            item = evidence_by_id.get(evidence_id)
            if item:
                items.append(item)
    return list({item.id: item for item in items}.values())


def _one_liner(normalized: NormalizedResume, top_scores: list[DimensionScore], evidence: list[EvidenceItem]) -> str:
    labels = "、".join(score.label for score in top_scores[:2])
    strongest = evidence[0].quote if evidence else (normalized.directions[0] if normalized.directions else normalized.target_role)
    return f"{normalized.target_role}的高潜候选人，突出在{labels}，代表证据是“{strongest}”。"


def _display_evidence(evidence: list[EvidenceItem]) -> list[EvidenceItem]:
    selected: list[EvidenceItem] = []
    seen: set[tuple[str, str]] = set()
    for item in sorted(evidence, key=lambda one: (-one.strength, one.id)):
        key = (item.source, item.quote)
        if key in seen:
            continue
        seen.add(key)
        selected.append(item)
        if len(selected) >= 14:
            break
    return selected


def _core_strengths(top_scores: list[DimensionScore], evidence_by_id: dict[str, EvidenceItem]) -> list[str]:
    strengths: list[str] = []
    for score in top_scores:
        refs = [evidence_by_id[eid] for eid in score.evidence_ids if eid in evidence_by_id]
        if refs:
            strengths.append(f"{score.label}强：{refs[0].quote}")
        else:
            strengths.append(f"{score.label}相对突出。")
    return strengths[:4]


def _risks(
    normalized: NormalizedResume,
    weak_scores: list[DimensionScore],
    scores: list[DimensionScore],
    critic_flags: list[str],
) -> list[str]:
    risks: list[str] = []
    for score in weak_scores:
        if score.score < 3.6:
            risks.append(f"{score.label}证据偏弱：{'；'.join(score.risk_notes[:2]) or '需要面谈验证'}")
    if any("拟投" in pub or "Under Review" in pub for pub in normalized.publications):
        risks.append("部分成果仍处在拟投或审稿阶段，需要确认论文、实验和本人贡献。")
    if not any(score.key == "ownership" and score.score >= 4.0 for score in scores):
        risks.append("ownership 需要进一步确认，避免把团队平台成果误判为个人能力。")
    risks.extend(critic_flags[:2])
    return list(dict.fromkeys(risks))[:5] or ["暂未发现明显硬伤，但仍需通过面谈验证项目真实性和本人贡献。"]


def _questions(
    top_scores: list[DimensionScore],
    weak_scores: list[DimensionScore],
    evidence_by_id: dict[str, EvidenceItem],
    normalized: NormalizedResume,
) -> list[str]:
    questions: list[str] = []
    metric_evidence = [
        evidence_by_id[eid]
        for score in top_scores
        for eid in score.evidence_ids
        if eid in evidence_by_id and evidence_by_id[eid].has_metric
    ]
    if metric_evidence:
        quote = metric_evidence[0].quote
        questions.append(f"你提到“{quote}”，baseline、评测集和消融设计分别是什么？")
    strong_evidence = [
        evidence_by_id[eid]
        for score in top_scores
        for eid in score.evidence_ids
        if eid in evidence_by_id
    ]
    if strong_evidence:
        questions.append(f"围绕“{strong_evidence[0].quote}”，哪些模块是你独立设计，哪些来自团队已有系统？")
    weak = weak_scores[0]
    questions.append(f"{weak.label}相对需要补证，请举一个失败案例，并说明你后来如何调整判断或方案。")
    if normalized.screening_tags:
        questions.append(f"如果进入{normalized.screening_tags[0]}相关项目，你会如何定义第一个月的可验证交付物？")
    else:
        questions.append("如果给你一个真实业务场景，你会如何把研究问题拆成可验证的工程闭环？")
    return list(dict.fromkeys(questions))[:4]


def _cultivation_direction(normalized: NormalizedResume, top_scores: list[DimensionScore]) -> list[str]:
    tags = Counter(normalized.screening_tags + normalized.directions)
    labels = {score.key for score in top_scores}
    directions: list[str] = []
    if "engineering_practice" in labels:
        directions.append("安排到可运行系统或训练 / 推理基础设施项目中，观察交付质量。")
    if "ai_agent_leverage" in labels:
        directions.append("参与 Agent 工作流、自动评测或数据闭环项目，验证工具化能力。")
    if "research_exploration" in labels:
        directions.append("给一个需要独立定义 baseline 和 ablation 的研究题，观察问题定义能力。")
    if tags:
        directions.append(f"优先匹配 {tags.most_common(1)[0][0]} 方向的小闭环项目。")
    return directions[:4] or ["先进入短周期研究原型项目，用真实交付验证长期培养价值。"]
