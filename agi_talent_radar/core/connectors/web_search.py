"""智谱 Web Search API 连接器：舆情/公开信息检索。

文档: https://docs.bigmodel.cn （工具 API - 网络搜索）
"""
from __future__ import annotations

import os

from agi_talent_radar.core.connectors.base import ConnectorUnavailableError, Fact

WEB_SEARCH_URL = "https://open.bigmodel.cn/api/paas/v4/web_search"
DEFAULT_ENGINE = "search_std"
TIMEOUT_SECONDS = 30


def search_web(
    query: str,
    count: int = 10,
    engine: str = DEFAULT_ENGINE,
    domain_filter: str = "",
    recency_filter: str = "noLimit",
) -> list[Fact]:
    """单次检索，返回统一 Fact 列表；任何失败都抛 ConnectorUnavailableError 由上层降级。"""
    api_key = os.getenv("Z_AI_API_KEY", "").strip()
    if not api_key:
        raise ConnectorUnavailableError("缺少 Z_AI_API_KEY，无法调用网络搜索。")
    try:
        import httpx
    except ImportError as exc:
        raise ConnectorUnavailableError("缺少 httpx 依赖。") from exc

    payload = {
        "search_query": query[:70],
        "search_engine": engine,
        "search_intent": False,
        "count": max(1, min(50, count)),
        "search_recency_filter": recency_filter,
        "content_size": "medium",
    }
    if domain_filter:
        payload["search_domain_filter"] = domain_filter
    try:
        response = httpx.post(
            WEB_SEARCH_URL,
            json=payload,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        data = response.json()
    except Exception as exc:
        raise ConnectorUnavailableError(f"网络搜索调用失败: {exc}") from exc
    if isinstance(data, dict) and data.get("error"):
        raise ConnectorUnavailableError(f"网络搜索返回错误: {data['error']}")

    results = data.get("search_result", []) if isinstance(data, dict) else []
    facts = []
    for item in results:
        if not isinstance(item, dict):
            continue
        facts.append(
            Fact(
                source="web_search",
                fact_type="search_hit",
                payload={
                    "query": query,
                    "title": str(item.get("title", "")),
                    "content": str(item.get("content", "")),
                    "media": str(item.get("media", "")),
                    "publish_date": str(item.get("publish_date", "")),
                },
                source_url=str(item.get("link", "")),
            )
        )
    return facts
