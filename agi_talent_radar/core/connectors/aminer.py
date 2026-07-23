"""AMiner MCP 连接器：通过 MCP 协议（SSE）查学者画像。

实际可用工具：search_person（免费，返回 interests/n_citation/org）。
search_paper / get_* 系列当前账户余额不足，调用会返回 success=false。

文档: https://www.aminer.cn/open/docs
MCP 服务: https://mcp.aminer.cn/sse
"""
from __future__ import annotations

import asyncio
import json
import os

from agi_talent_radar.core.connectors.base import ConnectorUnavailableError, Fact

AMINER_MCP_URL = "https://mcp.aminer.cn/sse"


def _check_auth() -> str:
    """取鉴权 token，缺失直接抛 ConnectorUnavailableError。"""
    token = os.getenv("AMINER_AUTH_TOKEN", "").strip()
    if not token:
        raise ConnectorUnavailableError("缺少 AMINER_AUTH_TOKEN，AMiner 连接器不可用。")
    return token


async def _call_search_person(name: str, org: str, size: int) -> list[dict]:
    """连接 MCP 服务，调用 search_person，返回原始学者列表。"""
    from mcp import ClientSession
    from mcp.client.sse import sse_client

    token = _check_auth()
    headers = {"Authorization": f"Bearer {token}"}
    payload = {"name": name.strip(), "size": max(1, min(10, size))}
    if org.strip():
        payload["org"] = org.strip()

    async with sse_client(url=AMINER_MCP_URL, headers=headers) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool("search_person", payload)
    text = result.content[0].text if result.content and hasattr(result.content[0], "text") else ""
    if not text:
        return []
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ConnectorUnavailableError(f"AMiner 返回非 JSON: {exc}") from exc
    if isinstance(data, dict) and data.get("success") is False:
        # 余额不足或鉴权失败等
        raise ConnectorUnavailableError(f"AMiner 拒绝: {data.get('msg', '未知原因')}")
    persons = data.get("data") if isinstance(data, dict) else data
    return [p for p in (persons or []) if isinstance(p, dict)]


def search_aminer_scholar(name: str, org: str = "", size: int = 5) -> list[Fact]:
    """按姓名（+机构消歧）检索学者，返回画像 Fact；失败抛 ConnectorUnavailableError 由上层降级。

    机构名经 LLM 标准化：用规范全称查 AMiner，用全部关键词变体做客户端消歧匹配。
    """
    if not (name or "").strip():
        return []
    org_terms = _normalize_org_terms(org)
    # 查询用规范全称（服务端过滤），客户端再用全部变体兜底匹配
    query_org = org_terms[0] if org_terms else ""
    try:
        persons = asyncio.run(_call_search_person(name, query_org, size))
    except ConnectorUnavailableError:
        raise
    except RuntimeError as exc:
        # 嵌套事件循环或网络异常
        raise ConnectorUnavailableError(f"AMiner MCP 调用失败: {exc}") from exc

    facts = [_scholar_to_fact(name, p) for p in persons]
    if org_terms:
        facts = [f for f in facts if _org_matches_any(f.payload.get("org", "") + f.payload.get("org_zh", ""), org_terms)]
    return facts


def _normalize_org_terms(org: str) -> list[str]:
    """机构名标准化成检索关键词；标准化失败时退化为原始输入。"""
    org = (org or "").strip()
    if not org:
        return []
    try:
        from agi_talent_radar.core.org_normalizer import normalize_org

        return normalize_org(org).search_terms
    except Exception:
        return [org]


def search_aminer_papers(name: str, size: int = 10) -> list[Fact]:
    """按作者姓名检索代表论文。当前 MCP search_paper 余额不足，返回空集。"""
    # search_person 免费但 search_paper 需付费，账户余额不足时调用即失败。
    # 保留接口签名供调用方无脑调用；付费开通后这里接入 MCP search_paper。
    return []


def _scholar_to_fact(query_name: str, person: dict) -> Fact:
    """AMiner search_person 字段 -> 标准化 payload。"""
    aminer_id = str(person.get("id") or "")
    return Fact(
        source="aminer",
        fact_type="scholar",
        payload={
            "query_name": query_name,
            "name": str(person.get("name") or person.get("name_zh") or ""),
            "name_zh": str(person.get("name_zh") or ""),
            "org": str(person.get("org") or ""),
            "org_zh": str(person.get("org_zh") or ""),
            "research_interests": list(person.get("interests") or []),
            "citation_count": int(person.get("n_citation") or 0),
            "aminer_id": aminer_id,
        },
        source_url=f"https://www.aminer.cn/profile/{aminer_id}" if aminer_id else "",
    )


def _org_matches_any(scholar_org: str, org_terms: list[str]) -> bool:
    """机构名宽松匹配：任一关键词变体子串命中即可（处理缩写/中英文）。"""
    s = scholar_org.lower()
    for term in org_terms:
        q = term.lower().strip()
        if q and (q in s or s in q):
            return True
    return False
