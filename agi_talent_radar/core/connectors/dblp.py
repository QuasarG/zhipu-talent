"""DBLP 连接器：按作者名检索论文（免费无 key），用于发文核验。

API: https://dblp.org/search/publ/api?q={name}&format=json&h={limit}
"""
from __future__ import annotations

from agi_talent_radar.core.connectors.base import ConnectorUnavailableError, Fact

DBLP_API = "https://dblp.org/search/publ/api"
TIMEOUT_SECONDS = 15


def search_author_pubs(name: str, limit: int = 20) -> list[Fact]:
    """按作者名检索 DBLP 论文；空结果返回 []，失败抛 ConnectorUnavailableError。"""
    name = (name or "").strip()
    if not name:
        return []
    try:
        import httpx
    except ImportError as exc:
        raise ConnectorUnavailableError("缺少 httpx 依赖。") from exc

    params = {"q": name, "format": "json", "h": max(1, min(100, limit))}
    try:
        response = httpx.get(DBLP_API, params=params, timeout=TIMEOUT_SECONDS)
        response.raise_for_status()
        data = response.json()
    except Exception as exc:
        raise ConnectorUnavailableError(f"DBLP 调用失败: {exc}") from exc

    hits = (((data.get("result") or {}).get("hits") or {}).get("hit")) or []
    facts = []
    for hit in hits:
        info = (hit or {}).get("info") or {}
        authors_raw = (info.get("authors") or {}).get("author") or []
        if isinstance(authors_raw, dict):
            authors_raw = [authors_raw]
        authors = [
            str(author.get("text") or "") if isinstance(author, dict) else str(author)
            for author in authors_raw
        ]
        facts.append(
            Fact(
                source="dblp",
                fact_type="dblp_publication",
                payload={
                    "query_name": name,
                    "title": str(info.get("title") or ""),
                    "venue": str(info.get("venue") or ""),
                    "year": info.get("year"),
                    "type": str(info.get("type") or ""),
                    "authors": authors,
                },
                source_url=str(info.get("url") or ""),
            )
        )
    return facts
