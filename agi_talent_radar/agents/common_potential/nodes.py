from __future__ import annotations

from typing import Any

from agi_talent_radar.agents.common_potential.rubric import COMMON_RUBRIC
from agi_talent_radar.agents.scoring_normalization import dimension_items, score_value, string_list
from agi_talent_radar.core import llm_client
from agi_talent_radar.core.models import DimensionScore, EvidenceItem, NormalizedResume


COMMON_SCORER_PROMPT = """
你是 AI 人才潜力评估系统里的【通用潜力评分 Agent】。
只输出 JSON 对象，顶层字段必须是 dimension_scores。

这部分只评价跨 Track 都成立的元能力，不评价具体方向熟练度，也不因 Agent 热度、学校或名企背景加分。论文标题和会议名气不能单独代替能力证据，但多项已正式发表的同行评议成果是「研究严谨性」与「证据可信度」的有效外部验证。
每个维度 score 为 0-5：0 无证据；1 只有关键词；2 参与但贡献不清；3 有方法、动作和基本验证；
4 有独立问题定义与完整验证；4.5 有多项独立高质量成果与清晰 ownership 交叉验证；
5 形成可迁移方法论并产生持续学术或工程影响。

每项必须输出 key, label, score, rationale, evidence_ids, risk_notes。
rationale 必须引用存在的 evidence id；没有证据时给 0 分。
同一维度在不同 Track 的表现形式可以不同，但判断标准必须基于候选人的实际动作与可验证证据。
多个独立项目中持续担任负责人、连续产出同一研究主线的高质量成果、从传统方法迁移到新范式，分别是 ownership、成长轨迹和学习迁移的高分证据。不要因简历没有展开每篇论文的消融表就将所有相关维度压到 3 分。
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
    by_key = {
        str(item.get("key")): item
        for item in dimension_items(response.get("dimension_scores", []))
    }
    scores = []
    for dimension in COMMON_RUBRIC:
        raw = by_key.get(dimension.key, {})
        score = score_value(raw.get("score", 0))
        scores.append(
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
        elif next_score >= 4 and not _supports_high_score(item.key, refs):
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
    calibrated = _apply_research_portfolio_floors(calibrated, list(evidence.values()))
    return {
        "common_scores": [item.model_dump() for item in calibrated],
        "common_score": round(sum(item.weighted_score for item in calibrated), 2),
        "common_critic_flags": list(dict.fromkeys(flags)),
    }


def _apply_research_portfolio_floors(
    scores: list[DimensionScore],
    evidence: list[EvidenceItem],
) -> list[DimensionScore]:
    strong_sources = {item.source for item in evidence if item.strength >= 4 and item.source}
    owned = sum(item.has_ownership for item in evidence)
    published = sum(_is_published_result(item) for item in evidence)
    if len(strong_sources) < 6 or owned < 3 or published < 2:
        return scores
    floors = {
        "problem_definition": 4.0,
        "research_rigor": 4.0,
        "learning_transfer": 3.5,
        "ownership": 4.5,
        "evidence_credibility": 4.5,
        "growth_trajectory": 4.0,
    }
    result: list[DimensionScore] = []
    for item in scores:
        floor = floors.get(item.key, 0)
        if item.score >= floor:
            result.append(item)
            continue
        result.append(
            item.model_copy(
                update={
                    "score": floor,
                    "weighted_score": round(floor / 5 * item.max_points, 2),
                    "rationale": f"{item.rationale} 组合证据校准：多项独立负责项目与正式发表成果交叉支撑该潜力判断。",
                }
            )
        )
    return result


def _is_published_result(item: EvidenceItem) -> bool:
    text = " ".join([item.source, item.quote, *item.signals]).lower()
    return item.strength >= 4 and any(token in text for token in ("已发表", "已接收", "ccf-a", "journal"))


def _supports_high_score(dimension_key: str, items: list[EvidenceItem]) -> bool:
    if not items:
        return False
    strong = [item for item in items if item.strength >= 4]
    credible = [item for item in items if item.strength >= 3]
    distinct_sources = {item.source for item in credible if item.source}

    if dimension_key == "problem_definition":
        return any(item.has_ownership and (item.has_specific_tool or item.has_metric) for item in strong) or (
            len(distinct_sources) >= 2
            and any(item.has_ownership for item in credible)
            and any(item.has_specific_tool or item.has_metric for item in credible)
        )
    if dimension_key == "research_rigor":
        return any(item.has_metric or item.has_specific_tool for item in strong) or (
            len(distinct_sources) >= 2 and any(item.has_metric for item in credible)
        )
    if dimension_key == "learning_transfer":
        return len(distinct_sources) >= 2 and len(credible) >= 2
    if dimension_key == "ownership":
        return any(item.has_ownership for item in strong)
    if dimension_key == "evidence_credibility":
        return bool(strong)
    if dimension_key == "growth_trajectory":
        return len(distinct_sources) >= 2 and len(credible) >= 2
    return any(
        item.strength >= 4
        and sum([item.has_metric, item.has_specific_tool, item.has_ownership]) >= 2
        for item in items
    )
