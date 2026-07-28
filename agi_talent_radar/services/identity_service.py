"""入库身份归并（Intake Identity Resolution）高层接口。

本轮（阶段 0 子集）只声明接口、不实装；
函数体抛 ``NotImplementedError``，等阶段 2 再接入 LangGraph 节点。

策略：

- 第一层确定性匹配：邮箱、ORCID、AMiner ID 等稳定唯一标识；
- 第二层 AI 模糊匹配：姓名变体、学校/机构、时间线、方向和论文。

首版采用保守策略：
- 稳定标识精确一致可自动归并；
- AI 模糊结果先生成 ``IdentityDecision.NEEDS_REVIEW`` 建议，不自动合并。
"""
from __future__ import annotations

from agi_talent_radar.core.domain_models import IdentityEvidence, IdentityResolution


def resolve_intake_identity(evidence: IdentityEvidence) -> IdentityResolution:
    """对一份入库简历执行身份归并。

    返回 ``IdentityResolution``，包含：

    - ``matched_person_id``：命中已有 Person 时返回；否则 ``None``。
    - ``decision``：``new`` / ``matched`` / ``needs_review`` / ``conflict``。
    - ``confidence``：0~1。
    - ``supporting_evidence``：支持命中的证据描述。
    - ``conflicts``：冲突项描述。

    身份冲突时会返回 ``conflict`` 决策并阻止自动归并；
    评分节点不应读取历史分数、HR 状态或旧结论。
    """
    raise NotImplementedError("阶段 0 子集仅声明接口；阶段 2 实装。")


__all__ = ["resolve_intake_identity"]