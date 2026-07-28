"""RAG 切片器：从 MySQL 业务数据生成可向量化的文本块。

每个 chunk 必须能回链到 MySQL 原文（record_type + record_id）。
首版覆盖：评估摘要、评分证据、论文自述/核验、外部事实。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable

from agi_talent_radar.core.db.orm import (
    CandidateORM,
    EvaluationORM,
    ExternalFactORM,
    PersonORM,
    PublicationClaimORM,
    PublicationVerificationORM,
)
from agi_talent_radar.core.embedding import MAX_CHARS_PER_INPUT, truncate_input


@dataclass(frozen=True)
class KnowledgeChunk:
    """一个可向量化的文本块。"""

    text: str
    record_type: str       # evaluation / evidence / publication_claim / external_fact
    record_id: str
    person_id: str
    candidate_id: str
    fact_status: str       # confirmed / pending / conflict / na
    source: str
    fetched_at: str        # ISO 字符串


def _iso(value) -> str:
    if isinstance(value, datetime):
        return value.replace(tzinfo=None).isoformat()
    if isinstance(value, str):
        return value
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat()


def _make_text(parts: Iterable[str]) -> str:
    return truncate_input(" ".join(p for p in parts if p))[:MAX_CHARS_PER_INPUT]


def chunk_evaluation_summary(
    evaluation: EvaluationORM,
    person: PersonORM | None,
    candidate: CandidateORM | None,
) -> KnowledgeChunk | None:
    """评估摘要切片。"""
    parts = [
        f"姓名：{person.name if person else (candidate.name if candidate else '')}",
        f"机构：{person.org if person else ''}",
        f"方向：{person.direction if person else ''}",
        f"总分：{evaluation.overall_score}",
        f"阶段画像：{evaluation.stage_profile}",
        f"一句话：{evaluation.one_liner}",
        f"核心优势：{', '.join(evaluation.core_strengths or [])}",
        f"潜在风险：{', '.join(evaluation.potential_risks or [])}",
        f"推荐 Track：{', '.join((t.get('track', '') if isinstance(t, dict) else str(t)) for t in (evaluation.recommended_tracks or []))}",
    ]
    return KnowledgeChunk(
        text=_make_text(parts),
        record_type="evaluation",
        record_id=str(evaluation.id),
        person_id=evaluation.person_id or (person.id if person else ""),
        candidate_id=str(evaluation.candidate_id or (candidate.id if candidate else "")),
        fact_status="confirmed",
        source="talent_pool",
        fetched_at=_iso(evaluation.completed_at or evaluation.created_at),
    )


def chunk_evidence(evaluation: EvaluationORM, evidence_item) -> KnowledgeChunk:
    """单条评分证据切片。"""
    return KnowledgeChunk(
        text=_make_text([
            f"评估 {evaluation.id} 证据",
            f"维度：{getattr(evidence_item, 'dimension', '')}",
            f"原文：{getattr(evidence_item, 'quote', '')}",
            f"信号：{', '.join(getattr(evidence_item, 'signals', []) or [])}",
        ]),
        record_type="evidence",
        record_id=str(getattr(evidence_item, 'id', '')),
        person_id=evaluation.person_id or "",
        candidate_id=str(evaluation.candidate_id or ""),
        fact_status="confirmed",
        source="talent_pool",
        fetched_at=_iso(evaluation.created_at),
    )


def chunk_publication_claim(claim: PublicationClaimORM) -> KnowledgeChunk:
    return KnowledgeChunk(
        text=_make_text([
            f"论文自述：{claim.title}",
            f"venue：{claim.venue}",
            f"年份：{claim.year}",
            f"作者角色：{claim.claimed_role}",
            f"自述状态：{claim.claimed_status}",
            f"原文：{claim.source_quote}",
        ]),
        record_type="publication_claim",
        record_id=str(claim.id),
        person_id="",  # claim 不直接挂 person，靠 evaluation 间接
        candidate_id="",
        fact_status="claimed",  # 自述，非外部事实
        source="resume",
        fetched_at=_iso(claim.created_at),
    )


def chunk_external_fact(fact: ExternalFactORM) -> KnowledgeChunk:
    return KnowledgeChunk(
        text=_make_text([
            f"外部事实（{fact.fact_type}）：{(fact.payload or {}).get('title', '')}",
            f"来源：{fact.source}",
            f"内容：{repr(fact.payload)[:500]}",
        ]),
        record_type="external_fact",
        record_id=str(fact.id),
        person_id=fact.person_id,
        candidate_id="",
        fact_status=str(fact.verification_status or "pending"),
        source=str(fact.source),
        fetched_at=_iso(fact.fetched_at),
    )


def collect_chunks_for_person(
    session,
    person_id: str,
) -> list[KnowledgeChunk]:
    """从 MySQL 收集某 person 的全部可向量化 chunk。"""
    person = session.get(PersonORM, person_id)
    if person is None:
        return []

    chunks: list[KnowledgeChunk] = []
    evaluations = (
        session.query(EvaluationORM)
        .filter_by(person_id=person_id, status="completed")
        .all()
    )
    for evaluation in evaluations:
        candidate = (
            session.get(CandidateORM, evaluation.candidate_id)
            if evaluation.candidate_id
            else None
        )
        summary = chunk_evaluation_summary(evaluation, person, candidate)
        if summary:
            chunks.append(summary)
        for evidence in evaluation.evidence_items:
            chunks.append(chunk_evidence(evaluation, evidence))
        # 论文自述
        claims = (
            session.query(PublicationClaimORM)
            .filter_by(evaluation_id=evaluation.id)
            .all()
        )
        for claim in claims:
            chunks.append(chunk_publication_claim(claim))

    # 外部事实（当前版本，排除 superseded）
    facts = (
        session.query(ExternalFactORM)
        .filter_by(person_id=person_id)
        .filter(ExternalFactORM.superseded_at.is_(None))
        .all()
    )
    for fact in facts:
        chunks.append(chunk_external_fact(fact))

    return chunks


def chunk_to_payload(chunk: KnowledgeChunk, index_version: str) -> dict[str, Any]:
    """把 chunk 转成 Qdrant payload（包含全部必需字段）。"""
    return {
        "person_id": chunk.person_id,
        "candidate_id": chunk.candidate_id,
        "record_type": chunk.record_type,
        "record_id": chunk.record_id,
        "fact_status": chunk.fact_status,
        "source": chunk.source,
        "fetched_at": chunk.fetched_at,
        "index_version": index_version,
        "text": chunk.text,
    }


__all__ = [
    "KnowledgeChunk",
    "chunk_evaluation_summary",
    "chunk_evidence",
    "chunk_publication_claim",
    "chunk_external_fact",
    "collect_chunks_for_person",
    "chunk_to_payload",
]