from __future__ import annotations

from typing import Any

from agi_talent_radar.agents.common_potential.rubric import COMMON_RUBRIC
from agi_talent_radar.agents.scoring_normalization import dimension_items, score_value, string_list
from agi_talent_radar.core import llm_client
from agi_talent_radar.core.models import DimensionScore, EvidenceItem, NormalizedResume
from agi_talent_radar.core.scoring_config import DEFAULT as CFG
from agi_talent_radar.core.stage_profile import STANDARD, StageProfile, profile_for_stage


COMMON_SCORER_PROMPT = """
你是 AI 人才潜力评估系统里的【通用潜力评分 Agent】。
只输出 JSON 对象，顶层字段必须是 dimension_scores。

这部分只评价跨 Track 都成立的元能力，不评价具体方向熟练度，也不因 Agent 热度、学校或名企背景加分。论文标题和会议名气不能单独代替能力证据，但多项已正式发表的同行评议成果是「研究严谨性」与「证据可信度」的有效外部验证。
每个维度 score 为 0-5，评分严格参照 rubric 中每个维度提供的 anchors：
- 0-3 为统一能力阶梯（所有维度通用）：0 无证据；1 只有关键词/方向；2 参与但说不清自己做了什么；3 能说清方法+本人动作+基本结果。
- 4 / 4.5 / 5 为维度特异行为锚，每个维度定义不同，必须逐条对照充分条件和降档触发判定。每个维度的 anchors 已在 rubric 中给出。
- 5 分为博士阶段罕见但可达，多数人不应达到，空着正常。

每项必须输出 key, label, score, rationale, evidence_ids, risk_notes。
rationale 必须引用存在的 evidence id；没有证据时给 0 分。
论文信任原则（优先于核验状态）：以简历自述为准。声称已发表即按已发表计，声称一作即按一作计，正常参与评分。经外部数据库核验确认（verified）的论文，在 research_rigor 与 evidence_credibility 上可给予更高评价；但核验未通过或未核验的论文，不得因此降低评分。作者顺序与自述不符同样不扣分，仅作风险记录。
硬性锚点（优先于其他判断）：
1. research_rigor 与 evidence_credibility：引用证据中没有任何量化指标、baseline/对照、复现、量化验收或正式发表成果时，得分不得超过 {no_verification:g}。
2. 任何维度 4 分以上，必须同时有本人具体动作和可验证结果（指标、产物、验收）的组合证据；只有方向、参与或头衔描述时封顶 {no_high_score_support:g}。
3. 论文列表、学校、机构、热门术语本身不构成加分理由。
4. 必须遵循 stage_profile 的证据预期：早期阶段以项目潜力证据为主，不因发表数量不足单独扣分；高年级则把持续产出和可核验成果作为重要待核验项。
同一维度在不同 Track 的表现形式可以不同，但判断标准必须基于候选人的实际动作与可验证证据。
多个独立项目中持续担任负责人、连续产出同一研究主线的高质量成果、从传统方法迁移到新范式，分别是 ownership、成长轨迹和学习迁移的高分证据。不要因简历没有展开每篇论文的消融表就将所有相关维度压到 3 分。
实习/工作经历可支撑通用潜力，但只评价其中的问题定义、本人动作、验证闭环、ownership 和成长迁移。脱敏机构档位、机构类型、岗位名和时长均不得直接加分。
""".strip().format(
    no_verification=CFG.caps.no_verification,
    no_high_score_support=CFG.caps.no_high_score_support,
)


def run_common_scorer(state: dict[str, Any]) -> dict[str, Any]:
    normalized = NormalizedResume.model_validate(state["normalized"])
    stage_profile = profile_for_stage(normalized.stage)
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
                    "anchors": item.anchors or {},
                }
                for item in COMMON_RUBRIC
            ],
            "track_assignments": state.get("track_assignments", []),
            "stage_profile": stage_profile.__dict__,
            "academic_report": state.get("academic_report", {}),
            "resume_brief": normalized.model_dump(exclude={"raw_text", "education_raw", "experiences_raw"}),
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
                weighted_score=CFG.weighted_score(score, dimension.max_points),
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
    normalized_raw = state.get("normalized")
    stage_profile = profile_for_stage(NormalizedResume.model_validate(normalized_raw).stage) if normalized_raw else STANDARD
    evidence = {item.id: item for item in [EvidenceItem.model_validate(raw) for raw in state.get("evidence", [])]}
    calibrated: list[DimensionScore] = []
    flags: list[str] = []

    for raw in state.get("common_scores", []):
        item = DimensionScore.model_validate(raw)
        refs = [evidence[evidence_id] for evidence_id in item.evidence_ids if evidence_id in evidence]
        next_score = item.score
        risk_notes = list(item.risk_notes)
        if not refs and next_score > CFG.caps.no_evidence:
            next_score = CFG.caps.no_evidence
            message = f"{item.label} 缺少可追溯证据，封顶 {CFG.caps.no_evidence:g} 分。"
            flags.append(message)
            risk_notes.append(message)
        elif item.key == "research_rigor" and next_score > CFG.caps.no_verification and not _has_stage_appropriate_verification(refs, stage_profile):
            next_score = CFG.caps.no_verification
            message = f"{item.label} 引用证据缺少量化指标、对照、复现或正式发表成果，封顶 {CFG.caps.no_verification:g} 分。"
            flags.append(message)
            risk_notes.append(message)
        elif item.key == "evidence_credibility" and next_score > CFG.caps.no_verification and not _has_stage_appropriate_verification(refs, stage_profile):
            next_score = CFG.caps.no_verification
            message = f"{item.label} 引用证据缺少量化指标、可运行产物或正式发表等可核验结果，封顶 {CFG.caps.no_verification:g} 分。"
            flags.append(message)
            risk_notes.append(message)
        elif next_score >= 4 and not _supports_high_score(item.key, refs):
            next_score = CFG.caps.no_high_score_support
            message = f"{item.label} 缺少支持高分的动作、指标或 ownership 组合证据。"
            flags.append(message)
            risk_notes.append(message)
        calibrated.append(
            item.model_copy(
                update={
                    "score": next_score,
                    "weighted_score": CFG.weighted_score(next_score, item.max_points),
                    "risk_notes": list(dict.fromkeys(risk_notes)),
                }
            )
        )
    evidence_items = list(evidence.values())
    calibrated = _apply_research_portfolio_floors(calibrated, evidence_items)
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
    pf = CFG.portfolio_floors
    if len(strong_sources) < pf.strong_sources_min or owned < pf.owned_min or published < pf.published_min:
        return scores
    result: list[DimensionScore] = []
    for item in scores:
        floor = pf.floors.get(item.key, 0)
        if item.score >= floor:
            result.append(item)
            continue
        result.append(
            item.model_copy(
                update={
                    "score": floor,
                    "weighted_score": CFG.weighted_score(floor, item.max_points),
                    "rationale": f"{item.rationale} 组合证据校准：多项独立负责项目与正式发表成果交叉支撑该潜力判断。",
                }
            )
        )
    return result


def _is_published_result(item: EvidenceItem) -> bool:
    text = " ".join([item.source, item.quote, *item.signals]).lower()
    return item.strength >= 4 and any(token in text for token in ("已发表", "已接收", "ccf-a", "journal"))


def _has_verification(refs: list[EvidenceItem], allow_tool: bool) -> bool:
    for item in refs:
        if item.has_metric or _is_published_result(item):
            return True
        if allow_tool and item.has_specific_tool:
            return True
        text = " ".join([item.source, item.quote, *item.signals]).lower()
        if any(token in text for token in ("验收", "上线", "可运行", "可复现")):
            return True
    return False


def _has_stage_appropriate_verification(refs: list[EvidenceItem], profile: StageProfile) -> bool:
    if _has_verification(refs, allow_tool=True):
        return True
    if not profile.project_potential_first:
        return False
    owned = [item for item in refs if item.strength >= 3 and item.has_ownership]
    sources = {item.source for item in owned if item.source}
    project_terms = ("设计", "实现", "原型", "构建", "开发")
    return len(sources) >= 2 and any(term in item.quote for item in owned for term in project_terms)


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
