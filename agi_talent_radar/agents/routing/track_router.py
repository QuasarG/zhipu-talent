from __future__ import annotations

from collections import defaultdict
from typing import Any

from agi_talent_radar.agents.tracks.registry import TRACK_SPECS
from agi_talent_radar.core import llm_client
from agi_talent_radar.core.models import EvidenceItem, NormalizedResume, TrackAssignment, TrackKey


TRACK_ROUTER_PROMPT = """
你是 AI 人才潜力评估系统里的【多 Track 路由 Agent】。
只输出 JSON 对象，顶层字段必须是 assignments。

任务：根据候选人实际工作分布，将其分配到 1-3 个 Track，并给出归一化权重。
可用 Track：base, agent, safety, multimodal, ai_infra, ai4science。

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
    normalized = NormalizedResume.model_validate(state["normalized"])
    evidence = [EvidenceItem.model_validate(item) for item in state.get("evidence", [])]
    response = llm_client.call_llm_json(
        TRACK_ROUTER_PROMPT,
        {
            "tracks": {key: spec.as_prompt_dict() for key, spec in TRACK_SPECS.items()},
            "resume": normalized.model_dump(exclude={"education_raw", "experiences_raw", "raw_text"}),
            "evidence": [item.model_dump() for item in evidence],
        },
        temperature=0.1,
    )
    assignments = _normalize_assignments(response.get("assignments", []), normalized, evidence)
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
) -> list[TrackAssignment]:
    merged: dict[TrackKey, dict[str, Any]] = {}
    valid_tracks = set(TRACK_SPECS)
    evidence_ids = {item.id for item in evidence}

    for raw in raw_assignments:
        track = str(raw.get("track", "")).strip().lower()
        if track not in valid_tracks:
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
        merged = _fallback_assignments(normalized, evidence)

    eligible = [
        item
        for item in merged.values()
        if _is_track_eligible(item["track"], item.get("evidence_ids", []), normalized, evidence)
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


def _is_track_eligible(
    track: TrackKey,
    evidence_ids: list[str],
    normalized: NormalizedResume,
    evidence: list[EvidenceItem],
) -> bool:
    selected_ids = set(evidence_ids)
    selected = [item for item in evidence if item.id in selected_ids] or evidence
    text = " ".join(
        [
            normalized.target_role,
            " ".join(normalized.directions),
            " ".join(normalized.skills),
            " ".join(f"{item.source} {item.quote} {' '.join(item.signals)}" for item in selected),
        ]
    ).lower()
    keywords: dict[TrackKey, tuple[str, ...]] = {
        "base": (
            "预训练", "后训练", "transformer", "attention", "moe", "rlhf", "sft",
            "语言模型", "基础模型", "长上下文", "tokenizer",
        ),
        "agent": (
            "agent", "智能体", "multi-agent", "planner", "tool", "memory", "harness",
            "workflow", "swe-bench", "fuzzing harness",
        ),
        "safety": (
            "安全", "攻击", "防御", "漏洞", "fuzz", "符号执行", "angr", "afl",
            "hook", "隐私", "威胁", "调试", "程序分析", "风险识别",
        ),
        "multimodal": (
            "多模态", "视觉", "vlm", "图像", "视频", "3d", "ocr", "clip", "跨模态",
        ),
        "ai_infra": (
            "训练系统", "推理系统", "大模型系统", "serving", "吞吐", "显存",
            "gpu", "cuda", "triton", "算子", "分布式训练", "并行训练", "低精度",
            "量化", "模型压缩", "ml编译器", "推理引擎", "vllm", "deepspeed",
        ),
        "ai4science": (
            "ai4science", "科学智能", "蛋白", "药物", "生物", "材料", "分子", "医学",
        ),
    }
    return any(keyword in text for keyword in keywords[track])


def _fallback_assignments(normalized: NormalizedResume, evidence: list[EvidenceItem]) -> dict[TrackKey, dict[str, Any]]:
    text = " ".join(
        [
            normalized.target_role,
            " ".join(normalized.directions),
            " ".join(normalized.skills),
            " ".join(item.quote for item in evidence),
        ]
    ).lower()
    keywords: dict[TrackKey, tuple[str, ...]] = {
        "base": ("预训练", "后训练", "微调", "rlhf", "attention", "transformer", "moe"),
        "agent": ("agent", "智能体", "工具调用", "workflow", "memory", "swe-bench"),
        "safety": ("安全", "攻击", "防御", "漏洞", "越狱", "隐私", "投毒"),
        "multimodal": ("多模态", "视觉", "vlm", "图像", "视频", "3d", "ocr"),
        "ai_infra": ("推理", "训练系统", "triton", "cuda", "显存", "吞吐", "编译器", "量化"),
        "ai4science": ("ai4science", "科学智能", "生物", "蛋白", "药物", "材料", "医学"),
    }
    scores: dict[TrackKey, int] = {track: sum(text.count(word) for word in words) for track, words in keywords.items()}
    if not any(scores.values()):
        scores["base"] = 1
    result: dict[TrackKey, dict[str, Any]] = {}
    for track, score in sorted(scores.items(), key=lambda item: item[1], reverse=True)[:3]:
        if score <= 0:
            continue
        result[track] = {
            "track": track,
            "weight": score,
            "confidence": 0.45,
            "rationale": "LLM 路由结果无效，使用关键词证据进行保守回退。",
            "evidence_ids": [item.id for item in evidence if any(word in item.quote.lower() for word in keywords[track])],
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
