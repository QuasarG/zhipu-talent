"""OpenAlex 连接器：免费学术图谱，核查论文真伪/作者位次/被引/撤稿。

文档: https://docs.openalex.org （无需 key，带 mailto 进礼貌池）
"""
from __future__ import annotations

import os

from agi_talent_radar.core.connectors.base import ConnectorUnavailableError, Fact

OPENALEX_WORKS_URL = "https://api.openalex.org/works"
TIMEOUT_SECONDS = 30


def _get(httpx, params: dict) -> dict:
    response = httpx.get(OPENALEX_WORKS_URL, params=params, timeout=TIMEOUT_SECONDS)
    response.raise_for_status()
    return response.json()


def search_works(title: str, count: int = 5) -> list[Fact]:
    """按标题检索论文，返回标准化 Fact；失败抛 ConnectorUnavailableError 由上层降级。"""
    if not (title or "").strip():
        return []
    try:
        import httpx
    except ImportError as exc:
        raise ConnectorUnavailableError("缺少 httpx 依赖。") from exc

    per_page = max(1, min(25, count))
    params = {
        "filter": f"title.search:{title.strip()}",
        "per-page": per_page,
        "sort": "cited_by_count:desc",
    }
    mailto = os.getenv("OPENALEX_MAILTO", "").strip()
    if mailto:
        params["mailto"] = mailto
    try:
        data = _get(httpx, params)
        if not data.get("results"):
            # 标题精确检索无果时退化为全文检索
            fallback = {"search": title.strip(), "per-page": per_page}
            if mailto:
                fallback["mailto"] = mailto
            data = _get(httpx, fallback)
    except Exception as exc:
        raise ConnectorUnavailableError(f"OpenAlex 调用失败: {exc}") from exc

    facts = []
    for work in data.get("results", []):
        if not isinstance(work, dict):
            continue
        source = (work.get("primary_location") or {}).get("source") or {}
        authors = [
            str((authorship.get("author") or {}).get("display_name", ""))
            for authorship in work.get("authorships", [])
        ]
        facts.append(
            Fact(
                source="openalex",
                fact_type="paper",
                payload={
                    "query_title": title,
                    "title": str(work.get("title") or ""),
                    "year": work.get("publication_year"),
                    "venue": str(source.get("display_name") or ""),
                    "type": str(work.get("type") or ""),
                    "cited_by_count": work.get("cited_by_count", 0),
                    "is_retracted": bool(work.get("is_retracted")),
                    "authors": authors,
                    "first_author": authors[0] if authors else "",
                    "doi": str(work.get("doi") or ""),
                },
                source_url=str(work.get("id") or work.get("doi") or ""),
            )
        )
    return facts
