"""多源论文检索编排：AMiner → CrossRef → arXiv → OpenAlex 四级降级。

每个源 try/except ConnectorUnavailableError，命中即返回，不阻塞流程。
多查询变体（expand_search_queries）提升召回：原文 + 主标题 + 纯净版。
"""
from __future__ import annotations

import re

from agi_talent_radar.core.connectors.base import ConnectorUnavailableError, Fact


def expand_search_queries(title: str) -> list[str]:
    """从论文标题生成多个检索查询变体，提升召回。

    OCR 错字/连字符丢失/省略副标题都会导致单次整体匹配召回 0。
    纯规则拆分：原文 + 冒号前主标题 + 去符号纯净版。
    """
    title = (title or "").strip()
    if not title:
        return []
    queries = [title]
    head = re.split(r"[:：—\-–]", title, maxsplit=1)[0].strip()
    if head and len(head) >= 4 and head.lower() != title.lower():
        queries.append(head)
    cleaned = re.sub(r"[^0-9A-Za-z\s]", " ", title)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    cleaned = re.sub(r"\b(and|the|a|an|of|for|with|to|in|on|via|using)\b", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if cleaned and cleaned.lower() not in {q.lower() for q in queries} and len(cleaned) >= 6:
        queries.append(cleaned)
    return queries


def search_papers_federated(title: str, count: int = 5) -> list[Fact]:
    """四级降级论文检索：AMiner → CrossRef → arXiv → OpenAlex。

    每源 try/except，命中非空即返回；全失败返回空列表。
    """
    sources: list[tuple[str, callable]] = [
        ("aminer", _search_aminer),
        ("crossref", _search_crossref),
        ("arxiv", _search_arxiv),
        ("openalex", _search_openalex),
    ]
    for _name, fn in sources:
        try:
            facts = fn(title, count)
            if facts:
                return facts
        except ConnectorUnavailableError:
            continue
    return []


def search_papers_federated_merged(title: str, count: int = 5) -> list[Fact]:
    """多查询变体 + 四源降级 + 合并去重，按标题相似度排序。

    用于评估链 lookup_claim（需要尽可能多的候选做对齐）。
    """
    from difflib import SequenceMatcher

    queries = expand_search_queries(title)
    if not queries:
        return []
    seen: set[str] = set()
    merged: list[Fact] = []
    for q in queries:
        try:
            facts = search_papers_federated(q, count)
        except ConnectorUnavailableError:
            continue
        for f in facts:
            t = str(f.payload.get("title", "")).strip().lower()
            if t and t not in seen:
                seen.add(t)
                merged.append(f)
    merged.sort(
        key=lambda f: SequenceMatcher(None, title.lower().strip(), str(f.payload.get("title", "")).lower().strip()).ratio(),
        reverse=True,
    )
    return merged[:10]


def _search_aminer(title: str, count: int) -> list[Fact]:
    from agi_talent_radar.core.connectors.aminer_rest import search_aminer_papers_by_title
    return search_aminer_papers_by_title(title, size=count)


def _search_crossref(title: str, count: int) -> list[Fact]:
    from agi_talent_radar.core.connectors.crossref import search_works
    return search_works(title, count=count)


def _search_arxiv(title: str, count: int) -> list[Fact]:
    from agi_talent_radar.core.connectors.arxiv import search_papers
    return search_papers(title, count=count)


def _search_openalex(title: str, count: int) -> list[Fact]:
    from agi_talent_radar.core.connectors.openalex import search_works
    return search_works(title, count=count)
