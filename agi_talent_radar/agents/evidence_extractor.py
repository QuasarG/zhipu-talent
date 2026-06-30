from __future__ import annotations

import re
from collections import defaultdict

from agi_talent_radar.core.models import EvidenceItem, NormalizedResume
from agi_talent_radar.core.rubric import (
    ACTION_TERMS,
    DIMENSION_KEYWORDS,
    METRIC_MARKERS,
    OWNERSHIP_MARKERS,
    TECH_STACK_TERMS,
)


def run_evidence_extractor(state: dict) -> dict:
    normalized = NormalizedResume.model_validate(state["normalized"])
    evidence: list[EvidenceItem] = []
    evidence_index = 1

    for source, quote in _iter_resume_claims(normalized):
        matched_dimensions = _match_dimensions(quote)
        if not matched_dimensions:
            continue
        signals = _collect_signals(quote)
        has_metric = _has_any(quote, METRIC_MARKERS) or bool(re.search(r"\d+(?:\.\d+)?\s*(?:%|倍|K|\+)", quote))
        has_specific_tool = _has_any(quote, TECH_STACK_TERMS)
        has_ownership = _has_any(quote, OWNERSHIP_MARKERS)
        for dimension in matched_dimensions[:3]:
            evidence.append(
                EvidenceItem(
                    id=f"e{evidence_index:03d}",
                    dimension=dimension,
                    source=source,
                    quote=quote,
                    signals=signals,
                    strength=_strength(quote, dimension, has_metric, has_specific_tool, has_ownership),
                    has_metric=has_metric,
                    has_specific_tool=has_specific_tool,
                    has_ownership=has_ownership,
                )
            )
            evidence_index += 1

    evidence = _deduplicate_and_balance(evidence)
    return {**state, "evidence": [item.model_dump() for item in evidence]}


def _iter_resume_claims(normalized: NormalizedResume) -> list[tuple[str, str]]:
    claims: list[tuple[str, str]] = []
    for project in normalized.projects:
        if project.name:
            claims.append((f"项目：{project.name}", project.name))
        for detail in project.details:
            claims.append((f"项目：{project.name}", detail))
    for publication in normalized.publications:
        claims.append(("代表成果", publication))
    if normalized.skills:
        claims.append(("技能关键词", "、".join(normalized.skills)))
    if normalized.directions:
        claims.append(("研究方向", "、".join(normalized.directions)))
    return [(source, quote.strip()) for source, quote in claims if quote.strip()]


def _match_dimensions(text: str) -> list[str]:
    scores: dict[str, int] = defaultdict(int)
    for dimension, keywords in DIMENSION_KEYWORDS.items():
        for keyword in sorted(keywords, key=lambda term: (-len(term), term)):
            if keyword.lower() in text.lower():
                scores[dimension] += 1
    if _has_any(text, TECH_STACK_TERMS):
        scores["engineering_practice"] += 1
    if "Agent" in text or "智能体" in text:
        scores["ai_agent_leverage"] += 2
    if _has_any(text, METRIC_MARKERS):
        scores["problem_definition"] += 1
    if _has_any(text, OWNERSHIP_MARKERS):
        scores["ownership"] += 1
    ordered = sorted(scores.items(), key=lambda item: (-item[1], item[0]))
    return [dimension for dimension, score in ordered if score > 0]


def _collect_signals(text: str) -> list[str]:
    signals: list[str] = []
    for term in sorted(TECH_STACK_TERMS, key=lambda one: (-len(one), one)):
        if term.lower() in text.lower():
            signals.append(f"技术栈:{term}")
    for term in sorted(ACTION_TERMS, key=lambda one: (-len(one), one)):
        if term in text:
            signals.append(f"动作:{term}")
    if _has_any(text, METRIC_MARKERS) or re.search(r"\d+(?:\.\d+)?\s*(?:%|倍|K|\+)", text):
        signals.append("量化结果")
    if _has_any(text, OWNERSHIP_MARKERS):
        signals.append("Ownership")
    return list(dict.fromkeys(signals))[:8]


def _strength(text: str, dimension: str, has_metric: bool, has_specific_tool: bool, has_ownership: bool) -> int:
    score = 2
    if has_metric:
        score += 1
    if has_specific_tool:
        score += 1
    if has_ownership:
        score += 1
    if "闭环" in text or "验证" in text or "评测" in text:
        score += 1
    if dimension == "cultivation_value" and ("平台" in text or "系统" in text or "开源" in text):
        score += 1
    return max(1, min(5, score))


def _deduplicate_and_balance(evidence: list[EvidenceItem]) -> list[EvidenceItem]:
    seen: set[tuple[str, str]] = set()
    balanced: list[EvidenceItem] = []
    per_dimension: dict[str, int] = defaultdict(int)
    for item in sorted(evidence, key=lambda one: (-one.strength, one.dimension, one.id)):
        key = (item.dimension, item.quote)
        if key in seen:
            continue
        if per_dimension[item.dimension] >= 8:
            continue
        seen.add(key)
        per_dimension[item.dimension] += 1
        balanced.append(item)
    balanced.sort(key=lambda one: one.id)
    return balanced


def _has_any(text: str, terms: set[str]) -> bool:
    lowered = text.lower()
    return any(term.lower() in lowered for term in terms)
