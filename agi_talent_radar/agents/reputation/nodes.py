"""舆情风险核查链：消歧 → 模板检索 → 事件分类 → 红黄绿分级。

设计原则：宁可漏报不可错杀。每条命中先过身份消歧，rejected 不参与分级；
所有事件必须带可点击来源 URL。
"""
from __future__ import annotations

from collections.abc import Callable

from agi_talent_radar.core import llm_client
from agi_talent_radar.core.connectors import ConnectorUnavailableError, Fact, search_web

from agi_talent_radar.agents.reputation.models import (
    PersonIdentity,
    ReputationEvent,
    ReputationReport,
    SearchHit,
)

SERIOUS_CATEGORIES = {"学术不端", "抄袭争议", "职业诚信"}
NEGATIVE_CATEGORIES = SERIOUS_CATEGORIES | {"项目争议", "商业纠纷", "公开冲突", "法律纠纷", "其他负面"}

RISK_QUERY_TEMPLATES: tuple[tuple[str, str], ...] = (
    ("{name} {org} 抄袭", ""),
    ("{name} {org} 学术不端", ""),
    ("{name} 撤稿", ""),
    ("{name} 论文 争议", ""),
    ("{name} 学术 纠纷", ""),
    ("{name}", "pubpeer.com"),
    ("{name}", "retractionwatch.com"),
    ("{name} 争议", ""),
    ("{name} 纠纷", ""),
    ("{name} 造假", ""),
    ("{name} 负面", ""),
    ("{name} 塌房", ""),
)

EVENT_CLASSIFIER_PROMPT = """
你是公开信息舆情核查 Agent。只输出 JSON 对象，顶层字段必须是 events。

任务：根据检索结果判断是否存在针对目标人物的公开职业声誉风险事件。

目标人物：
- 姓名：{name}
- 机构：{org}
- 研究方向：{direction}

铁律：
1. 同名不同人是最大风险。每条候选事件必须先做身份消歧：
   confirmed = 文本同时提到姓名且机构/方向/成果可对应；
   probable = 只提到姓名，机构方向未提但不矛盾；
   rejected = 机构、方向、年代明显对不上，或只是重名。
2. 只允许输出这些 category：学术不端 / 抄袭争议 / 项目争议 / 商业纠纷 / 公开冲突 / 法律纠纷 / 职业诚信 / 其他负面 / 误报。
   - 项目争议：开源/商业项目涉嫌抄袭、索贿、刷量、虚假宣传、社区塌房等
   - 商业纠纷：劳资、股权、违约、欠款等
   - 职业诚信：简历/学历造假、冒充资历、虚构经历等
3. 内容只是正常学术讨论、新闻报道中性提及、或明显广告，归入 误报。
4. 严格区分「事件主体」与「事件对象」：summary 必须写清是谁对谁做了什么。
   例如"A 指控 B 抄袭"，目标人物是 A 则事件是"A 发起抄袭指控"，是 B 则是"B 被指控抄袭"。
   绝不可把报道里出现的人都当成目标人物的负面。
5. 每条事件必须给出来源。优先用 source_urls（引用输入 hit 中出现的 url）；
   若 hit 无 url（聚合摘要类结果常缺链接），改在 source_refs 里填该 hit 的 title 原文，作为来源标识。不得编造不存在的来源。
6. status 填写事件当前状态：进行中 / 已澄清 / 已有结论 / 不明。
7. 没有可靠命中时 events 输出空数组，不要硬凑。

每条 event 输出字段：category, identity_match, summary（50 字内事实转述，不做定性评价，必须点明主客体）, status, source_urls, source_refs（url 缺失时填来源标题）, publish_date。
""".strip()


def build_queries(identity: PersonIdentity) -> list[tuple[str, str]]:
    queries = []
    for template, domain in RISK_QUERY_TEMPLATES:
        query = " ".join(
            part for part in template.format(name=identity.name, org=identity.org).split() if part
        )
        queries.append((query, domain))
    return queries


def collect_hits(
    identity: PersonIdentity,
    search_fn: Callable[..., list[Fact]] = search_web,
    count_per_query: int = 8,
) -> tuple[list[SearchHit], list[str]]:
    """按模板检索并去重；单个查询失败降级为 warning，不中断整体。"""
    hits: list[SearchHit] = []
    warnings: list[str] = []
    seen_urls: set[str] = set()
    for query, domain in build_queries(identity):
        try:
            facts = search_fn(query, count=count_per_query, domain_filter=domain)
        except ConnectorUnavailableError as exc:
            warnings.append(str(exc))
            continue
        for fact in facts:
            if fact.source_url and fact.source_url in seen_urls:
                continue
            seen_urls.add(fact.source_url)
            hits.append(
                SearchHit(
                    query=query,
                    title=str(fact.payload.get("title", "")),
                    content=str(fact.payload.get("content", ""))[:600],
                    url=fact.source_url,
                    media=str(fact.payload.get("media", "")),
                    publish_date=str(fact.payload.get("publish_date", "")),
                )
            )
    return hits, warnings


def classify_events(identity: PersonIdentity, hits: list[SearchHit]) -> list[ReputationEvent]:
    if not hits:
        return []
    response = llm_client.call_llm_json(
        EVENT_CLASSIFIER_PROMPT.format(
            name=identity.name,
            org=identity.org or "未知",
            direction=identity.direction or "未知",
        ),
        {
            "hits": [hit.model_dump() for hit in hits],
        },
        temperature=0.1,
    )
    events: list[ReputationEvent] = []
    # 已知来源：URL 优先，无 URL 时用标题做来源标识（智谱聚合结果常缺 link）
    known_urls = {hit.url for hit in hits if hit.url}
    known_titles = {hit.title for hit in hits if hit.title}
    for raw in response.get("events", []):
        if not isinstance(raw, dict):
            continue
        raw_urls = [str(u) for u in raw.get("source_urls", []) if u]
        # URL 在已知集合里就直接用；否则尝试用来源标注匹配已知标题
        verified_urls = [u for u in raw_urls if u in known_urls]
        source_refs = raw.get("source_refs", [])  # LLM 可用标题/媒体做来源标注
        if not verified_urls:
            # URL 缺失或不在已知集，改用标题匹配补来源
            for ref in source_refs:
                ref_str = str(ref)
                for title in known_titles:
                    if ref_str and ref_str in title:
                        verified_urls.append(f"来源:{title[:40]}")
                        break
        event = ReputationEvent(
            category=str(raw.get("category", "误报")),
            identity_match=str(raw.get("identity_match", "rejected")),
            summary=str(raw.get("summary", "")),
            status=str(raw.get("status", "不明")),
            source_urls=verified_urls,
            publish_date=str(raw.get("publish_date", "")),
        )
        if event.category == "误报" or event.identity_match == "rejected":
            continue
        # 有 URL 或标题来源都算可追溯，不再因缺 URL 直接丢弃
        if not event.source_urls:
            continue
        events.append(event)
    return events


def grade_risk(events: list[ReputationEvent]) -> tuple[str, str]:
    confirmed = [e for e in events if e.identity_match == "confirmed"]
    probable = [e for e in events if e.identity_match == "probable"]
    serious_confirmed = [
        e for e in confirmed if e.category in SERIOUS_CATEGORIES and e.status != "已澄清"
    ]
    if serious_confirmed:
        return "red", f"确认身份的学术不端/抄袭/职业诚信问题 {len(serious_confirmed)} 起，需人工复核。"
    negative_confirmed = [
        e for e in confirmed if e.category in NEGATIVE_CATEGORIES and e.status != "已澄清"
    ]
    serious_probable = [e for e in probable if e.category in SERIOUS_CATEGORIES]
    if negative_confirmed or serious_probable:
        return "yellow", "存在确认身份的一般负面事件或疑似学术争议，建议人工确认。"
    return "green", "未发现可靠来源的负面舆情。"


def run_reputation_check(
    identity: PersonIdentity,
    search_fn: Callable[..., list[Fact]] = search_web,
) -> ReputationReport:
    hits, warnings = collect_hits(identity, search_fn=search_fn)
    events = classify_events(identity, hits)
    level, rationale = grade_risk(events)
    return ReputationReport(
        level=level,
        events=events,
        hits=hits,
        rationale=rationale,
        warnings=warnings,
    )
