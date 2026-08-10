"""CrossRef 连接器：按标题检索有 DOI 的正式发表论文。

免费无 key，带 mailto 进 polite pool（限速更宽）。
CrossRef 原生提供精确被引数和撤稿标记，是 DOI 核验的权威来源。
"""
from __future__ import annotations

import os

from agi_talent_radar.core.connectors.base import ConnectorUnavailableError, Fact

CROSSREF_WORKS_URL = "https://api.crossref.org/works"
TIMEOUT_SECONDS = 30


def search_works(title: str, count: int = 5) -> list[Fact]:
    """按标题关键词检索 CrossRef 论文，返回统一 Fact 列表。"""
    title = (title or "").strip()
    if not title:
        return []
    try:
        import httpx
    except ImportError as exc:
        raise ConnectorUnavailableError("缺少 httpx 依赖。") from exc

    params: dict[str, str | int] = {
        "query.bibliographic": title,
        "rows": max(1, min(50, count)),
    }
    mailto = os.getenv("CROSSREF_MAILTO") or os.getenv("OPENALEX_MAILTO", "")
    if mailto:
        params["mailto"] = mailto

    try:
        resp = httpx.get(CROSSREF_WORKS_URL, params=params, timeout=TIMEOUT_SECONDS)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        raise ConnectorUnavailableError(f"CrossRef 调用失败: {exc}") from exc

    items = (data.get("message") or {}).get("items") or []
    return [_work_to_fact(item, title) for item in items if _work_to_fact(item, title)]


def _work_to_fact(item: dict, query_title: str) -> Fact | None:
    title_list = item.get("title") or []
    title = title_list[0] if title_list else ""
    if not title:
        return None

    authors: list[str] = []
    for a in item.get("author") or []:
        name = " ".join(filter(None, [a.get("given", ""), a.get("family", "")])).strip()
        if name:
            authors.append(name)

    # 年份：优先 print，其次 online
    year = None
    for key in ("published-print", "published-online"):
        parts = (item.get(key) or {}).get("date-parts") or []
        if parts and parts[0] and parts[0][0]:
            year = int(parts[0][0])
            break

    venue_list = item.get("container-title") or []
    doi = item.get("DOI") or ""

    return Fact(
        source="crossref",
        fact_type="paper",
        payload={
            "title": title,
            "authors": authors,
            "first_author": authors[0] if authors else "",
            "year": year,
            "venue": venue_list[0] if venue_list else "",
            "doi": doi,
            "cited_by_count": item.get("is-referenced-by-count") or 0,
            "is_retracted": bool(item.get("is-retracted")),
            "type": item.get("type") or "",
            "query_title": query_title,
        },
        source_url=f"https://doi.org/{doi}" if doi else "",
    )
