from __future__ import annotations

from collections import defaultdict
from typing import Any

from agi_talent_radar.agents.tracks.registry import load_active_specs
from agi_talent_radar.agents.tracks.shared.spec import TrackSpec
from agi_talent_radar.core import llm_client
from agi_talent_radar.core.models import EvidenceItem, NormalizedResume, TrackAssignment, TrackKey


TRACK_ROUTER_PROMPT = """
你是 AI 人才潜力评估系统里的【多 Track 路由 Agent】。
只输出 JSON 对象，顶层字段必须是 assignments。

任务：根据候选人实际工作分布，将其分配到 1-3 个 Track，并给出归一化权重。
可用 Track 由输入的 tracks 字段给出（key 必须原样引用，不得编造）。

权重判断依据：
- 45% 项目、实习/工作内容与投入时间占比。
- 25% 论文、系统、数据集等成果占比。
- 20% 本人实质负责内容占比。
- 10% 当前及未来研究意向。

规则：
1. 权重代表候选人在做什么，不代表能力强弱。
2. 技能列表或一句“熟悉”不能单独触发 Track。
3. 第二 Track 必须有至少两条独立证据；最多三个 Track。
4. assignments 的 weight 之和必须为 1。
5. 每项输出 track, weight, confidence, rationale, evidence_ids。
6. 实习/工作经历只按脱敏后的技术动作、产物和结果路由；机构档位和岗位名不得影响 Track 权重或置信度。
""".strip()


def run_track_router(state: dict[str, Any]) -> dict[str, Any]:
    specs = load_active_specs()
    normalized = NormalizedResume.model_validate(state["normalized"])
    evidence = [EvidenceItem.model_validate(item) for item in state.get("evidence", [])]
    if not specs:
        # JD 池为空：无 track 可路由，聚合层按纯通用分汇总
        return {"track_assignments": [], "routing_confidence": 0.0, "evidence": [item.model_dump() for item in evidence]}
    response = llm_client.call_llm_json(
        TRACK_ROUTER_PROMPT,
        {
            "tracks": {key: spec.as_prompt_dict() for key, spec in specs.items()},
            "resume": normalized.model_dump(exclude={"education_raw", "experiences_raw", "raw_text"}),
            "evidence": [item.model_dump() for item in evidence],
        },
        temperature=0.1,
    )
    assignments = _normalize_assignments(response.get("assignments", []), normalized, evidence, specs)
    enriched_evidence = _attach_track_hints(evidence, assignments)
    confidence = sum(item.weight * item.confidence for item in assignments)
    return {
        "track_assignments": [item.model_dump() for item in assignments],
        "routing_confidence": round(confidence, 3),
        "evidence": [item.model_dump() for item in enriched_evidence],
    }


def _normalize_assignments(
    raw_assignments: list[dict[str, Any]],
    normalized: NormalizedResume,
    evidence: list[EvidenceItem],
    specs: dict[TrackKey, TrackSpec] | None = None,
) -> list[TrackAssignment]:
    specs = specs if specs is not None else load_active_specs()
    merged: dict[TrackKey, dict[str, Any]] = {}
    evidence_ids = {item.id for item in evidence}

    for raw in raw_assignments:
        track = str(raw.get("track", "")).strip().lower()
        if track not in specs:
            continue
        weight = max(0.0, float(raw.get("weight", 0)))
        if weight <= 0:
            continue
        refs = [str(item) for item in raw.get("evidence_ids", []) if str(item) in evidence_ids]
        merged[track] = {
            "track": track,
            "weight": merged.get(track, {}).get("weight", 0) + weight,
            "confidence": max(float(raw.get("confidence", 0)), merged.get(track, {}).get("confidence", 0)),
            "rationale": str(raw.get("rationale", "")),
            "evidence_ids": list(dict.fromkeys(merged.get(track, {}).get("evidence_ids", []) + refs)),
        }

    if not merged:
        merged = _fallback_assignments(normalized, evidence, specs)

    eligible = [
        item
        for item in merged.values()
        if _is_track_eligible(item["track"], item.get("evidence_ids", []), normalized, evidence, specs)
    ]
    pool = eligible or list(merged.values())
    ranked = sorted(pool, key=lambda item: float(item["weight"]), reverse=True)[:3]
    if len(ranked) > 1:
        # 第二、三 Track 必须有至少两条独立证据，否则是路由噪声，砍掉并把权重还给主 Track
        primary, *secondary = ranked
        secondary = [item for item in secondary if len(item.get("evidence_ids", [])) >= 2]
        ranked = [primary, *secondary]
    total = sum(float(item["weight"]) for item in ranked) or 1
    return [
        TrackAssignment(
            track=item["track"],
            weight=round(float(item["weight"]) / total, 4),
            confidence=max(0.0, min(1.0, float(item.get("confidence", 0.5)))),
            rationale=str(item.get("rationale", "")),
            evidence_ids=item.get("evidence_ids", []),
        )
        for item in ranked
    ]


def _resume_text(normalized: NormalizedResume, selected: list[EvidenceItem]) -> str:
    return " ".join(
        [
            normalized.target_role,
            " ".join(normalized.directions),
            " ".join(normalized.skills),
            " ".join(f"{item.source} {item.quote} {' '.join(item.signals)}" for item in selected),
        ]
    ).lower()


def _is_track_eligible(
    track: TrackKey,
    evidence_ids: list[str],
    normalized: NormalizedResume,
    evidence: list[EvidenceItem],
    specs: dict[TrackKey, TrackSpec],
) -> bool:
    """资格校验：spec 自带 keywords（LLM 起草时生成）命中即合格。"""
    spec = specs.get(track)
    if spec is None or not spec.keywords:
        return True  # 无关键词时不设卡，信任 LLM 路由
    selected_ids = set(evidence_ids)
    selected = [item for item in evidence if item.id in selected_ids] or evidence
    text = _resume_text(normalized, selected)
    return any(keyword.lower() in text for keyword in spec.keywords)


def _fallback_assignments(
    normalized: NormalizedResume,
    evidence: list[EvidenceItem],
    specs: dict[TrackKey, TrackSpec],
) -> dict[TrackKey, dict[str, Any]]:
    """LLM 路由失效时的保守回退：按各 spec keywords 在简历文本中的命中数排序。"""
    text = _resume_text(normalized, evidence)
    scores: dict[TrackKey, int] = {
        track: sum(text.count(word.lower()) for word in spec.keywords)
        for track, spec in specs.items()
    }
    if not any(scores.values()):
        # 一个关键词都没命中：兜底给第一个 active track，保证链路有输出
        scores[next(iter(specs))] = 1
    result: dict[TrackKey, dict[str, Any]] = {}
    for track, score in sorted(scores.items(), key=lambda item: item[1], reverse=True)[:3]:
        if score <= 0:
            continue
        keywords = tuple(word.lower() for word in specs[track].keywords)
        result[track] = {
            "track": track,
            "weight": score,
            "confidence": 0.45,
            "rationale": "LLM 路由结果无效，使用关键词证据进行保守回退。",
            "evidence_ids": [item.id for item in evidence if any(word in item.quote.lower() for word in keywords)],
        }
    return result


def _attach_track_hints(
    evidence: list[EvidenceItem],
    assignments: list[TrackAssignment],
) -> list[EvidenceItem]:
    hints: dict[str, list[TrackKey]] = defaultdict(list)
    for assignment in assignments:
        for evidence_id in assignment.evidence_ids:
            hints[evidence_id].append(assignment.track)
    return [item.model_copy(update={"track_hints": list(dict.fromkeys(item.track_hints + hints[item.id]))}) for item in evidence]
