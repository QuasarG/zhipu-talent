from __future__ import annotations

from collections.abc import Callable
from typing import Any

from agi_talent_radar.core import llm_client
from agi_talent_radar.agents.scoring_normalization import dimension_items, score_value, string_list
from agi_talent_radar.core.models import DimensionScore, EvidenceItem, NormalizedResume, TrackAssignment, TrackEvaluation
from agi_talent_radar.agents.tracks.shared.spec import TrackDimensionSpec, TrackSpec
from agi_talent_radar.core.scoring_config import DEFAULT as CFG
from agi_talent_radar.core.stage_profile import StageProfile, profile_for_stage


TRACK_SCORER_PROMPT = """
你是 AI 人才潜力评估系统里的【{track_label} 专业评估 Agent】。
只输出 JSON 对象，顶层字段必须是 dimension_scores。

你只评价当前 Track 的专业能力，不重复评价学校、GPA、通用成长潜力，也不因为候选人使用热门术语而加分。
每个维度 score 为 0-5：
- 0：没有证据。
- 1：只有关键词、方向或论文标题。
- 2：参与过相关工作，但贡献、方法或验证仅有部分信息。
- 3：有具体方法或本人动作，并有项目、系统或研究成果支撑。
- 4：有原创方法/问题定义和较完整的研究或工程闭环，多条独立强证据可交叉支撑。
- 4.5：多项独立高质量成果与项目 ownership 交叉验证，已明显超过单项工作的完整闭环。
- 5：形成可迁移方法论，并有强验证、清晰 ownership 和学术或产业影响。

评分原则：
1. 评价候选人已被证据支撑的能力，不是评价简历是否写成完整论文。
2. 正式发表的高水平同行评议成果是有效外部验证；不得与仅有论文标题的拟投成果等同。
3. 项目负责人 + 具体技术方法 + 可核验成果可构成高分组合证据，不强求它们出现在同一条 evidence 中。
4. 同一个「缺少量化指标/贡献细节」不得在多个维度重复扣分；将它放在最相关维度的 risk_notes 中。
5. 实习/工作经历中的具体方法、系统、指标和产物与项目证据同等有效；但机构档位、机构类型、岗位名或时长本身不得加分。
6. 必须遵循 stage_profile：早期阶段以项目中的方法、本人动作和验证思路判断潜力，不因发表数量不足单独扣分；高年级候选人的论文、代码或系统产出应列为外部核验重点。
论文信任原则（优先于核验状态）：以简历自述为准。声称已发表即按已发表计，声称一作即按一作计，正常参与评分。经外部数据库核验确认（verified）的论文可给予更高评价；但核验未通过或未核验的论文，不得因此降低评分。作者顺序与自述不符同样不扣分，仅作风险记录。

硬性锚点（优先于其他判断）：
- 引用证据中没有任何量化指标、可运行产物、验收结果或正式发表成果时，该维度得分不得超过 {no_verification:g}。
- 4 分以上需要指标、具体工具或 ownership 中至少两项的组合证据；只有方向或参与描述时封顶 {no_high_score_support:g}。

每项必须输出 key, label, score, rationale, evidence_ids, risk_notes。
rationale 必须引用存在的 evidence id。没有证据时 score 必须为 0，不要硬凑。
Track 证据重点：{evidence_focus}
高分规则：{high_score_rule}
""".strip()


PortfolioCalibrator = Callable[
    [list[DimensionScore], list[EvidenceItem]],
    list[DimensionScore],
]


def run_dynamic_tracks(state: dict[str, Any]) -> dict[str, Any]:
    """JD 池驱动的动态 track 节点：对路由命中的每个 active track 跑共享引擎。

    替代旧的 6 个静态 track 节点——track 集合随 JD 池实时变动，
    spec 在节点运行时从 DB 加载，graph 无需为增删 track 重新编译。
    """
    from agi_talent_radar.agents.tracks.registry import load_active_specs

    specs = load_active_specs()
    results: list[dict[str, Any]] = []
    for raw in state.get("track_assignments", []):
        spec = specs.get(str(raw.get("track", "")))
        if spec is None:
            continue
        results.extend(run_track_chain(state, spec).get("track_results", []))
    return {"track_results": results}


def run_track_chain(
    state: dict[str, Any],
    spec: TrackSpec,
    portfolio_calibrator: PortfolioCalibrator | None = None,
) -> dict[str, Any]:
    assignment = _assignment_for_track(state, spec)
    if assignment is None:
        return {"track_results": []}

    normalized = NormalizedResume.model_validate(state["normalized"])
    stage_profile = profile_for_stage(normalized.stage)
    evidence = [EvidenceItem.model_validate(item) for item in state.get("evidence", [])]
    selected = _select_track_evidence(evidence, assignment, spec)
    response = llm_client.call_llm_json(
        TRACK_SCORER_PROMPT.format(
            track_label=spec.label,
            evidence_focus=spec.evidence_focus,
            high_score_rule=spec.high_score_rule,
            no_verification=CFG.caps.no_verification,
            no_high_score_support=CFG.caps.no_high_score_support,
        ),
        {
            "track": spec.as_prompt_dict(),
            "assignment": assignment.model_dump(),
            "resume_brief": normalized.model_dump(exclude={"raw_text", "education_raw", "experiences_raw"}),
            "stage_profile": stage_profile.__dict__,
            "academic_report": state.get("academic_report", {}),
            "evidence": [item.model_dump() for item in selected],
        },
        temperature=0.1,
    )
    scores = _normalize_scores(response.get("dimension_scores", []), spec)
    calibrated, critic_flags = _calibrate_scores(scores, selected, spec, stage_profile)
    if portfolio_calibrator is not None:
        calibrated = portfolio_calibrator(calibrated, selected)
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
                weighted_score=CFG.weighted_score(score, dimension.max_points),
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
    stage_profile: StageProfile = StageProfile("standard", "阶段未细分", ""),
) -> tuple[list[DimensionScore], list[str]]:
    evidence_by_id = {item.id: item for item in evidence}
    dimension_specs = {item.key: item for item in spec.dimensions}
    calibrated: list[DimensionScore] = []
    critic_flags: list[str] = []

    for item in scores:
        refs = [evidence_by_id[evidence_id] for evidence_id in item.evidence_ids if evidence_id in evidence_by_id]
        next_score = item.score
        risk_notes = list(item.risk_notes)
        if not refs and next_score > CFG.caps.no_evidence:
            next_score = CFG.caps.no_evidence
            message = f"{item.label} 缺少可追溯证据，按规则封顶 {CFG.caps.no_evidence:g} 分。"
            risk_notes.append(message)
            critic_flags.append(message)
        elif next_score > CFG.caps.no_verification and not _has_stage_appropriate_verification(refs, stage_profile):
            next_score = CFG.caps.no_verification
            message = f"{item.label} 引用证据缺少量化指标、产物、验收或正式发表成果，封顶 {CFG.caps.no_verification:g} 分。"
            risk_notes.append(message)
            critic_flags.append(message)
        elif next_score >= 4 and not _supports_high_score(refs):
            next_score = CFG.caps.no_high_score_support
            message = f"{item.label} 的高分缺少量化、工具或 ownership 组合证据，封顶 {CFG.caps.no_high_score_support:g} 分。"
            risk_notes.append(message)
            critic_flags.append(message)

        dimension = dimension_specs[item.key]
        calibrated.append(
            item.model_copy(
                update={
                    "score": next_score,
                    "weighted_score": CFG.weighted_score(next_score, dimension.max_points),
                    "risk_notes": list(dict.fromkeys(risk_notes)),
                }
            )
        )
    return calibrated, list(dict.fromkeys(critic_flags))


def _supports_high_score(items: list[EvidenceItem]) -> bool:
    strong = [item for item in items if item.strength >= 4]
    if any(sum([item.has_metric, item.has_specific_tool, item.has_ownership]) >= 2 for item in strong):
        return True
    distinct_sources = {item.source for item in strong if item.source}
    return len(distinct_sources) >= 2


def _has_published_signal(item: EvidenceItem) -> bool:
    """已发表/已接收的论文本身即验证证据(无量化指标时也成立)。"""
    text = " ".join(item.signals)
    return "发表状态:已发表" in text or "发表状态:已接收" in text


def _has_verification(refs: list[EvidenceItem]) -> bool:
    for item in refs:
        if item.has_metric or item.has_specific_tool or _has_published_signal(item):
            return True
        text = " ".join([item.source, item.quote, *item.signals]).lower()
        if any(token in text for token in ("已发表", "已接收", "ccf-a", "journal", "验收", "上线")):
            return True
    return False


def _has_stage_appropriate_verification(refs: list[EvidenceItem], profile: StageProfile) -> bool:
    if _has_verification(refs):
        return True
    if not profile.project_potential_first:
        return False
    owned = [item for item in refs if item.strength >= 3 and item.has_ownership]
    sources = {item.source for item in owned if item.source}
    project_terms = ("设计", "实现", "原型", "构建", "开发")
    return len(sources) >= 2 and any(term in item.quote for item in owned for term in project_terms)


def apply_dimension_floors(
    scores: list[DimensionScore],
    floors: dict[str, float],
    reason: str,
) -> list[DimensionScore]:
    calibrated: list[DimensionScore] = []
    for item in scores:
        floor = floors.get(item.key, 0)
        if item.score >= floor:
            calibrated.append(item)
            continue
        calibrated.append(
            item.model_copy(
                update={
                    "score": floor,
                    "weighted_score": CFG.weighted_score(floor, item.max_points),
                    "rationale": f"{item.rationale} 组合证据校准：{reason}",
                }
            )
        )
    return calibrated
