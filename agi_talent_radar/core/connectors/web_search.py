"""智谱 web-search-prime MCP 连接器：舆情/公开信息检索。

MCP 端点（streamable HTTP）：https://open.bigmodel.cn/api/mcp/web_search_prime/mcp
工具名 web_search_prime，Authorization: Bearer <LLM_API_KEY>（智谱开放平台 Key）。
替代旧 /api/paas/v4/web_search REST 直连。
"""
from __future__ import annotations

import json
import os

from agi_talent_radar.core.connectors.base import ConnectorUnavailableError, Fact

MCP_URL = "https://open.bigmodel.cn/api/mcp/web_search_prime/mcp"
TOOL_NAME = "web_search_prime"
TIMEOUT_SECONDS = 30


def search_web(
    query: str,
    count: int = 10,
    engine: str = "",
    domain_filter: str = "",
    recency_filter: str = "",
) -> list[Fact]:
    """单次检索，返回统一 Fact 列表；任何失败都抛 ConnectorUnavailableError 由上层降级。

    engine / recency_filter 是旧 REST 接口的参数，MCP 版不支持，仅为签名兼容保留。
    """
    api_key = (os.getenv("LLM_API_KEY") or os.getenv("Z_AI_API_KEY", "")).strip()
    if not api_key:
        raise ConnectorUnavailableError("缺少 LLM_API_KEY，无法调用网络搜索。")
    try:
        items = _fetch(query[:70], domain_filter, api_key)
    except ConnectorUnavailableError:
        raise
    except Exception as exc:
        raise ConnectorUnavailableError(f"网络搜索 MCP 调用失败: {exc}") from exc

    facts = []
    for item in items[: max(1, min(50, count))]:
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
                    "media": str(item.get("media", "") or item.get("refer", "")),
                    "publish_date": str(item.get("publish_date", "")),
                },
                source_url=str(item.get("link", "")),
            )
        )
    return facts


def _fetch(query: str, domain_filter: str, api_key: str) -> list[dict]:
    """同步包装：在线程内起一次性事件循环跑 MCP 调用。"""
    try:
        import anyio
    except ImportError as exc:
        raise ConnectorUnavailableError("缺少 mcp/anyio 依赖。") from exc
    return anyio.run(_call_mcp, query, domain_filter, api_key)


async def _call_mcp(query: str, domain_filter: str, api_key: str) -> list[dict]:
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client

    arguments: dict = {"search_query": query}
    if domain_filter:
        arguments["search_domain_filter"] = domain_filter
    headers = {"Authorization": f"Bearer {api_key}"}

    import anyio

    with anyio.fail_after(TIMEOUT_SECONDS):
        async with streamablehttp_client(MCP_URL, headers=headers) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(TOOL_NAME, arguments)

    if getattr(result, "isError", False):
        text = "".join(getattr(c, "text", "") for c in result.content)
        raise ConnectorUnavailableError(f"网络搜索 MCP 返回错误: {text[:200]}")
    text = "".join(getattr(c, "text", "") for c in result.content).strip()
    if not text:
        return []
    # 返回内容是 JSON 字符串里再包一层 JSON 数组（双重编码）
    data = json.loads(text)
    if isinstance(data, str):
        data = json.loads(data)
    return data if isinstance(data, list) else []
