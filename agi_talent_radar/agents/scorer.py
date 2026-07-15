"""Legacy v1 single-rubric scorer; the multi-track graph does not import this module."""

from __future__ import annotations

from pydantic import BaseModel, Field

from agi_talent_radar.core import llm_client
from agi_talent_radar.core.models import DimensionScore, EvidenceItem, NormalizedResume
from agi_talent_radar.core.rubric import (
    AUXILIARY_PROFILE_KEYS,
    BREAKTHROUGH_AXIS_KEYS,
    CALIBRATION_REFERENCE,
    CORE_POTENTIAL_KEYS,
    RUBRIC,
)


class ScoringOutput(BaseModel):
    overall_score: int = Field(ge=0, le=100)
    level: str
    tier: str
    dimension_scores: list[DimensionScore]

    @classmethod
    def model_validate(cls, obj, **kwargs):
        if isinstance(obj, dict):
            obj = dict(obj)
            obj["overall_score"] = int(round(float(obj.get("overall_score", 0))))
        return super().model_validate(obj, **kwargs)


SCORER_PROMPT = """
你是 AI 人才潜力初评系统里的【跨领域对齐打分 Agent】。
只输出 JSON 对象，字段必须是 overall_score, level, tier, dimension_scores。

评分目标：
识别长期培养价值，不是传统履历排序。不要直接按学校、GPA、论文名气给高分；教育背景只能使用 background_signal_tiers 的分级信号，不能猜测具体学校或精确成绩。

本任务的“真正高潜”定义：
- 不是简历最光鲜、论文标题最多、学校/GPA 最亮的人。
- 是能把问题定义、AI/Agent 工具杠杆、工程交付、验证闭环和 ownership 串起来的人。
- 用本批 10 个虚构候选人作为校准：更看好有可验证闭环的 Agent/工程/问题定义型候选人；谨慎看待只有方向/论文/泛化成果但缺少闭环与本人动作的人。

评分规则：
- 每个维度 score 为 1-5 分。
- weighted_score = score × weight × 20。
- overall_score = 所有维度 weighted_score 之和，四舍五入到整数；高分必须来自核心潜力维度，而不是履历辅助维度。
- 潜力维度（learning_growth, research_exploration, engineering_practice, ai_agent_leverage, problem_definition, ownership, cultivation_value）是核心，必须基于具体 evidence 判断，不能只看背景。
- 履历维度（education_signal, academic_output, project_richness, impact_visibility, direction_fit）只是辅助，不得把候选人推入优选。

1-5 分含义：
- 5：必须同时具备具体技术/工具、明确本人动作、量化或可验证结果、闭环验证，且体现独立定义/推进。
- 4：有具体技术和本人动作，并有局部指标或验证闭环，但贡献边界或复现细节仍需追问。
- 3：有项目事实和技术词，但偏执行/参与/方向描述，闭环、指标、ownership 至少缺一项。
- 2：证据薄弱，只有背景、论文题目、方向词或间接描述。
- 1：几乎无证据或明显不匹配。

硬性封顶：
- 没有 evidence 的维度最高 1.5。
- 核心潜力维度如果没有具体技术栈/工具，也没有量化或验证闭环，最高 3.0。
- ai_agent_leverage 如果没有 Agent/工具调用/自动验证/RAG/路由/代码执行/工作流证据，最高 2.0。
- ownership 如果没有负责/设计/提出/维护/一作/负责人等本人动作，最高 3.0。
- research_exploration 如果只有论文题目或拟投状态、没有方法机制/假设/消融/错误归因，最高 3.0。
- problem_definition 如果没有痛点、约束、baseline、失败模式、评价指标或取舍逻辑，最高 3.2。
- cultivation_value 不能作为兜底高分项；如果核心突破维度没有任何一个 >= 4.0，最高 3.2。
- 辅助履历维度最高 4.0，education_signal 最高 3.5。

总分校准：
- overall_score >= 80 必须至少有 3 个核心潜力维度 >= 4.0，且至少 1 个来自 engineering_practice / ai_agent_leverage / problem_definition / ownership。
- overall_score >= 85 必须至少有 4 个核心潜力维度 >= 4.0，且有明确量化或验证闭环。
- 如果 AI/Agent 杠杆、问题定义、ownership 三项都低于 3.5，即使论文/背景不错，总分通常不应超过 72。
- 如果维度分数过于集中（大多数在 3.5-4.2），必须根据证据硬度拉开差异，不能端水。

等级规则：
- S: overall_score >= 90
- A: 80 <= overall_score <= 89
- B: 60 <= overall_score <= 79
- C: overall_score < 60

分层规则：
- 强烈建议沟通：overall_score >= 80 且核心潜力维度有具体证据
- 建议沟通：60 <= overall_score <= 79，进入备选库
- 暂缓 / 需补充信息：overall_score < 60，进入不建议后续沟通

dimension_scores 每项必须包含：
key, label, score(1-5), weighted_score, rationale, evidence_ids, risk_notes。
- rationale 必须引用 evidence id，解释为什么是这个分数。
- risk_notes 必须是字符串列表，指出该维度的待验证点；如果没有风险，给空列表 []。
- 不要给所有维度相同分数，要根据 evidence 区分强弱。
""".strip()


def run_scorer(state: dict) -> dict:
    normalized = NormalizedResume.model_validate(state["normalized"])
    evidence = [EvidenceItem.model_validate(item) for item in state.get("evidence", [])]
    response = llm_client.call_llm_json(
        SCORER_PROMPT,
        {
            "rubric": [item.model_dump() for item in RUBRIC],
            "calibration_reference": CALIBRATION_REFERENCE,
            "resume_brief": normalized.model_dump(exclude={"raw_text", "education_raw", "experiences_raw"}),
            "evidence": [item.model_dump() for item in evidence],
            "critic_feedback": state.get("critic_flags", []),
            "rescore_instruction": "如果 critic_feedback 非空，请降低证据不足维度分数，并在 risk_notes 中解释。",
        },
        temperature=0.1,
    )
    _normalize_risk_notes(response.get("dimension_scores", []))
    scoring = ScoringOutput.model_validate(response)
    calibrated_scores, assessment = _calibrate_scoring(scoring.dimension_scores, evidence)
    return {
        **state,
        "scores": [item.model_dump() for item in calibrated_scores],
        "ai_assessment": {
            **state.get("ai_assessment", {}),
            **assessment,
        },
    }


def _normalize_risk_notes(scores: list[dict]) -> None:
    for item in scores:
        risk_notes = item.get("risk_notes", [])
        if isinstance(risk_notes, str):
            item["risk_notes"] = [risk_notes] if risk_notes.strip() else []
        elif not isinstance(risk_notes, list):
            item["risk_notes"] = []


def _calibrate_scoring(scores: list[DimensionScore], evidence: list[EvidenceItem]) -> tuple[list[DimensionScore], dict[str, str | int]]:
    rubric_by_key = {item.key: item for item in RUBRIC}
    evidence_by_id = {item.id: item for item in evidence}
    by_dimension = _evidence_by_dimension(evidence)
    calibrated: list[DimensionScore] = []

    for score in scores:
        rubric = rubric_by_key.get(score.key)
        if not rubric:
            calibrated.append(score)
            continue

        refs = [
            evidence_by_id[item_id]
            for item_id in score.evidence_ids
            if item_id in evidence_by_id and evidence_by_id[item_id].dimension == score.key
        ]
        if not refs:
            refs = by_dimension.get(score.key, [])
        if not refs and score.key in CORE_POTENTIAL_KEYS:
            refs = _transferable_core_refs(score.key, evidence)
        next_score = float(score.score)
        caps = _score_caps(score.key, refs, by_dimension)
        if caps:
            next_score = min(next_score, min(cap for cap, _ in caps))

        risk_notes = list(score.risk_notes)
        for cap, reason in caps:
            if score.score > cap and reason not in risk_notes:
                risk_notes.append(reason)

        next_score = max(1.0, min(5.0, round(next_score, 1)))
        calibrated.append(
            score.model_copy(
                update={
                    "score": next_score,
                    "weighted_score": round(next_score * rubric.weight * 20, 2),
                    "risk_notes": risk_notes,
                }
            )
        )

    overall = int(round(sum(item.weighted_score for item in calibrated)))
    overall = _calibrate_overall(overall, calibrated, evidence)
    return calibrated, {
        "overall_score": overall,
        "level": _level_for_score(overall),
        "tier": _tier_for_score(overall),
    }


def _score_caps(
    key: str,
    refs: list[EvidenceItem],
    by_dimension: dict[str, list[EvidenceItem]],
) -> list[tuple[float, str]]:
    caps: list[tuple[float, str]] = []
    if not refs:
        return [(1.5, "该维度缺少直接证据，按规则封顶。")]

    has_tool = any(item.has_specific_tool for item in refs)
    has_metric = any(item.has_metric for item in refs)
    has_ownership = any(item.has_ownership for item in refs)
    has_strong = any(item.strength >= 4 for item in refs)
    text = " ".join([item.quote + " " + " ".join(item.signals) for item in refs]).lower()
    has_agent_signal = _has_any(text, ["agent", "智能体", "路由", "routing", "rag", "代码解释器", "workflow", "工作流", "自动验证", "反思", "swe", "工具调用"])
    has_method_signal = _has_any(text, ["提出", "设计", "机制", "框架", "范式", "消融", "ablation", "错误归因", "baseline", "约束", "验证"])
    has_problem_signal = _has_any(text, ["针对", "问题", "约束", "baseline", "评测", "指标", "错误", "失败", "成本", "误报", "漏召", "长尾", "鲁棒", "闭环", "验证", "反思", "求解", "任务拆解", "设计"])
    has_closed_loop = has_metric or _has_any(text, ["闭环", "验证", "评测", "测试", "ablation", "复现", "patch", "一致性检查", "错误归因", "拦截", "修复"])

    if key in CORE_POTENTIAL_KEYS and not (has_tool or has_metric or has_closed_loop):
        caps.append((3.0, "核心潜力维度缺少具体工具、量化结果或验证闭环。"))
    if key == "ai_agent_leverage" and not has_agent_signal:
        caps.append((2.0, "缺少 Agent、工具调用、自动验证、RAG、路由或工作流证据。"))
    if key == "ownership" and not has_ownership:
        caps.append((3.0, "缺少负责、设计、提出、维护、一作或负责人等本人动作信号。"))
    if key == "research_exploration" and not (has_method_signal and has_strong):
        caps.append((3.2, "研究维度不能只依赖论文题目或方向，需要方法机制、假设、消融或错误归因。"))
    if key == "problem_definition" and not has_problem_signal:
        caps.append((3.2, "缺少痛点、约束、baseline、评价指标或取舍逻辑。"))
    if key == "cultivation_value":
        breakthrough_refs = [
            item
            for axis in BREAKTHROUGH_AXIS_KEYS
            for item in by_dimension.get(axis, [])
        ]
        if not any(item.strength >= 4 and (item.has_metric or item.has_ownership or item.has_specific_tool) for item in breakthrough_refs):
            caps.append((3.2, "长期培养价值必须由突破维度硬证据支撑，不能泛化兜底。"))
    if key in AUXILIARY_PROFILE_KEYS:
        caps.append((4.0, "履历辅助维度低权重封顶，不能替代潜力证据。"))
    if key == "education_signal":
        caps.append((3.5, "教育背景只能作为低权重分级信号。"))
    return caps


def _calibrate_overall(overall: int, scores: list[DimensionScore], evidence: list[EvidenceItem]) -> int:
    by_key = {item.key: item.score for item in scores}
    core_scores = [by_key.get(key, 0) for key in CORE_POTENTIAL_KEYS]
    breakthrough_scores = [by_key.get(key, 0) for key in BREAKTHROUGH_AXIS_KEYS]
    strong_core_count = sum(1 for score in core_scores if score >= 4.0)
    strong_breakthrough_count = sum(1 for score in breakthrough_scores if score >= 4.0)
    has_metric_or_loop = any(item.has_metric or "验证" in " ".join(item.signals) or "闭环" in item.quote for item in evidence)

    if strong_core_count < 3 or strong_breakthrough_count < 1:
        overall = min(overall, 79)
    if strong_core_count < 4 or not has_metric_or_loop:
        overall = min(overall, 84)
    if (
        by_key.get("ai_agent_leverage", 0) < 3.5
        and by_key.get("problem_definition", 0) < 3.5
        and by_key.get("ownership", 0) < 3.5
    ):
        overall = min(overall, 72)

    if _score_spread(scores) < 1.0 and strong_core_count < 4:
        overall = min(overall, 76)
    return max(0, min(100, overall))


def _evidence_by_dimension(evidence: list[EvidenceItem]) -> dict[str, list[EvidenceItem]]:
    result: dict[str, list[EvidenceItem]] = {}
    for item in evidence:
        result.setdefault(item.dimension, []).append(item)
    return result


def _transferable_core_refs(key: str, evidence: list[EvidenceItem]) -> list[EvidenceItem]:
    related: dict[str, set[str]] = {
        "learning_growth": {"problem_definition", "engineering_practice", "ai_agent_leverage", "ownership"},
        "research_exploration": {"problem_definition", "engineering_practice", "ownership"},
        "engineering_practice": {"ai_agent_leverage", "problem_definition", "ownership"},
        "ai_agent_leverage": {"engineering_practice", "problem_definition", "ownership"},
        "problem_definition": {"research_exploration", "engineering_practice", "ai_agent_leverage", "ownership"},
        "ownership": {"engineering_practice", "ai_agent_leverage", "problem_definition", "research_exploration"},
        "cultivation_value": BREAKTHROUGH_AXIS_KEYS,
    }
    candidates = [item for item in evidence if item.dimension in related.get(key, set()) and item.strength >= 4]
    return [
        item
        for item in candidates
        if item.has_metric or item.has_specific_tool or item.has_ownership or _has_any(item.quote.lower(), ["闭环", "验证", "评测", "复现", "修复"])
    ][:3]


def _score_spread(scores: list[DimensionScore]) -> float:
    values = [float(item.score) for item in scores]
    if not values:
        return 0
    return max(values) - min(values)


def _has_any(text: str, needles: list[str]) -> bool:
    return any(needle.lower() in text for needle in needles)


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
