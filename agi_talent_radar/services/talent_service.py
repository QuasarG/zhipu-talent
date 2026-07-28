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

from datetime import datetime, timezone
from typing import Any

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

    阶段 4 实装：身份归并 → 标准化 → 论文自述提取 → 证据提取 → 通用潜力 →
    Track 路由/评分 → 汇总 → 格式化。

    评估成功且需要入库时，必须调用 ``admit_candidate_after_evaluation``，
    不允许直接修改 ``CandidateORM.group``。
    """
    raise NotImplementedError("阶段 1 仅实装事务接口；阶段 4 编排实装。")


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

        candidate = repository.find_candidate_by_person(session, person_id)
        if candidate is None:
            candidate = repository.find_or_create_candidate_for_person(
                session,
                person_id=person_id,
                name=candidate_name,
                target_role=candidate_role,
                stage=candidate_stage,
            )
            evaluation.candidate_id = candidate.id

        repository.append_candidate_source(
            session,
            candidate_id=candidate.id,
            source_kind="resume_evaluation",
            source_record_id=str(evaluation.id),
            created_by="system:resume_evaluation",
        )
        sources = repository.list_candidate_source_kinds(session, candidate.id)
        return {
            "candidate_id": candidate.id,
            "person_id": person_id,
            "sources": sources,
        }


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