"""arXiv 连接器：按标题检索预印本论文。

免费无 key，返回 Atom XML（用 xml.etree 解析）。
覆盖 CS/物理/数学等领域的预印本，很多人先挂 arXiv 再正式发表。
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET

from agi_talent_radar.core.connectors.base import ConnectorUnavailableError, Fact

ARXIV_API = "https://export.arxiv.org/api/query"
TIMEOUT_SECONDS = 30
_ATOM_NS = "{http://www.w3.org/2005/Atom}"


def search_papers(title: str, count: int = 5) -> list[Fact]:
    """按标题关键词检索 arXiv 预印本，返回统一 Fact 列表。"""
    title = (title or "").strip()
    if not title:
        return []
    try:
        import httpx
    except ImportError as exc:
        raise ConnectorUnavailableError("缺少 httpx 依赖。") from exc

    # ti: 只搜标题字段，召回更精确
    cleaned = re.sub(r'\s+', '+', title)
    params = {
        "search_query": f"ti:{cleaned}",
        "start": 0,
        "max_results": max(1, min(50, count)),
        "sortBy": "relevance",
    }

    try:
        resp = httpx.get(ARXIV_API, params=params, timeout=TIMEOUT_SECONDS)
        resp.raise_for_status()
        root = ET.fromstring(resp.text)
    except Exception as exc:
        raise ConnectorUnavailableError(f"arXiv 调用失败: {exc}") from exc

    facts: list[Fact] = []
    for entry in root.findall(f"{_ATOM_NS}entry"):
        fact = _entry_to_fact(entry, title)
        if fact:
            facts.append(fact)
    return facts


def _entry_to_fact(entry: ET.Element, query_title: str) -> Fact | None:
    def _text(tag: str) -> str:
        el = entry.find(f"{_ATOM_NS}{tag}")
        return (el.text or "").strip() if el is not None else ""

    title = _text("title").replace("\n", " ").strip()
    title = re.sub(r"\s+", " ", title)
    if not title:
        return None

    authors: list[str] = []
    for author in entry.findall(f"{_ATOM_NS}author"):
        name_el = author.find(f"{_ATOM_NS}name")
        if name_el is not None and name_el.text:
            authors.append(name_el.text.strip())

    # arXiv entry 的 id 形如 http://arxiv.org/abs/2401.12345v1
    entry_id = _text("id")
    arxiv_id = entry_id.rsplit("/", 1)[-1] if entry_id else ""
    # 去版本号 v1
    arxiv_id = re.sub(r"v\d+$", "", arxiv_id)

    year = None
    published = _text("published")
    if published and len(published) >= 4:
        try:
            year = int(published[:4])
        except ValueError:
            pass

    # DOI 可选（部分 arXiv 论文关联正式发表 DOI）
    doi_el = entry.find(f"{_ATOM_NS}doi")
    doi = doi_el.text.strip() if doi_el is not None else ""

    return Fact(
        source="arxiv",
        fact_type="paper",
        payload={
            "title": title,
            "authors": authors,
            "first_author": authors[0] if authors else "",
            "year": year,
            "venue": "arXiv preprint",
            "doi": doi,
            "arxiv_id": arxiv_id,
            "cited_by_count": 0,  # arXiv 不提供被引数
            "is_retracted": False,
            "type": "preprint",
            "query_title": query_title,
        },
        source_url=f"https://arxiv.org/abs/{arxiv_id}" if arxiv_id else entry_id,
    )
