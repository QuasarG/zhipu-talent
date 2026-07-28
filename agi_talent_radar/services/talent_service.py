"""候选人才库事务高层接口。

本轮（阶段 0 子集）只声明接口、不实装；
所有写路径函数体抛 ``NotImplementedError``，等阶段 1 / 4 / 5 / 7 再接入。

契约要点（与 ``CONTEXT.md``、``docs/backend_use_case_decisions.md`` 对齐）：

1. ``evaluate_resume`` 必须经 ``admit_candidate_after_evaluation`` 才能写入人才库。
   不允许评估成功后跳过入库事务直接改 ``candidate.group``。
2. ``update_engagement_status`` 必须强制要求 ``changed_by`` 和 ``note``；
   禁止接受 ``overall_score``、``level`` 等隐式入参。
   系统不得基于分数、舆情或其他自动规则切换跟进状态。
3. ``record_track_recommendation`` 与 ``get_research_group_matching`` 字段独立。
   未配置研究组要求时，研究组匹配永远返回 ``NOT_CONFIGURED``。
4. ``manual_admit_person_to_pool`` 仅 HR 显式调用；不接受自动路径触发。
5. ``retry_publication_verification`` 仅重试核验任务，不得重跑整份评估。
"""
from __future__ import annotations

from typing import Any

from agi_talent_radar.core.domain_models import (
    EngagementStatus,
    EngagementStatusChange,
    PublicationClaim,
    ResearchGroupMatching,
    ResearchGroupMatchingStatus,
    TrackRecommendation,
)


def evaluate_resume(submission_id: str) -> dict[str, Any]:
    """驱动一次简历评估。返回评估摘要（不含 HR 状态、不含录取等级）。

    内部顺序：身份归并 → 标准化 → 论文自述提取 → 证据提取 → 通用潜力 →
    Track 路由/评分 → 汇总 → 格式化。

    评估成功且需要入库时，必须调用 ``admit_candidate_after_evaluation``，
    不允许直接修改 ``CandidateORM.group``。
    """
    raise NotImplementedError("阶段 0 子集仅声明接口；阶段 4 实装。")


def retry_publication_verification(
    evaluation_id: int,
    paper_claim_ids: list[str] | None = None,
) -> dict[str, Any]:
    """仅重试外部论文核验任务，不重跑整份评估。"""
    raise NotImplementedError("阶段 0 子集仅声明接口；阶段 3 实装。")


def admit_candidate_after_evaluation(evaluation_id: int) -> dict[str, Any]:
    """评估成功后将候选人关联或创建到人才库。

    - 必须显式调用，不接受 ``automatic=True`` 或基于 ``overall_score`` 的隐式触发。
    - 评估未完成 / 评估失败时拒绝调用。
    - 写入 ``Candidate`` 后必须追加 ``resume_evaluation`` 来源。
    """
    raise NotImplementedError("阶段 0 子集仅声明接口；阶段 1 实装。")


def manual_admit_person_to_pool(
    person_id: str,
    changed_by: str,
    note: str,
) -> dict[str, Any]:
    """HR 显式把已知人物调查后的人物主档加入人才库。

    - 必须由 HR 显式触发；不接受自动路径。
    - 同一 ``person_id`` 至多拥有一个 ``Candidate``；重复调用必须幂等。
    """
    raise NotImplementedError("阶段 0 子集仅声明接口；阶段 1 实装。")


def update_engagement_status(
    candidate_id: str,
    status: EngagementStatus,
    changed_by: str,
    note: str,
) -> EngagementStatusChange:
    """人工修改 HR 跟进状态。

    强制要求 ``changed_by`` 与 ``note``；不接受 ``overall_score``、``level``、
    ``automatic`` 等隐式入参。系统不得基于分数、舆情或其他自动规则切换。
    """
    raise NotImplementedError("阶段 0 子集仅声明接口；阶段 1 实装。")


def record_track_recommendation(evaluation_id: int) -> TrackRecommendation:
    """记录一次评估的 Track 推荐，不回写评分与论文核验。"""
    raise NotImplementedError("阶段 0 子集仅声明接口；阶段 4 实装。")


def get_research_group_matching(candidate_id: str) -> ResearchGroupMatching:
    """查询研究组匹配。

    在 HR 与研究组确认并版本化要求之前，永远返回
    ``ResearchGroupMatchingStatus.NOT_CONFIGURED``，不得伪造匹配分。
    """
    raise NotImplementedError("阶段 0 子集仅声明接口；阶段 6 实装。")


__all__ = [
    "evaluate_resume",
    "retry_publication_verification",
    "admit_candidate_after_evaluation",
    "manual_admit_person_to_pool",
    "update_engagement_status",
    "record_track_recommendation",
    "get_research_group_matching",
]