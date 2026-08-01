"""RAG 切片器：从 MySQL 业务数据生成可向量化的文本块。

每个 chunk 必须能回链到 MySQL 原文（record_type + record_id）。
覆盖：评估摘要、评分证据、论文自述/核验、外部事实、简历画像、简历原文。
"""
from __future__ import annotations

import re
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
    ResumeSubmissionORM,
)
from agi_talent_radar.core.embedding import MAX_CHARS_PER_INPUT, truncate_input

# 简历原文切片参数：目标片长 / 相邻片重叠
RESUME_RAW_SLICE_CHARS = 800
RESUME_RAW_OVERLAP_CHARS = 100


@dataclass(frozen=True)
class KnowledgeChunk:
    """一个可向量化的文本块。"""

    text: str
    record_type: str       # evaluation / evidence / publication_claim / external_fact / resume_profile / resume_raw
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


def chunk_publication_claim(
    claim: PublicationClaimORM,
    evaluation: EvaluationORM | None = None,
) -> KnowledgeChunk:
    """论文自述切片。传入关联 evaluation 可补上 person_id / candidate_id。"""
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
        person_id=(evaluation.person_id or "") if evaluation else "",
        candidate_id=str(evaluation.candidate_id or "") if evaluation else "",
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


def _education_text(item) -> str:
    if isinstance(item, dict):
        return " ".join(
            str(item.get(key) or "")
            for key in ("school", "degree", "major", "period")
        ).strip()
    return str(item or "").strip()


def chunk_resume_profile(
    person: PersonORM,
    submission: ResumeSubmissionORM,
    candidate_id: str = "",
) -> KnowledgeChunk | None:
    """简历结构化画像切片：姓名/学校学历/实习组织岗位/技能/方向的紧凑摘要。"""
    structured = submission.structured or {}
    if not isinstance(structured, dict):
        return None
    education = "；".join(
        text for text in (_education_text(item) for item in structured.get("education") or []) if text
    )
    experiences = "；".join(
        " ".join(
            part
            for part in (
                str(exp.get("organization") or ""),
                str(exp.get("role") or ""),
                str(exp.get("period") or ""),
            )
            if part
        )
        for exp in structured.get("experiences") or []
        if isinstance(exp, dict)
    )
    parts = [
        f"姓名：{structured.get('name') or person.name}",
        f"机构：{person.org}",
        f"方向：{person.direction or '、'.join(structured.get('directions') or [])}",
        f"教育：{education}",
        f"实习/经历：{experiences}",
        f"技能：{'、'.join(str(s) for s in structured.get('skills') or [])}",
        f"目标岗位：{structured.get('target_role') or ''}",
    ]
    text = _make_text(parts)
    if not text.strip():
        return None
    return KnowledgeChunk(
        text=text,
        record_type="resume_profile",
        record_id=f"{person.id}:profile",
        person_id=person.id,
        candidate_id=candidate_id,
        fact_status="confirmed",
        source="resume",
        fetched_at=_iso(submission.updated_at or submission.created_at),
    )


def _slice_raw_text(
    text: str,
    size: int = RESUME_RAW_SLICE_CHARS,
    overlap: int = RESUME_RAW_OVERLAP_CHARS,
) -> list[str]:
    """把长文按 ~size 字切片，段落边界优先，相邻片重叠 ~overlap 字。"""
    paragraphs = [p.strip() for p in re.split(r"\n+", text) if p.strip()]
    slices: list[str] = []
    current = ""
    for para in paragraphs:
        candidate = f"{current}\n{para}" if current else para
        if current and len(candidate) > size:
            slices.append(current)
            current = (current[-overlap:] + "\n" + para) if overlap else para
        else:
            current = candidate
        # 单段远超片长时硬切，避免巨型 chunk
        while len(current) > size + overlap:
            slices.append(current[:size])
            current = current[size - overlap:]
    if current:
        slices.append(current)
    return [piece.strip() for piece in slices if piece.strip()]


def chunk_resume_raw(
    person: PersonORM,
    submission: ResumeSubmissionORM,
    candidate_id: str = "",
) -> list[KnowledgeChunk]:
    """简历原文切片：raw_text 按 ~800 字切，段落边界优先，相邻重叠 ~100 字。"""
    raw_text = (submission.raw_text or "").strip()
    if not raw_text:
        return []
    fetched_at = _iso(submission.updated_at or submission.created_at)
    return [
        KnowledgeChunk(
            text=truncate_input(piece)[:MAX_CHARS_PER_INPUT],
            record_type="resume_raw",
            record_id=f"{person.id}:raw:{index}",
            person_id=person.id,
            candidate_id=candidate_id,
            fact_status="claimed",
            source="resume",
            fetched_at=fetched_at,
        )
        for index, piece in enumerate(_slice_raw_text(raw_text))
    ]


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
            chunks.append(chunk_publication_claim(claim, evaluation))

    # 外部事实（当前版本，排除 superseded）
    facts = (
        session.query(ExternalFactORM)
        .filter_by(person_id=person_id)
        .filter(ExternalFactORM.superseded_at.is_(None))
        .all()
    )
    for fact in facts:
        chunks.append(chunk_external_fact(fact))

    # 简历画像 + 原文（取最新一次提交）
    submission = (
        session.query(ResumeSubmissionORM)
        .filter_by(person_id=person_id)
        .order_by(ResumeSubmissionORM.created_at.desc())
        .first()
    )
    if submission is not None:
        candidate = (
            session.query(CandidateORM).filter_by(person_id=person_id).first()
        )
        candidate_id = candidate.id if candidate else ""
        profile = chunk_resume_profile(person, submission, candidate_id)
        if profile:
            chunks.append(profile)
        chunks.extend(chunk_resume_raw(person, submission, candidate_id))

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
    "chunk_resume_profile",
    "chunk_resume_raw",
    "collect_chunks_for_person",
    "chunk_to_payload",
]