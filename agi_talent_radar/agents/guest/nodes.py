"""嘉宾画像链：研究方向 + 代表成果提取。

AMiner 优先；拿不到 key 时降级走 web_search 检索 + LLM 抽取。
判定克制：查不到只标 warning，不编造方向。
"""
from __future__ import annotations

from collections.abc import Callable

from agi_talent_radar.core import llm_client
from agi_talent_radar.core.connectors import (
    ConnectorUnavailableError,
    Fact,
    search_aminer_papers,
    search_aminer_scholar,
    search_web,
)

from agi_talent_radar.agents.guest.models import (
    ResearchDirection,
    RepresentativeWork,
    ScholarProfile,
)

PROFILE_QUERY_TEMPLATES = [
    "{name} {org} 研究方向",
    "{name} {org} 论文",
    "{name} {org} 代表成果",
]

PROFILE_EXTRACTOR_PROMPT = """
你是学术画像提取 Agent。只输出 JSON 对象，顶层字段必须是 profile。

任务：根据输入的检索结果，提取这位学者的研究方向与代表成果。

输入：
- identity: 候选人姓名 + 机构 + 已知方向
- hits: 公开检索结果（title / content / url）

输出字段：
- research_directions: list[{name, evidence, source_urls}]
  - name: 研究方向名称（如"大模型对齐""强化学习"）
  - evidence: 该方向从哪条证据抽出的（引用原文片段或来源）
  - source_urls: 支撑该方向的来源 URL 列表
- representative_works: list[{title, venue, year, role}]
  - 从检索结果里能识别出的代表性论文/成果，role 填 一作/通讯/其他/不明，查不到填空
- affiliation: 当前所在机构（消歧用），不确定填空
- citation_count, publication_count, hindex: 检索结果里有就填整数，没有填 0

规则：
1. 只提取有证据支撑的方向，不得编造。
2. 没有明确来源的方向不写。
3. 检索结果与目标人物对不上（同名不同人）时，全部留空并在 note 说明。
""".strip()


def _build_queries(name: str, org: str) -> list[str]:
    base = {"name": name, "org": org}
    return [t.format(**base) for t in PROFILE_QUERY_TEMPLATES]


def _collect_hits(
    name: str,
    org: str,
    search_fn: Callable[..., list[Fact]] = search_web,
    count_per_query: int = 6,
) -> tuple[list[dict], list[str]]:
    """跑模板检索，URL 去重，返回 (hits payload, warnings)。"""
    hits: list[dict] = []
    seen_urls: set[str] = set()
    warnings: list[str] = []
    for query in _build_queries(name, org):
        try:
            facts = search_fn(query, count=count_per_query)
        except ConnectorUnavailableError as exc:
            warnings.append(f"检索失败[{query[:20]}]: {exc}")
            continue
        for fact in facts:
            url = fact.source_url or ""
            if url and url in seen_urls:
                continue
            if url:
                seen_urls.add(url)
            hits.append(
                {
                    "query": query,
                    "title": str(fact.payload.get("title", "")),
                    "content": str(fact.payload.get("content", "")),
                    "url": url,
                    "media": str(fact.payload.get("media", "")),
                }
            )
    return hits, warnings


def build_scholar_profile(
    name: str,
    org: str = "",
    direction: str = "",
    aminer_scholar_fn: Callable[..., list[Fact]] = search_aminer_scholar,
    aminer_paper_fn: Callable[..., list[Fact]] = search_aminer_papers,
    web_search_fn: Callable[..., list[Fact]] = search_web,
) -> ScholarProfile:
    """优先用 AMiner 拿画像；拿不到降级走 web_search + LLM 抽取。"""
    profile, warnings = _try_aminer(name, org, aminer_scholar_fn, aminer_paper_fn)
    if profile is not None:
        return profile

    # AMiner 不可用，降级走 web_search
    warnings.append("AMiner 不可用，降级使用 web_search 抽取研究方向。")
    hits, hit_warnings = _collect_hits(name, org, search_fn=web_search_fn)
    warnings.extend(hit_warnings)
    if not hits:
        warnings.append("web_search 无命中，无法提取研究方向。")
        return ScholarProfile(name=name, org=org, data_source="web_search", warnings=warnings)

    profile = _extract_profile_via_llm(name, org, direction, hits)
    profile.warnings = warnings
    return profile


def _try_aminer(
    name: str,
    org: str,
    scholar_fn: Callable[..., list[Fact]],
    paper_fn: Callable[..., list[Fact]],
) -> tuple[ScholarProfile | None, list[str]]:
    """尝试用 AMiner 画像；失败返回 (None, warnings)。"""
    warnings: list[str] = []
    try:
        scholars = scholar_fn(name, org=org, size=3)
    except ConnectorUnavailableError as exc:
        warnings.append(str(exc))
        return None, warnings
    if not scholars:
        warnings.append("AMiner 学者检索无命中。")
        return None, warnings

    best = scholars[0]
    payload = best.payload
    directions = [
        ResearchDirection(name=tag, evidence="aminer 学者画像", source_urls=[best.source_url])
        for tag in payload.get("research_interests", [])
    ]
    # AMiner 论文补代表成果
    works: list[RepresentativeWork] = []
    try:
        papers = paper_fn(name, size=10)
    except ConnectorUnavailableError as exc:
        warnings.append(str(exc))
        papers = []
    for paper in papers:
        p = paper.payload
        works.append(
            RepresentativeWork(
                title=p.get("title", ""),
                venue=p.get("venue", ""),
                year=str(p.get("year", "")),
                role="不明",
            )
        )
    return (
        ScholarProfile(
            name=payload.get("name", name),
            org=payload.get("org", org),
            research_directions=directions,
            representative_works=works,
            affiliation=payload.get("org", ""),
            citation_count=payload.get("citation_count", 0),
            publication_count=payload.get("publication_count", 0),
            hindex=payload.get("hindex", 0),
            data_source="aminer",
            warnings=warnings,
        ),
        warnings,
    )


def _extract_profile_via_llm(name: str, org: str, direction: str, hits: list[dict]) -> ScholarProfile:
    """web_search 降级路径：LLM 从检索结果抽取方向与成果。"""
    response = llm_client.call_llm_json(
        PROFILE_EXTRACTOR_PROMPT,
        {
            "identity": {"name": name, "org": org, "direction": direction},
            "hits": hits,
        },
        temperature=0.1,
    )
    raw = response.get("profile", response) if isinstance(response, dict) else {}
    directions = [
        ResearchDirection(
            name=str(d.get("name", "")),
            evidence=str(d.get("evidence", "")),
            source_urls=[str(u) for u in d.get("source_urls", []) if u],
        )
        for d in raw.get("research_directions", [])
        if str(d.get("name", "")).strip()
    ]
    works = [
        RepresentativeWork(
            title=str(w.get("title", "")),
            venue=str(w.get("venue", "")),
            year=str(w.get("year", "")),
            role=str(w.get("role", "不明")),
        )
        for w in raw.get("representative_works", [])
        if str(w.get("title", "")).strip()
    ]
    return ScholarProfile(
        name=name,
        org=org,
        research_directions=directions,
        representative_works=works,
        affiliation=str(raw.get("affiliation", "")),
        citation_count=int(raw.get("citation_count", 0) or 0),
        publication_count=int(raw.get("publication_count", 0) or 0),
        hindex=int(raw.get("hindex", 0) or 0),
        data_source="web_search",
    )
