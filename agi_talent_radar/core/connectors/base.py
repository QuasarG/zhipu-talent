"""外部证据连接器：统一协议 search(identity) -> Fact，失败降级为空集。"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Fact:
    source: str           # 连接器标识，如 web_search / openalex / github
    fact_type: str        # 事实类型，如 search_hit / paper / repo
    payload: dict[str, Any]
    source_url: str = ""
    confidence: float = 1.0
    extra: dict[str, Any] = field(default_factory=dict)


class ConnectorUnavailableError(RuntimeError):
    """连接器依赖缺失或鉴权失败，调用方应降级处理。"""
