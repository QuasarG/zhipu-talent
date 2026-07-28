"""业务事务下沉入口。

按计划 M1，本包承担以下高层接口：

- ``talent_service``: 简历评估入库、HR 跟进状态、研究组匹配等候选人才库事务。
- ``identity_service``: 入库前的身份归并（入库身份归并节点）。
- 后续阶段新增 ``knowledge_agent``、``research_group_matching`` 等子模块。

本轮（阶段 0 子集）只声明接口、不实装：
任何写路径函数体都会抛 ``NotImplementedError``，
等阶段 1 / 4 / 5 再把 ``core/db/repository.py`` 与 ``core/runner.py`` 替换为这些接口。
"""
from __future__ import annotations

from agi_talent_radar.services import identity_service, talent_service

__all__ = [
    "identity_service",
    "talent_service",
]
