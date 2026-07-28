"""人才知识 Agent 的 LangGraph 状态、事件与统一 Fact 模型。

设计要点：

- ``KnowledgeState`` 是 LangGraph 的状态字典；
- ``AgentEvent`` 是流式输出（service 层 yield 出来给 SSE / 调用方）；
- ``KnowledgeFact`` 是统一外部事实结构，所有连接器返回它；
- ``Citation`` 携带来源、获取时间和核验状态，回答中必须出现。
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Iterator, Literal

from pydantic import BaseModel, Field
from typing_extensions import TypedDict


# ---------------------------------------------------------------------------
# 意图与决策枚举
# ---------------------------------------------------------------------------


class UserIntent(str, Enum):
    """意图识别结果。"""

    POOL_QUERY = "pool_query"                  # 库内查询 / 比较 / 统计
    KNOWN_PERSON = "known_person"              # 已知人物调查
    TALENT_DISCOVERY = "talent_discovery"      # 不在本期范围
    UNSUPPORTED = "unsupported"


class ToolSelection(str, Enum):
    """工具选择（哪些外部链路需要调用）。"""

    NONE = "none"            # 库内信息足够
    AMINER = "aminer"
    OPENALEX = "openalex"
    WEB_SEARCH = "web_search"


class FactVerification(str, Enum):
    """事实核验状态（与 domain_models.ExternalFactVerification 对齐）。"""

    CONFIRMED = "confirmed"
    PENDING = "pending"
    CONFLICT = "conflict"
    DISPROVED = "disproved"
    SUPERSEDED = "superseded"


# ---------------------------------------------------------------------------
# 统一 Fact 模型（连接器层返回）
# ---------------------------------------------------------------------------


class KnowledgeFact(BaseModel):
    """连接器返回的统一外部事实结构。Agent 节点不直接解析供应商原始响应。"""

    source: Literal["aminer", "openalex", "web_search", "talent_pool"]
    fact_type: str = ""           # profile / paper / search_hit / ...
    title: str = ""
    payload: dict[str, Any] = Field(default_factory=dict)
    source_url: str = ""
    fetched_at: datetime
    # 默认新事实为 pending；库内已有 confirmed 由 persister 决定。
    verification_status: FactVerification = FactVerification.PENDING


class Citation(BaseModel):
    """回答引用：必须携带来源、获取时间和核验状态。"""

    source: str
    source_url: str = ""
    fetched_at: datetime
    verification_status: FactVerification
    quote: str = ""


# ---------------------------------------------------------------------------
# LangGraph 状态
# ---------------------------------------------------------------------------


class KnowledgeState(TypedDict, total=False):
    """人才知识 Agent 的 LangGraph 状态。"""

    conversation_id: str
    prompt: str
    intent: str                           # UserIntent.value
    scope: list[str]                      # 用户显式限定的范围（如 只看论文）
    identity: dict[str, Any]              # 姓名 / 机构 / 方向 / 附加检索词
    identity_confidence: float
    needs_clarification: bool
    clarification_message: str
    local_facts: list[dict[str, Any]]
    local_sufficient: bool
    tools: list[str]                      # ToolSelection.value
    external_facts: list[dict[str, Any]]
    failed_tools: list[str]
    normalized_facts: list[dict[str, Any]]
    pending_fact_count: int
    answer: str
    citations: list[dict[str, Any]]
    warnings: list[str]


# ---------------------------------------------------------------------------
# 流式事件
# ---------------------------------------------------------------------------


class AgentEvent(BaseModel):
    """service 层 yield 给调用方的事件（SSE 友好）。"""

    type: Literal[
        "node",
        "intent",
        "clarification",
        "local_facts",
        "tool_plan",
        "external_fact",
        "tool_failure",
        "answer",
        "warning",
        "done",
    ]
    payload: dict[str, Any] = Field(default_factory=dict)


__all__ = [
    "UserIntent",
    "ToolSelection",
    "FactVerification",
    "KnowledgeFact",
    "Citation",
    "KnowledgeState",
    "AgentEvent",
]