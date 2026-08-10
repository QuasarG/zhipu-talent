"""业务事务下沉入口。

- ``talent_service``: 简历评估入库、HR 跟进状态等候选人才库事务（已实装）。
- ``identity_service``: 入库前的身份归并（入库身份归并节点，已实装）。
"""
from __future__ import annotations

from agi_talent_radar.services import identity_service, talent_service

__all__ = [
    "identity_service",
    "talent_service",
]
