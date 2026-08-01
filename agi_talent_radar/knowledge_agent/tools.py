"""ReAct Agent 工具注册表：只读检索工具 + 门控写入工具。

每个工具：{name, label, description, parameters(JSON schema), handler(ctx, args) -> dict, gated}。
gated=True 的工具 handler 不写库，只返回 {requires_confirmation, kind, payload}，
真正的写入由 execute_gated_action 在用户决策后执行。
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from agi_talent_radar.core.db.orm import (
    EvaluationORM,
    ExternalFactORM,
    PersonORM,
    ResumeSubmissionORM,
)

# 喂回 LLM 的单次工具结果最大字符数
TOOL_RESULT_MAX_CHARS = 2000


class ToolContext:
    """一次回答的工具执行上下文：db session + 引用注册表（citation_id 形如 c1/c2）。"""

    def __init__(self, session, existing_sources: list[dict] | None = None) -> None:
        self.session = session
        self.sources: list[dict[str, Any]] = list(existing_sources or [])

    def register_source(self, type: str, title: str, url: str = "", status: str = "") -> str:
        citation_id = f"c{len(self.sources) + 1}"
        self.sources.append(
            {"id": citation_id, "type": type, "title": title, "url": url, "status": status}
        )
        return citation_id


# ---------------------------------------------------------------------------
# 库内查询辅助
# ---------------------------------------------------------------------------


def _person_brief(person: PersonORM) -> dict[str, Any]:
    return {
        "person_id": person.id,
        "name": person.name,
        "org": person.org,
        "direction": person.direction,
        "schools": person.schools or [],
        "person_type": person.person_type,
    }


def _latest_submission(session, person_id: str) -> ResumeSubmissionORM | None:
    return (
        session.query(ResumeSubmissionORM)
        .filter_by(person_id=person_id)
        .order_by(ResumeSubmissionORM.created_at.desc())
        .first()
    )


def _latest_evaluation(session, person_id: str) -> EvaluationORM | None:
    return (
        session.query(EvaluationORM)
        .filter_by(person_id=person_id, status="completed")
        .order_by(EvaluationORM.created_at.desc())
        .first()
    )


def _filter_persons(session, args: dict[str, Any]) -> list[PersonORM]:
    """姓名/方向走 SQL，学校/学历在 Python 侧过滤（池子小）。"""
    name = str(args.get("name") or "").strip()
    school = str(args.get("school") or "").strip()
    direction = str(args.get("direction") or "").strip()
    degree = str(args.get("degree") or "").strip()
    query = session.query(PersonORM)
    if name:
        query = query.filter(PersonORM.name.like(f"%{name}%"))
    if direction:
        query = query.filter(PersonORM.direction.like(f"%{direction}%"))
    persons = query.limit(100).all()
    if school:
        persons = [
            p
            for p in persons
            if school in (p.org or "") or any(school in str(s) for s in (p.schools or []))
        ]
    if degree:
        persons = [p for p in persons if _person_has_degree(session, p, degree)]
    return persons


def _person_has_degree(session, person: PersonORM, degree: str) -> bool:
    submission = _latest_submission(session, person.id)
    structured = (submission.structured or {}) if submission else {}
    for item in structured.get("education") or []:
        if isinstance(item, dict) and degree in str(item.get("degree") or ""):
            return True
        if isinstance(item, str) and degree in item:
            return True
    return False


# ---------------------------------------------------------------------------
# 只读工具：库内
# ---------------------------------------------------------------------------


def tool_search_knowledge(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    query = str(args.get("query") or "").strip()
    if not query:
        return {"hits": [], "summary": "查询为空"}
    top_k = max(1, min(20, int(args.get("top_k") or 8)))
    from agi_talent_radar.core.embedding import embed_texts
    from agi_talent_radar.core.vector_store import QdrantVectorStore

    vector = embed_texts([query])[0]
    try:
        hits = QdrantVectorStore().search(vector, top_k=top_k)
    except Exception as exc:  # noqa: BLE001
        return {"hits": [], "summary": f"向量库暂不可用：{exc}"}
    items = []
    for hit in hits:
        payload = hit.payload or {}
        text = str(payload.get("text") or "")
        citation_id = ctx.register_source(
            str(payload.get("record_type") or "knowledge"),
            text[:40],
            status=str(payload.get("fact_status") or ""),
        )
        items.append(
            {
                "citation_id": citation_id,
                "text": text,
                "person_id": str(payload.get("person_id") or ""),
                "record_type": str(payload.get("record_type") or ""),
                "fact_status": str(payload.get("fact_status") or ""),
                "source": str(payload.get("source") or ""),
                "score": round(float(hit.score), 4),
            }
        )
    return {"hits": items, "summary": f"命中 {len(items)} 条事实"}


def tool_search_persons(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    persons = _filter_persons(ctx.session, args)
    results = []
    for p in persons[:20]:
        # 每个人都注册引用，给模型可引用的 citation_id，防止它编造角标
        citation_id = ctx.register_source("talent_pool", f"人才库：{p.name}", status="confirmed")
        results.append({"citation_id": citation_id, **_person_brief(p)})
    return {"persons": results, "summary": f"命中 {len(results)} 人"}


def tool_get_person_profile(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    person = ctx.session.get(PersonORM, str(args.get("person_id") or ""))
    if person is None:
        return {"found": False, "summary": "人物不存在"}
    submission = _latest_submission(ctx.session, person.id)
    structured = (submission.structured or {}) if submission else {}
    citation_id = ctx.register_source("resume", f"{person.name} 的简历画像", status="confirmed")
    return {
        "found": True,
        "citation_id": citation_id,
        "person": _person_brief(person),
        "has_resume": submission is not None,
        "education": structured.get("education") or [],
        "experiences": structured.get("experiences") or [],
        "skills": structured.get("skills") or [],
        "publications": structured.get("publications") or [],
        "target_role": structured.get("target_role") or "",
        "summary": f"已获取 {person.name} 的简历画像",
    }


def tool_get_person_evaluation(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    person = ctx.session.get(PersonORM, str(args.get("person_id") or ""))
    if person is None:
        return {"found": False, "summary": "人物不存在"}
    evaluation = _latest_evaluation(ctx.session, person.id)
    if evaluation is None:
        return {"found": True, "has_evaluation": False, "summary": f"{person.name} 暂无评估记录"}
    citation_id = ctx.register_source("evaluation", f"{person.name} 的评估报告", status="confirmed")
    academic = evaluation.academic_report or {}
    return {
        "found": True,
        "has_evaluation": True,
        "citation_id": citation_id,
        "overall_score": evaluation.overall_score,
        "level": evaluation.level,
        "tier": evaluation.tier,
        "one_liner": evaluation.one_liner,
        "stage_profile": evaluation.stage_profile,
        "core_strengths": evaluation.core_strengths or [],
        "potential_risks": evaluation.potential_risks or [],
        "recommended_tracks": evaluation.recommended_tracks or [],
        "academic_summary": {
            "verdict": academic.get("verdict", ""),
            "warnings": (academic.get("warnings") or [])[:5],
        },
        "evaluated_at": str(evaluation.completed_at or evaluation.created_at),
        "summary": f"已获取 {person.name} 的评估（总分 {evaluation.overall_score}）",
    }


def tool_get_resume_versions(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    person = ctx.session.get(PersonORM, str(args.get("person_id") or ""))
    if person is None:
        return {"found": False, "summary": "人物不存在"}
    citation_id = ctx.register_source("resume", f"{person.name} 的简历版本历史", status="confirmed")
    submissions = (
        ctx.session.query(ResumeSubmissionORM)
        .filter_by(person_id=person.id)
        .order_by(ResumeSubmissionORM.created_at.asc())
        .all()
    )
    versions = []
    for submission in submissions:
        structured = submission.structured or {}
        versions.append(
            {
                "submission_id": submission.id,
                "created_at": str(submission.created_at),
                "education": structured.get("education") or [],
                "skills": structured.get("skills") or [],
                "publications": structured.get("publications") or [],
                "experiences": [
                    f"{e.get('organization', '')} {e.get('role', '')}".strip()
                    for e in (structured.get("experiences") or [])
                    if isinstance(e, dict)
                ],
            }
        )
    return {
        "found": True,
        "citation_id": citation_id,
        "person": _person_brief(person),
        "versions": versions,
        "summary": f"{person.name} 共 {len(versions)} 个简历版本",
    }


def tool_aggregate_persons(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    persons = _filter_persons(ctx.session, args)
    metric = str(args.get("metric") or "count")
    top_n = max(1, min(50, int(args.get("top_n") or 10)))
    rows = []
    for person in persons:
        row = _person_brief(person)
        if metric == "avg_score":
            evaluation = _latest_evaluation(ctx.session, person.id)
            row["score"] = evaluation.overall_score if evaluation else None
        elif metric == "pub_count":
            submission = _latest_submission(ctx.session, person.id)
            structured = (submission.structured or {}) if submission else {}
            row["pub_count"] = len(structured.get("publications") or [])
        rows.append(row)
    if metric == "avg_score":
        rows = sorted((r for r in rows if r["score"] is not None), key=lambda r: r["score"], reverse=True)
    elif metric == "pub_count":
        rows = sorted(rows, key=lambda r: r["pub_count"], reverse=True)
    rows = rows[:top_n]
    citation_id = ctx.register_source("talent_pool", "人才库统计聚合", status="confirmed")
    return {
        "metric": metric,
        "citation_id": citation_id,
        "total": len(persons),
        "rows": rows,
        "summary": f"共 {len(persons)} 人，按 {metric} 给出前 {len(rows)} 名",
    }


# ---------------------------------------------------------------------------
# 只读工具：外部连接器
# ---------------------------------------------------------------------------


def tool_search_scholar_aminer(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    from agi_talent_radar.core.connectors.aminer_rest import search_aminer_scholar

    name_variants = [str(v) for v in (args.get("name_variants") or []) if str(v).strip()]
    facts = search_aminer_scholar(
        str(args.get("name") or ""),
        org=str(args.get("org") or ""),
        name_variants=name_variants,
    )
    scholars = []
    for fact in facts:
        citation_id = ctx.register_source(
            "aminer", f"AMiner 学者：{fact.payload.get('name', '')}", fact.source_url, "pending"
        )
        scholars.append({"citation_id": citation_id, **fact.payload})
    tried = sorted({str(f.payload.get("query_name") or "") for f in facts if f.payload.get("query_name")})
    suffix = f"（尝试变体：{'/'.join(tried)}）" if tried else ""
    return {"scholars": scholars, "summary": f"AMiner 命中 {len(scholars)} 位学者{suffix}"}


def tool_search_papers_aminer(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    from agi_talent_radar.core.connectors.aminer_rest import search_aminer_papers_by_title

    facts = search_aminer_papers_by_title(str(args.get("title") or ""))
    papers = []
    for fact in facts:
        citation_id = ctx.register_source(
            "aminer", str(fact.payload.get("title") or ""), fact.source_url, "pending"
        )
        papers.append({"citation_id": citation_id, **fact.payload})
    return {"papers": papers, "summary": f"AMiner 命中 {len(papers)} 篇论文"}


def tool_search_papers_openalex(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    from agi_talent_radar.core.connectors.openalex import search_author_works, search_works

    query = str(args.get("query") or "").strip()
    author = str(args.get("author") or "").strip()
    since_year = args.get("since_year")
    if author:
        facts = search_author_works(author, since_year=int(since_year) if since_year else None)
    elif query:
        facts = search_works(query)
    else:
        return {"papers": [], "summary": "query 与 author 至少提供一个"}
    papers = []
    for fact in facts:
        citation_id = ctx.register_source(
            "openalex", str(fact.payload.get("title") or ""), fact.source_url, "pending"
        )
        papers.append({"citation_id": citation_id, **fact.payload})
    return {"papers": papers, "summary": f"OpenAlex 命中 {len(papers)} 篇论文"}


def tool_search_dblp(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    from agi_talent_radar.core.connectors.dblp import search_author_pubs

    facts = search_author_pubs(str(args.get("name") or ""))
    papers = []
    for fact in facts:
        citation_id = ctx.register_source(
            "dblp", str(fact.payload.get("title") or ""), fact.source_url, "pending"
        )
        papers.append({"citation_id": citation_id, **fact.payload})
    return {"papers": papers, "summary": f"DBLP 命中 {len(papers)} 篇论文"}


def tool_search_web(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    from agi_talent_radar.core.connectors.web_search import search_web

    facts = search_web(str(args.get("query") or ""))
    items = []
    for fact in facts:
        citation_id = ctx.register_source(
            "web_search", str(fact.payload.get("title") or ""), fact.source_url, "pending"
        )
        items.append({"citation_id": citation_id, **fact.payload, "url": fact.source_url})
    return {"results": items, "summary": f"网络检索命中 {len(items)} 条"}


def tool_check_reputation(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    """舆情双面监测：综合查询 + 负面信号查询各一次，分组返回。

    负面信号只是关键词命中，真伪需模型甄别；大部分人查不到负面，属正常。
    """
    from agi_talent_radar.core.connectors.base import ConnectorUnavailableError
    from agi_talent_radar.core.connectors.web_search import search_web

    name = str(args.get("name") or "").strip()
    org = str(args.get("org") or "").strip()
    subject = f"{name} {org}".strip()
    errors: list[str] = []

    def _collect(query: str) -> list[dict[str, Any]]:
        try:
            facts = search_web(query, count=8)
        except ConnectorUnavailableError as exc:
            errors.append(str(exc))
            return []
        items = []
        for fact in facts:
            citation_id = ctx.register_source(
                "web_search", str(fact.payload.get("title") or ""), fact.source_url, "pending"
            )
            items.append({"citation_id": citation_id, **fact.payload, "url": fact.source_url})
        return items

    general = _collect(subject)
    negative = _collect(f"{subject} 争议 学术不端 撤稿 造假 抄袭")
    result: dict[str, Any] = {
        "general": general,
        "negative_signals": negative,
        "note": "negative_signals 仅为负面关键词命中，不代表确有其事；为空即未发现公开负面记录",
        "summary": f"舆情双面监测：综合信息 {len(general)} 条，负面关键词命中 {len(negative)} 条",
    }
    if errors:
        result["errors"] = errors
    return result


def tool_get_github_repo(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    from agi_talent_radar.core.connectors.github import get_repo_stats

    fact = get_repo_stats(str(args.get("repo") or ""))
    citation_id = ctx.register_source(
        "github", f"GitHub 仓库：{fact.payload.get('repo', '')}", fact.source_url, "pending"
    )
    return {"citation_id": citation_id, **fact.payload, "summary": f"已获取 {fact.payload.get('repo', '')} 的仓库信息"}


# ---------------------------------------------------------------------------
# 门控工具（handler 不写库，只返回待确认动作）
# ---------------------------------------------------------------------------


def _gated(kind: str, payload: dict[str, Any]) -> dict[str, Any]:
    return {"requires_confirmation": True, "kind": kind, "payload": payload, "summary": "等待用户确认"}


def tool_select_person(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    return _gated("select_person", {"candidates": args.get("candidates") or []})


def tool_propose_add_person(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    return _gated(
        "propose_add_person",
        {
            "name": str(args.get("name") or ""),
            "org": str(args.get("org") or ""),
            "direction": str(args.get("direction") or ""),
            "note": str(args.get("note") or ""),
        },
    )


def tool_resolve_fact_conflict(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    return _gated(
        "resolve_fact_conflict",
        {
            "fact_id": args.get("fact_id"),
            "chosen_payload": args.get("chosen_payload") or {},
            "note": str(args.get("note") or ""),
        },
    )


def tool_ask_clarification(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    return _gated(
        "clarify",
        {
            "question": str(args.get("question") or ""),
            "options": args.get("options") or [],
        },
    )


def execute_gated_action(session, kind: str, payload: dict[str, Any], decision: dict[str, Any]) -> str:
    """用户决策后执行门控动作（真正写库只发生在这里），返回喂回 LLM 的文本。"""
    decision = decision or {}
    if kind == "select_person":
        person = session.get(PersonORM, str(decision.get("choice") or ""))
        if person is None:
            return "用户选择的人物不存在。"
        return f"用户已选定人物：{json.dumps(_person_brief(person), ensure_ascii=False)}"

    if kind == "propose_add_person":
        if not decision.get("approved"):
            return "用户暂不将该人物加入人才库。"
        from agi_talent_radar.core.persons import get_or_create_person

        person = get_or_create_person(
            session,
            name=str(payload.get("name") or ""),
            org=str(payload.get("org") or ""),
            direction=str(payload.get("direction") or ""),
            person_type="guest",
        )
        note = str(payload.get("note") or "")
        if note:
            person.identifiers = {**(person.identifiers or {}), "agent_note": note}
        session.commit()
        return f"已将 {person.name} 加入人才库（guest，待评估），person_id={person.id}。"

    if kind == "resolve_fact_conflict":
        if not decision.get("approved"):
            return "用户暂不裁定该冲突，保持现状。"
        fact = session.get(ExternalFactORM, int(payload.get("fact_id") or 0))
        if fact is None:
            return "冲突事实不存在。"
        chosen = decision.get("chosen_payload") or payload.get("chosen_payload") or {}
        note = str(decision.get("note") or payload.get("note") or "")
        fact.payload = {**(fact.payload or {}), **chosen, "resolution_note": note}
        fact.verification_status = "confirmed"
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        conflicts = []
        if fact.identity_key:
            conflicts = (
                session.query(ExternalFactORM)
                .filter(
                    ExternalFactORM.identity_key == fact.identity_key,
                    ExternalFactORM.id != fact.id,
                    ExternalFactORM.superseded_at.is_(None),
                )
                .all()
            )
        for other in conflicts:
            other.verification_status = "superseded"
            other.superseded_at = now
        session.commit()
        return f"裁定已落库：事实 #{fact.id} 已确认，{len(conflicts)} 条冲突版本已标记 superseded。"

    if kind == "clarify":
        answer = str(decision.get("answer") or decision.get("choice") or "")
        return f"用户回答：{answer}"

    return f"未知的门控动作类型：{kind}"


# ---------------------------------------------------------------------------
# 注册表
# ---------------------------------------------------------------------------


def _str(desc: str) -> dict[str, Any]:
    return {"type": "string", "description": desc}


def _obj(properties: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    return {"type": "object", "properties": properties, "required": required or []}


TOOLS: list[dict[str, Any]] = [
    {
        "name": "search_knowledge",
        "label": "检索人才知识库",
        "description": "在人才知识向量库语义检索（简历画像/原文/评估/外部事实），返回带 citation_id 的事实。",
        "parameters": _obj(
            {"query": _str("检索问题或关键词"), "top_k": {"type": "integer", "description": "返回条数，默认 8"}},
            ["query"],
        ),
        "handler": tool_search_knowledge,
        "gated": False,
    },
    {
        "name": "search_persons",
        "label": "筛选库内人物",
        "description": "按姓名/学校/方向/学历筛选人才库人物，返回候选人卡片（含 person_id）。",
        "parameters": _obj(
            {
                "name": _str("姓名（可空）"),
                "school": _str("学校关键词（可空）"),
                "direction": _str("研究方向关键词（可空）"),
                "degree": _str("学历关键词，如 博士/硕士（可空）"),
            }
        ),
        "handler": tool_search_persons,
        "gated": False,
    },
    {
        "name": "get_person_profile",
        "label": "读取人物简历画像",
        "description": "读取人物最新简历的结构化画像（教育/实习/技能/论文自述）。",
        "parameters": _obj({"person_id": _str("人物 ID")}, ["person_id"]),
        "handler": tool_get_person_profile,
        "gated": False,
    },
    {
        "name": "get_person_evaluation",
        "label": "读取人物评估结果",
        "description": "读取人物最新评估：总分/层级/优势/风险/论文核验结论/推荐 Track。",
        "parameters": _obj({"person_id": _str("人物 ID")}, ["person_id"]),
        "handler": tool_get_person_evaluation,
        "gated": False,
    },
    {
        "name": "get_resume_versions",
        "label": "读取简历版本时间线",
        "description": "读取人物全部简历版本（按时间升序的技能/论文/实习列表），用于成长对比。",
        "parameters": _obj({"person_id": _str("人物 ID")}, ["person_id"]),
        "handler": tool_get_resume_versions,
        "gated": False,
    },
    {
        "name": "aggregate_persons",
        "label": "库内统计排名",
        "description": "库内统计排名：按 degree/school/direction 过滤 + count/avg_score/pub_count 聚合。",
        "parameters": _obj(
            {
                "degree": _str("学历过滤（可空）"),
                "school": _str("学校过滤（可空）"),
                "direction": _str("方向过滤（可空）"),
                "metric": _str("count | avg_score | pub_count"),
                "top_n": {"type": "integer", "description": "返回前 N 名，默认 10"},
            }
        ),
        "handler": tool_aggregate_persons,
        "gated": False,
    },
    {
        "name": "search_scholar_aminer",
        "label": "AMiner 学者检索",
        "description": "按姓名检索 AMiner 学者画像（引用数/单位/研究兴趣），用于库外人物调查。中文名自动带拼音变体；拼写不确定时用 name_variants 多给几个变体。org 仅作排序提示。",
        "parameters": _obj(
            {
                "name": _str("姓名"),
                "name_variants": {"type": "array", "items": {"type": "string"}, "description": "姓名变体（拼音/英文名/常见拼写，可空）"},
                "org": _str("机构（可空，仅排序提示）"),
            },
            ["name"],
        ),
        "handler": tool_search_scholar_aminer,
        "gated": False,
    },
    {
        "name": "search_papers_aminer",
        "label": "AMiner 论文检索",
        "description": "按标题检索 AMiner 论文（免费，引用数为分桶值），论文检索的首选；查不到再换 OpenAlex 兜底。",
        "parameters": _obj({"title": _str("论文标题或关键词")}, ["title"]),
        "handler": tool_search_papers_aminer,
        "gated": False,
    },
    {
        "name": "search_papers_openalex",
        "label": "OpenAlex 论文检索",
        "description": "兜底工具：仅当 AMiner 无结果、或必须拿精确被引数/撤稿标记时使用（限流频繁，能不用就不用）。",
        "parameters": _obj(
            {
                "query": _str("论文标题关键词（可空）"),
                "author": _str("作者姓名（可空）"),
                "since_year": {"type": "integer", "description": "起始年份（可空）"},
            }
        ),
        "handler": tool_search_papers_openalex,
        "gated": False,
    },
    {
        "name": "search_dblp",
        "label": "DBLP 发文检索",
        "description": "按作者名检索 DBLP 论文（题名/venue/年份），用于发文核验。",
        "parameters": _obj({"name": _str("作者姓名")}, ["name"]),
        "handler": tool_search_dblp,
        "gated": False,
    },
    {
        "name": "search_web",
        "label": "联网检索舆情",
        "description": "联网检索公开信息/舆情，返回标题/摘要/发布时间/链接。",
        "parameters": _obj({"query": _str("检索词")}, ["query"]),
        "handler": tool_search_web,
        "gated": False,
    },
    {
        "name": "check_reputation",
        "label": "舆情双面监测",
        "description": "人物舆情背调的首选：综合查询+负面信号查询双轨返回。需要看正/负两面舆情时必须用它，而不是只跑一次 search_web。",
        "parameters": _obj({"name": _str("人物姓名"), "org": _str("机构（可空）")}, ["name"]),
        "handler": tool_check_reputation,
        "gated": False,
    },
    {
        "name": "get_github_repo",
        "label": "GitHub 仓库核查",
        "description": "核查 GitHub 仓库 stars/近 90 天提交活跃度/描述，接受 owner/repo 或完整 URL。",
        "parameters": _obj({"repo": _str("owner/repo 或 GitHub URL")}, ["repo"]),
        "handler": tool_get_github_repo,
        "gated": False,
    },
    {
        "name": "select_person",
        "label": "请用户选定人物",
        "description": "search_persons 命中多个不同人时调用，请用户从候选中选定一位。",
        "parameters": _obj(
            {
                "candidates": {
                    "type": "array",
                    "description": "候选人物列表",
                    "items": _obj(
                        {"person_id": _str("人物 ID"), "name": _str("姓名"), "org": _str("机构")},
                        ["person_id", "name"],
                    ),
                }
            },
            ["candidates"],
        ),
        "handler": tool_select_person,
        "gated": True,
    },
    {
        "name": "propose_add_person",
        "label": "提议加入人才库",
        "description": "库外人物调查完成后，提议将其加入人才库（需用户确认）。",
        "parameters": _obj(
            {
                "name": _str("姓名"),
                "org": _str("机构（可空）"),
                "direction": _str("研究方向（可空）"),
                "note": _str("调查结论摘要（可空）"),
            },
            ["name"],
        ),
        "handler": tool_propose_add_person,
        "gated": True,
    },
    {
        "name": "resolve_fact_conflict",
        "label": "提请事实冲突裁定",
        "description": "外部事实冲突时提请用户裁定：确认 chosen_payload 并将冲突版本标记 superseded。",
        "parameters": _obj(
            {
                "fact_id": {"type": "integer", "description": "冲突事实 ID"},
                "chosen_payload": {"type": "object", "description": "选定的事实内容"},
                "note": _str("备注（可空）"),
            },
            ["fact_id", "chosen_payload"],
        ),
        "handler": tool_resolve_fact_conflict,
        "gated": True,
    },
    {
        "name": "ask_clarification",
        "label": "向用户追问澄清",
        "description": "问题缺主语或意图不明时，向用户追问澄清（可给选项）。",
        "parameters": _obj(
            {
                "question": _str("追问内容"),
                "options": {"type": "array", "items": _str("选项"), "description": "可选项（可空）"},
            },
            ["question"],
        ),
        "handler": tool_ask_clarification,
        "gated": True,
    },
]

TOOLS_BY_NAME = {tool["name"]: tool for tool in TOOLS}


def tools_schema() -> list[dict[str, Any]]:
    """OpenAI tools 参数格式。"""
    return [
        {
            "type": "function",
            "function": {
                "name": tool["name"],
                "description": tool["description"],
                "parameters": tool["parameters"],
            },
        }
        for tool in TOOLS
    ]
