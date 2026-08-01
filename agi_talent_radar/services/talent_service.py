"""候选人才库事务高层接口。

本轮（阶段 1）实装：

- ``admit_candidate_after_evaluation``  评估成功后关联 / 创建 Candidate，写
  ``resume_evaluation`` 来源；评估失败或未完成时不入库。
- ``manual_admit_person_to_pool``       HR 显式把已知人物主档加入人才库；写
  ``person_investigation`` 来源。
- ``update_engagement_status``          写 HR 跟进状态 + 不可变审计；强制
  ``changed_by``，拒绝自动入参。
- ``get_research_group_matching``       未配置研究组要求时永远返回
  ``not_configured``。

仍 raise ``NotImplementedError`` 等后续阶段实装：

- ``evaluate_resume`` / ``retry_publication_verification``（阶段 3/4）
- ``record_track_recommendation``（阶段 4）
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

from agi_talent_radar.core.db import repository
from agi_talent_radar.core.db.orm import (
    CANDIDATE_SOURCE_KINDS,
    CandidateORM,
    EvaluationORM,
    PersonORM,
)
from agi_talent_radar.core.domain_models import (
    EngagementStatus,
    EngagementStatusChange,
    ExternalFactVerification,
    PublicationVerificationStatus,
    ResearchGroupMatching,
    ResearchGroupMatchingStatus,
    TrackRecommendation,
)


def evaluate_resume(submission_id: str) -> dict[str, Any]:
    """驱动一次简历评估。返回评估摘要（不含 HR 状态、不含录取等级）。

    阶段 4 编排实装：

    1. 从 ``submission_id``（兼容期复用 candidate_id）加载 CandidateORM。
    2. 调老 ``run_candidate`` 跑 LangGraph（身份归并节点阶段 2 已留接口，
       但老 graph 暂未串入；这里先跑现有评估链路）。
    3. ``save_evaluation`` 写 EvaluationORM（内部已写 person_id）。
    4. ``admit_candidate_after_evaluation`` 入库 + 追加 resume_evaluation 来源。
    5. 派发论文核验 task（pending）。

    评估成功且需要入库时，必须经 ``admit_candidate_after_evaluation``，
    不允许直接修改 ``CandidateORM.group``。
    """
    from agi_talent_radar.core.database import get_session, save_evaluation, start_evaluation_run
    from agi_talent_radar.core.db.orm import CandidateORM
    from agi_talent_radar.core.runner import run_candidate

    with get_session() as session:
        candidate = session.get(CandidateORM, submission_id)
        if candidate is None:
            raise ValueError(f"候选人 / 简历提交不存在: {submission_id}")
        resume = _candidate_orm_to_resume(candidate)
        evaluation_run = start_evaluation_run(session, submission_id)
        evaluation_run_id = evaluation_run.id

    # 跑评估 graph（同步）；失败由上层捕获并 fail_evaluation_run
    evaluation = run_candidate(resume)
    evaluation.id = submission_id

    with get_session() as session:
        save_evaluation(session, evaluation, evaluation_id=evaluation_run_id)

    # 入库（admit 内部会校验 status=completed + person_id）
    admit_result = admit_candidate_after_evaluation(evaluation_run_id)

    # 派发论文核验 task（不阻塞主流程）
    try:
        retry_publication_verification(evaluation_run_id)
    except Exception:
        pass

    return {
        "evaluation_id": evaluation_run_id,
        "overall_score": evaluation.overall_score,
        "admit": admit_result,
    }


def _candidate_orm_to_resume(candidate) -> "CandidateResume":
    """从 CandidateORM 重建 CandidateResume（兼容老字段）。"""
    import json as _json

    from agi_talent_radar.core.models import CandidateResume

    def _loads(value):
        if isinstance(value, (list, dict)):
            return value
        if isinstance(value, str) and value:
            try:
                return _json.loads(value)
            except _json.JSONDecodeError:
                return []
        return []

    return CandidateResume.model_validate({
        "id": candidate.id,
        "name": candidate.name,
        "target_role": candidate.target_role,
        "stage": candidate.stage,
        "raw_text": candidate.raw_text,
        "education": _loads(candidate.education),
        "directions": _loads(candidate.directions),
        "experiences": _loads(getattr(candidate, "experiences", "")),
        "projects": _loads(candidate.projects),
        "publications": _loads(candidate.publications),
        "skills": _loads(candidate.skills),
        "screening_tags": _loads(candidate.screening_tags),
        "source_format": getattr(candidate, "source_format", "text") or "text",
        "document_analysis": _loads(getattr(candidate, "document_analysis", "")) or {},
    })


def retry_publication_verification(
    evaluation_id: int,
    paper_claim_ids: list[str] | None = None,
) -> dict[str, Any]:
    """仅重试外部论文核验任务，不重跑整份简历评估。

    返回新建 ``TaskORM.id`` 与 payload；实际外部核验由后台 worker 执行。
    """
    from agi_talent_radar.core.database import get_session

    with get_session() as session:
        evaluation = session.get(EvaluationORM, evaluation_id)
        if evaluation is None:
            raise ValueError(f"评估运行不存在: {evaluation_id}")
        task = repository.create_publication_verification_task(
            session,
            evaluation_id=evaluation_id,
            claim_ids=[int(cid) for cid in (paper_claim_ids or [])] or None,
        )
        return {
            "task_id": task.id,
            "task_type": task.task_type,
            "status": task.status,
            "payload": task.payload,
        }


def admit_candidate_after_evaluation(evaluation_id: int) -> dict[str, Any]:
    """评估成功后将候选人关联或创建到人才库。

    事务语义：

    1. 加载 ``EvaluationORM``；状态非 ``completed`` 时拒绝入库。
    2. 加载 ``EvaluationORM.person_id``；缺失时拒绝入库（阶段 2 之前先 fail-fast）。
    3. 通过 ``find_or_create_candidate_for_person`` 按 person 归并 Candidate。
    4. ``append_candidate_source('resume_evaluation')`` 幂等追加来源。
    5. 不写 ``CandidateORM.group``——让前端默认展示，由手动接口调整。

    返回 ``{candidate_id, person_id, sources}`` 用于上层记录。
    """
    from agi_talent_radar.core.database import get_session

    with get_session() as session:
        evaluation = session.get(EvaluationORM, evaluation_id)
        if evaluation is None:
            raise ValueError(f"评估运行不存在: {evaluation_id}")
        if (evaluation.status or "").lower() != "completed":
            raise ValueError("评估未完成，不允许入库人才库。")
        person_id = evaluation.person_id
        if not person_id:
            raise ValueError("评估缺少 person_id，请先执行入库身份归并。")

        candidate_name = ""
        candidate_role = ""
        candidate_stage = ""
        if evaluation.candidate:
            candidate_name = evaluation.candidate.name or ""
            candidate_role = evaluation.candidate.target_role or ""
            candidate_stage = evaluation.candidate.stage or ""

        submission_candidate = evaluation.candidate
        candidate = repository.find_candidate_by_person(session, person_id)
        if candidate is None:
            if submission_candidate is not None:
                candidate = submission_candidate
                candidate.person_id = person_id
                candidate.admitted_at = candidate.admitted_at or datetime.now(timezone.utc).replace(tzinfo=None)
                session.flush()
            else:
                candidate = repository.find_or_create_candidate_for_person(
                    session,
                    person_id=person_id,
                    name=candidate_name,
                    target_role=candidate_role,
                    stage=candidate_stage,
                )
        elif submission_candidate is not None and submission_candidate.id != candidate.id:
            _merge_submission_profile(candidate, submission_candidate)
            submission_candidate.group = "dismissed"

        if evaluation.candidate_id != candidate.id:
            evaluation.candidate_id = candidate.id

        repository.append_candidate_source(
            session,
            candidate_id=candidate.id,
            source_kind="resume_evaluation",
            source_record_id=str(evaluation.id),
            created_by="system:resume_evaluation",
        )
        sources = repository.list_candidate_source_kinds(session, candidate.id)

        # 阶段 7：入库成功后派发向量同步 outbox task（不阻塞主流程）。
        try:
            from agi_talent_radar.knowledge_agent.vector_sync import enqueue_vector_sync_task

            enqueue_vector_sync_task(session, person_id, action="upsert")
        except Exception:
            # outbox 失败不应让 admit 回滚；可由运维重试。
            pass

        # outbox 暂无独立消费者：就地 best-effort 同步一次，失败静默降级（任务仍在队列可重试）。
        try:
            from agi_talent_radar.core.vector_store import QdrantVectorStore
            from agi_talent_radar.knowledge_agent.vector_sync import sync_person_vectors

            sync_person_vectors(session, person_id, QdrantVectorStore())
        except Exception:
            logger.warning("person %s 向量同步失败，等待后续重试", person_id, exc_info=True)

        return {
            "candidate_id": candidate.id,
            "person_id": person_id,
            "sources": sources,
        }


def _merge_submission_profile(target: CandidateORM, source: CandidateORM) -> None:
    """把新版简历字段合入人物主档，保留主档身份与 HR 状态。"""
    profile_fields = (
        "name",
        "target_role",
        "stage",
        "raw_text",
        "education",
        "directions",
        "experiences",
        "projects",
        "publications",
        "skills",
        "screening_tags",
        "source_format",
        "document_analysis",
        "import_level",
        "import_category",
        "import_confidence",
        "academic_report",
        "academic_check_status",
        "academic_check_at",
        "current_resume_version_id",
    )
    for field in profile_fields:
        value = getattr(source, field, None)
        if value not in (None, "", [], {}):
            setattr(target, field, value)


def manual_admit_person_to_pool(
    person_id: str,
    changed_by: str,
    note: str,
) -> dict[str, Any]:
    """HR 显式把已知人物主档加入人才库。

    - ``changed_by`` 强制要求。
    - 同一 ``person_id`` 至多拥有一个 Candidate；重复调用幂等。
    - 写入 ``person_investigation`` 来源，与 ``resume_evaluation`` 并存。
    """
    if not changed_by or not changed_by.strip():
        raise ValueError("changed_by 必填，HR 显式操作不能自动触发。")
    if "person_investigation" not in CANDIDATE_SOURCE_KINDS:
        raise RuntimeError("CANDIDATE_SOURCE_KINDS 配置异常，缺 person_investigation。")

    from agi_talent_radar.core.database import get_session

    with get_session() as session:
        person = session.get(PersonORM, person_id)
        if person is None:
            raise ValueError(f"人物主档不存在: {person_id}")
        candidate = repository.find_candidate_by_person(session, person_id)
        if candidate is None:
            candidate = repository.find_or_create_candidate_for_person(
                session,
                person_id=person_id,
                name=person.name,
                target_role="",
                stage="",
            )
        repository.append_candidate_source(
            session,
            candidate_id=candidate.id,
            source_kind="person_investigation",
            source_record_id=person_id,
            note=note or "",
            created_by=changed_by,
        )
        sources = repository.list_candidate_source_kinds(session, candidate.id)
        return {
            "candidate_id": candidate.id,
            "person_id": person_id,
            "sources": sources,
        }


def update_engagement_status(
    candidate_id: str,
    status: EngagementStatus | str,
    changed_by: str,
    note: str,
) -> EngagementStatusChange:
    """人工修改 HR 跟进状态，强制要求 ``changed_by`` 与 ``note``。

    ``status`` 接受 ``EngagementStatus`` 枚举或字符串；
    不合法字符串或未注册的枚举值会抛 ``ValueError``。
    系统不得基于分数、舆情或其他自动规则切换。
    """
    if isinstance(status, EngagementStatus):
        normalized = status
    else:
        try:
            normalized = EngagementStatus(status)
        except ValueError as exc:
            allowed = sorted(member.value for member in EngagementStatus)
            raise ValueError(
                f"status 必须是 {allowed} 之一或对应 EngagementStatus 枚举"
            ) from exc

    from agi_talent_radar.core.database import get_session

    with get_session() as session:
        history_row = repository.update_engagement_status(
            session=session,
            candidate_id=candidate_id,
            status=normalized.value,
            changed_by=changed_by,
            note=note or "",
        )
        return EngagementStatusChange(
            candidate_id=candidate_id,
            previous=EngagementStatus(history_row.previous_status) if history_row.previous_status else None,
            current=EngagementStatus(history_row.current_status),
            changed_by=history_row.changed_by,
            changed_at=history_row.created_at,
            note=history_row.note or "",
        )


def record_track_recommendation(evaluation_id: int) -> TrackRecommendation:
    """记录一次评估的 Track 推荐，不回写评分与论文核验。

    阶段 4 实装：直接从 EvaluationORM.recommended_tracks 读取，
    与 ``get_research_group_matching`` 字段独立，无回写。
    """
    from agi_talent_radar.core.database import get_session

    with get_session() as session:
        evaluation = session.get(EvaluationORM, evaluation_id)
        if evaluation is None:
            raise ValueError(f"评估运行不存在: {evaluation_id}")
        tracks = list(evaluation.recommended_tracks or [])
        return TrackRecommendation(
            evaluation_id=evaluation_id,
            tracks=tracks,
        )


def get_research_group_matching(candidate_id: str) -> ResearchGroupMatching:
    """查询研究组匹配。

    在 HR 与研究组确认并版本化要求之前，永远返回
    ``ResearchGroupMatchingStatus.NOT_CONFIGURED``，不得伪造匹配分。
    """
    return ResearchGroupMatching(
        candidate_id=candidate_id,
        status=ResearchGroupMatchingStatus.NOT_CONFIGURED,
        requirement_version=None,
        matches=[],
    )


__all__ = [
    "evaluate_resume",
    "retry_publication_verification",
    "admit_candidate_after_evaluation",
    "manual_admit_person_to_pool",
    "update_engagement_status",
    "record_track_recommendation",
    "get_research_group_matching",
]  # noqa: E501
