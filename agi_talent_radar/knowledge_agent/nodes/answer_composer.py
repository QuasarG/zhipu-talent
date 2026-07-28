"""回答组装节点：生成结论 + 警告 + 引用。

引用必须携带来源、获取时间和核验状态。
待核验事实只能以"尚未人工确认"措辞引用；
冲突事实必须同时展示不同来源，AI 不得擅自选择真相。
"""
from __future__ import annotations

from typing import Any

from agi_talent_radar.knowledge_agent.models import (
    Citation,
    FactVerification,
    KnowledgeState,
)


def build_citations(facts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    citations: list[dict[str, Any]] = []
    for fact in facts:
        status = str(fact.get("verification_status", "pending"))
        citations.append(
            Citation(
                source=str(fact.get("source", "")),
                source_url=str(fact.get("source_url", "")),
                fetched_at=_coerce_dt(fact.get("fetched_at")),
                verification_status=FactVerification(status)
                if status in {item.value for item in FactVerification}
                else FactVerification.PENDING,
                quote=str(fact.get("title", "")),
            ).model_dump()
        )
    return citations


def _coerce_dt(value: Any):
    from datetime import datetime

    if isinstance(value, datetime):
        return value
    if isinstance(value, str) and value:
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return datetime.utcnow()
    from datetime import datetime

    return datetime.utcnow()


def compose_answer(
    normalized_facts: list[dict[str, Any]],
    failed_tools: list[str],
    needs_clarification: bool,
    clarification_message: str,
    pending_count: int,
) -> dict[str, Any]:
    if needs_clarification:
        return {
            "answer": clarification_message or "请补充可识别的具体人物信息。",
            "citations": [],
            "warnings": [],
        }

    lines: list[str] = []
    by_status: dict[str, int] = {}
    for fact in normalized_facts:
        status = str(fact.get("verification_status", "pending"))
        by_status[status] = by_status.get(status, 0) + 1
        title = fact.get("title") or fact.get("fact_type", "")
        prefix = ""
        if status == FactVerification.PENDING.value:
            prefix = "[尚未人工确认] "
        elif status == FactVerification.CONFLICT.value:
            prefix = "[冲突，请人工确认] "
        elif status == FactVerification.CONFIRMED.value:
            prefix = ""
        lines.append(f"- {prefix}{fact.get('source', '')}：{title}")

    answer = "已汇总如下事实（按来源与核验状态标注）：\n" + "\n".join(lines) if lines else "暂无可引用的事实。"

    warnings: list[str] = []
    if failed_tools:
        warnings.append(
            f"部分外部链路失败：{', '.join(failed_tools)}；其余结果已正常返回。"
        )
    if pending_count:
        warnings.append(
            f"本次新写入 {pending_count} 条待核验外部事实；"
            "需人工确认后才会升级为可信档案事实。"
        )
    if by_status.get(FactVerification.CONFLICT.value):
        warnings.append("检测到冲突事实，已同时保留不同来源；请人工确认。")

    return {
        "answer": answer,
        "citations": build_citations(normalized_facts),
        "warnings": warnings,
    }


def answer_composer(state: KnowledgeState) -> dict[str, Any]:
    """LangGraph 节点：组装回答。"""
    return compose_answer(
        normalized_facts=state.get("normalized_facts") or [],
        failed_tools=state.get("failed_tools") or [],
        needs_clarification=bool(state.get("needs_clarification", False)),
        clarification_message=state.get("clarification_message", ""),
        pending_count=int(state.get("pending_fact_count") or 0),
    )