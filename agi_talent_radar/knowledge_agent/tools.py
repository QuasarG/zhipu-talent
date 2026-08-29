"""ReAct Agent 工具注册表：只读检索工具 + 门控写入工具。

每个工具：{name, label, description, parameters(JSON schema), handler(ctx, args) -> dict, gated}。
gated=True 的工具 handler 不写库，只返回 {requires_confirmation, kind, payload}，
真正的写入由 execute_gated_action 在用户决策后执行。
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from typing import Any

from agi_talent_radar.core.db.orm import (
    CandidateJdAssessmentORM,
    CandidateORM,
    EvaluationORM,
    ExternalFactORM,
    JdEntryORM,
    PersonORM,
    ResumeSubmissionORM,
)

# 喂回 LLM 的单次工具结果最大字符数
TOOL_RESULT_MAX_CHARS = 2000

# 知识库空态缓存：(检查时间戳, 是否为空)，TTL 内不重复 count
_KB_EMPTY_TTL_SECONDS = 300
_KB_EMPTY_CACHE: tuple[float, bool] | None = None


class ToolContext:
    """一次回答的工具执行上下文：db session + 引用注册表（citation_id 形如 c1/c2）。"""

    def __init__(self, session, existing_sources: list[dict] | None = None) -> None:
        self.session = session
        self.sources: list[dict[str, Any]] = list(existing_sources or [])

    def register_source(
        self,
        type: str,
        title: str,
        url: str = "",
        status: str = "",
        meta: dict[str, Any] | None = None,
    ) -> str:
        citation_id = f"c{len(self.sources) + 1}"
        source: dict[str, Any] = {"id": citation_id, "type": type, "title": title, "url": url, "status": status}
        if meta:
            source["meta"] = meta
        self.sources.append(source)
        return citation_id


# ---------------------------------------------------------------------------
# 库内查询辅助
# ---------------------------------------------------------------------------


def _person_brief(person: PersonORM, session=None) -> dict[str, Any]:
    group_name = ""
    if session and person.group_id:
        from agi_talent_radar.core.db.orm import TalentGroupORM
        g = session.get(TalentGroupORM, person.group_id)
        if g:
            group_name = g.name
    return {
        "person_id": person.id,
        "name": person.name,
        "org": person.org,
        "direction": person.direction,
        "schools": person.schools or [],
        "person_type": person.person_type,
        "group": group_name or None,
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


_ADMISSION_DECISION_LABELS = {"interview": "进入面试", "no_interview": "不进入面试"}


def _person_jd_assessments(session, person_id: str) -> list[CandidateJdAssessmentORM]:
    """新准入表（一岗一评）的有效评估，按时间倒序。"""
    return (
        session.query(CandidateJdAssessmentORM)
        .join(CandidateORM, CandidateJdAssessmentORM.candidate_id == CandidateORM.id)
        .filter(
            CandidateORM.person_id == person_id,
            CandidateJdAssessmentORM.status == "completed",
            CandidateJdAssessmentORM.is_valid.is_(True),
        )
        .order_by(CandidateJdAssessmentORM.created_at.desc())
        .all()
    )


def _admission_view(session, assessment: CandidateJdAssessmentORM, jd_title: str) -> dict[str, Any]:
    """单条准入评估的紧凑视图（控制在 TOOL_RESULT_MAX_CHARS 内，给 LLM 的一岗一评摘要）。"""
    tasks = [
        {
            "task_id": str(t.get("task_id") or ""),
            "level": t.get("level"),
            "confidence": t.get("confidence"),
        }
        for t in (assessment.task_assessments or [])
        if isinstance(t, dict)
    ]
    return {
        "jd_title": jd_title,
        "decision": _ADMISSION_DECISION_LABELS.get(assessment.decision, assessment.decision),
        "total_score": round(float(assessment.total_score or 0), 1),
        "tasks": tasks,
    }


def _person_citation_meta(session, person: PersonORM) -> dict[str, Any]:
    """人物引用的 meta：brief + 最新评估。前端凭 meta.person_id 渲染详细档案卡。"""
    meta = _person_brief(person, session)
    from agi_talent_radar.services.person_assessment_view import get_person_assessment_view

    view = get_person_assessment_view(session, person.id)
    if view and view["latest"]:
        latest = view["latest"]
        meta["overall_score"] = latest["score"]
        meta["assessment_source"] = latest["source_type"]
        if latest["source_type"] == "interview_admission":
            meta["admission_decision"] = _ADMISSION_DECISION_LABELS.get(
                latest["decision"], latest["decision"]
            )
        elif view["general_evaluation"]:
            meta["level"] = view["general_evaluation"]["level"]
            meta["tier"] = view["general_evaluation"]["tier"]
    return meta


def _filter_persons(session, args: dict[str, Any]) -> list[PersonORM]:
    """姓名/方向走 SQL，学校/学历/分组在 Python 侧过滤（池子小）。"""
    name = str(args.get("name") or "").strip()
    school = str(args.get("school") or "").strip()
    direction = str(args.get("direction") or "").strip()
    degree = str(args.get("degree") or "").strip()
    group = str(args.get("group") or "").strip()
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
    if group:
        # 按分组名模糊匹配或 "ungrouped" 查未分组
        from agi_talent_radar.core.db.orm import TalentGroupORM
        if group.lower() == "ungrouped" or group == "未分组":
            persons = [p for p in persons if not p.group_id]
        else:
            group_ids = {
                g.id for g in session.query(TalentGroupORM).filter(TalentGroupORM.name.like(f"%{group}%")).all()
            }
            persons = [p for p in persons if p.group_id in group_ids]
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

    store = QdrantVectorStore()
    # 空库短路：避免每次问答都白花一次 embedding + 检索
    global _KB_EMPTY_CACHE
    if _KB_EMPTY_CACHE is None or time.time() - _KB_EMPTY_CACHE[0] > _KB_EMPTY_TTL_SECONDS:
        try:
            _KB_EMPTY_CACHE = (time.time(), store.count() == 0)
        except Exception:  # noqa: BLE001
            _KB_EMPTY_CACHE = None
    if _KB_EMPTY_CACHE is not None and _KB_EMPTY_CACHE[1]:
        return {"hits": [], "empty_collection": True, "summary": "人才知识库当前为空，请直接使用库内人物工具与外部数据源"}

    vector = embed_texts([query])[0]
    try:
        hits = store.search(vector, top_k=top_k)
    except Exception as exc:  # noqa: BLE001
        return {"hits": [], "summary": f"向量库暂不可用：{exc}"}
    items = []
    for hit in hits:
        payload = hit.payload or {}
        text = str(payload.get("text") or "")
        # 引用展示层：pending/空默认视为已确认（人工核验只走舆情卡片），冲突等异常态保留
        raw_status = str(payload.get("fact_status") or "")
        citation_id = ctx.register_source(
            str(payload.get("record_type") or "knowledge"),
            text[:40],
            status="confirmed" if raw_status in ("", "pending") else raw_status,
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


def tool_list_talent_groups(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    """列出人才库全部分组（含人数），帮用户了解手工分类情况。"""
    from agi_talent_radar.core.persons import count_persons_by_group, list_talent_groups

    groups = list_talent_groups(ctx.session)
    rows = [
        {"id": g.id, "name": g.name, "count": count_persons_by_group(ctx.session, g.id)}
        for g in groups
    ]
    ungrouped = ctx.session.query(PersonORM).filter(PersonORM.group_id.is_(None)).count()
    summary = f"共 {len(groups)} 个分组" + (f"（未分组 {ungrouped} 人）" if ungrouped else "")
    citation_id = ctx.register_source("talent_pool", "人才库分组概况", status="confirmed")
    return {"citation_id": citation_id, "groups": rows, "ungrouped_count": ungrouped, "summary": summary}


def tool_search_persons(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    persons = _filter_persons(ctx.session, args)
    results = []
    for p in persons[:20]:
        # 每个人都注册引用，给模型可引用的 citation_id，防止它编造角标
        # meta 带完整人物信息（含最新评估），前端引用卡片直接渲染详细档案
        brief = _person_brief(p, ctx.session)
        citation_id = ctx.register_source(
            "talent_pool", f"人才库：{p.name}", status="confirmed",
            meta=_person_citation_meta(ctx.session, p),
        )
        results.append({"citation_id": citation_id, **brief})
    return {"persons": results, "summary": f"命中 {len(results)} 人"}


def tool_get_person_profile(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    person = ctx.session.get(PersonORM, str(args.get("person_id") or ""))
    if person is None:
        return {"found": False, "summary": "人物不存在"}
    from agi_talent_radar.services.person_assessment_view import get_person_assessment_view

    view = get_person_assessment_view(ctx.session, person.id)
    resume = view["resume"] if view else {"has_resume": False, "structured": {}}
    structured = resume.get("structured") or {}
    citation_id = ctx.register_source(
        "resume", f"{person.name} 的简历画像", status="confirmed",
        meta=_person_citation_meta(ctx.session, person),
    )
    return {
        "found": True,
        "citation_id": citation_id,
        "person": _person_brief(person, ctx.session),
        "has_resume": bool(resume.get("has_resume")),
        "resume_source": {
            "submission_id": resume.get("submission_id"),
            "candidate_id": resume.get("candidate_id"),
            "updated_at": resume.get("updated_at"),
        },
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
    from agi_talent_radar.services.person_assessment_view import get_person_assessment_view

    view = get_person_assessment_view(ctx.session, person.id)
    admissions = view["admissions"] if view else []
    if admissions:
        views = [
            {
                "assessment_id": admission["id"],
                "jd_id": admission["jd_id"],
                "jd_title": admission["jd_title"],
                "decision": _ADMISSION_DECISION_LABELS.get(
                    admission["decision"], admission["decision"]
                ),
                "total_score": admission["total_score"],
                "tasks": [
                    {
                        "task_id": str(task.get("task_id") or ""),
                        "level": task.get("level"),
                        "confidence": task.get("confidence"),
                    }
                    for task in admission["task_assessments"]
                    if isinstance(task, dict)
                ],
                "evaluated_at": admission["updated_at"] or admission["created_at"],
            }
            for admission in admissions
        ]
        interview_count = sum(1 for item in admissions if item["decision"] == "interview")
        citation_id = ctx.register_source(
            "evaluation", f"{person.name} 的面试准入评估", status="confirmed",
            meta=_person_citation_meta(ctx.session, person),
        )
        return {
            "found": True,
            "has_evaluation": True,
            "citation_id": citation_id,
            "source": "interview_admission",
            "assessments": views,
            "interview_count": interview_count,
            "total_positions": len(views),
            "schema_version": view["schema_version"],
            "latest_evaluated_at": admissions[0]["updated_at"] or admissions[0]["created_at"],
            "summary": (
                f"已获取 {person.name} 的面试准入评估（{len(views)} 个岗位："
                f"{interview_count} 进入面试 / {len(views) - interview_count} 不进入面试）"
            ),
        }
    general = view["general_evaluation"] if view else None
    if general is None:
        return {"found": True, "has_evaluation": False, "summary": f"{person.name} 暂无评估记录"}
    citation_id = ctx.register_source(
        "evaluation", f"{person.name} 的评估报告", status="confirmed",
        meta=_person_citation_meta(ctx.session, person),
    )
    academic = general["academic_report"] or {}
    return {
        "found": True,
        "has_evaluation": True,
        "citation_id": citation_id,
        "schema_version": view["schema_version"],
        "overall_score": general["overall_score"],
        "level": general["level"],
        "tier": general["tier"],
        "one_liner": general["one_liner"],
        "stage_profile": general["stage_profile"],
        "core_strengths": general["core_strengths"],
        "potential_risks": general["potential_risks"],
        "recommended_tracks": general["recommended_tracks"],
        "academic_summary": {
            "verdict": academic.get("verdict", ""),
            "warnings": (academic.get("warnings") or [])[:5],
        },
        "evaluated_at": general["completed_at"] or general["created_at"],
        "summary": f"已获取 {person.name} 的评估（总分 {general['overall_score']}）",
    }


def tool_get_resume_versions(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    person = ctx.session.get(PersonORM, str(args.get("person_id") or ""))
    if person is None:
        return {"found": False, "summary": "人物不存在"}
    citation_id = ctx.register_source(
        "resume", f"{person.name} 的简历版本历史", status="confirmed",
        meta=_person_citation_meta(ctx.session, person),
    )
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
        "person": _person_brief(person, ctx.session),
        "versions": versions,
        "summary": f"{person.name} 共 {len(versions)} 个简历版本",
    }


def tool_aggregate_persons(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    persons = _filter_persons(ctx.session, args)
    metric = str(args.get("metric") or "count")
    top_n = max(1, min(50, int(args.get("top_n") or 10)))
    rows = []
    for person in persons:
        row = _person_brief(person, ctx.session)
        if metric == "avg_score":
            evaluation = _latest_evaluation(ctx.session, person.id)
            if evaluation is not None:
                row["score"] = evaluation.overall_score
            else:
                # 旧表无记录时取新准入表最高总分，保持与人才库列表口径一致
                admissions = _person_jd_assessments(ctx.session, person.id)
                row["score"] = (
                    round(max(float(a.total_score or 0) for a in admissions), 1) if admissions else None
                )
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
            "aminer", f"AMiner 学者：{fact.payload.get('name', '')}", fact.source_url, "confirmed"
        )
        scholars.append({"citation_id": citation_id, **fact.payload})
    tried = sorted({str(f.payload.get("query_name") or "") for f in facts if f.payload.get("query_name")})
    suffix = f"（尝试变体：{'/'.join(tried)}）" if tried else ""
    return {"scholars": scholars, "summary": f"AMiner 命中 {len(scholars)} 位学者{suffix}"}


def tool_search_papers(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    """统一论文检索：AMiner → CrossRef → arXiv → OpenAlex 四级降级。"""
    from agi_talent_radar.core.connectors.paper_search import search_papers_federated

    title = str(args.get("title") or "").strip()
    facts = search_papers_federated(title, count=int(args.get("count") or 5))
    papers = []
    sources_used: set[str] = set()
    for fact in facts:
        sources_used.add(fact.source)
        citation_id = ctx.register_source(
            fact.source, str(fact.payload.get("title") or ""), fact.source_url, "confirmed"
        )
        papers.append({"citation_id": citation_id, **fact.payload})
    src_label = "/".join(sorted(sources_used)) if sources_used else "无命中"
    return {"papers": papers, "summary": f"命中 {len(papers)} 篇（来源：{src_label}）"}


def tool_search_dblp(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    from agi_talent_radar.core.connectors.aminer_rest import _pinyin_variants
    from agi_talent_radar.core.connectors.dblp import search_author_pubs

    name = str(args.get("name") or "").strip()
    variants = [name]
    for v in [*(str(x) for x in (args.get("name_variants") or [])), *_pinyin_variants(name)]:
        v = v.strip()
        if v and v not in variants:
            variants.append(v)
    papers: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    for query_name in variants:
        for fact in search_author_pubs(query_name):
            if fact.source_url in seen_urls:
                continue
            seen_urls.add(fact.source_url)
            citation_id = ctx.register_source(
                "dblp", str(fact.payload.get("title") or ""), fact.source_url, "confirmed"
            )
            papers.append({"citation_id": citation_id, "query_name": query_name, **fact.payload})
    suffix = f"（尝试变体：{'/'.join(variants)}）" if len(variants) > 1 else ""
    return {"papers": papers, "summary": f"DBLP 命中 {len(papers)} 篇论文{suffix}"}


def tool_search_web(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    from agi_talent_radar.core.connectors.web_search import search_web

    facts = search_web(str(args.get("query") or ""))
    items = []
    for fact in facts:
        citation_id = ctx.register_source(
            "web_search", str(fact.payload.get("title") or ""), fact.source_url, "confirmed"
        )
        items.append({"citation_id": citation_id, **fact.payload, "url": fact.source_url})
    return {"results": items, "summary": f"网络检索命中 {len(items)} 条"}


def tool_check_reputation(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    """舆情双面监测：综合查询 + 负面信号查询各一次，分组返回。

    负面轨按"标题/正文是否提及当事人"过滤降噪（否则全是同名新闻），
    每条只保留标题+摘要片段，保证 LLM 在工具结果预算内看得到摘要。
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
        except ConnectorUnavailableError:
            # 工具卡会把此字段展示给用户；只给可行动的业务摘要，原始 HTTP
            # 响应、URL 和供应商堆栈不得沿工具结果泄漏到界面或下一轮模型。
            if "网络搜索暂时不可用，请稍后重试" not in errors:
                errors.append("网络搜索暂时不可用，请稍后重试")
            return []
        items = []
        for fact in facts:
            citation_id = ctx.register_source(
                "web_search", str(fact.payload.get("title") or ""), fact.source_url, "confirmed"
            )
            items.append(
                {
                    "citation_id": citation_id,
                    "title": str(fact.payload.get("title") or ""),
                    "snippet": str(fact.payload.get("content") or "")[:150],
                    "publish_date": str(fact.payload.get("publish_date") or ""),
                    "url": fact.source_url,
                }
            )
        return items

    def _mentions_subject(item: dict[str, Any]) -> bool:
        text = item["title"] + item["snippet"]
        return (name and name in text) or (org and org in text)

    general = _collect(subject)
    negative_all = _collect(f"{subject} 争议 质疑 翻车 夸大")
    # 降噪：负面轨只留提及当事人的，无关的"撤稿/造假"同名新闻直接丢
    negative = [it for it in negative_all if _mentions_subject(it)][:6]
    dropped = len(negative_all) - len(negative)
    result: dict[str, Any] = {
        "general": general[:6],
        "negative_signals": negative,
        "note": "negative_signals 已按当事人相关性过滤（含标题含糊的深扒/调查文），仍需甄别真伪；"
        "为空即未发现公开负面记录" + (f"（已滤掉 {dropped} 条无关命中）" if dropped else ""),
        "summary": f"舆情双面监测：综合信息 {len(general[:6])} 条，负面信号 {len(negative)} 条（滤掉 {dropped} 条无关）",
    }
    if errors:
        result["errors"] = errors
    return result


def tool_get_github_repo(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    from agi_talent_radar.core.connectors.github import get_repo_stats

    fact = get_repo_stats(str(args.get("repo") or ""))
    citation_id = ctx.register_source(
        "github", f"GitHub 仓库：{fact.payload.get('repo', '')}", fact.source_url, "confirmed"
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


def tool_request_reputation_review(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    items = []
    for raw in args.get("items") or []:
        if not isinstance(raw, dict):
            continue
        items.append(
            {
                "title": str(raw.get("title") or ""),
                "url": str(raw.get("url") or ""),
                "snippet": str(raw.get("snippet") or ""),
                "sentiment": str(raw.get("sentiment") or "negative"),
                "concern": str(raw.get("concern") or ""),
            }
        )
    return _gated(
        "review_reputation",
        {
            "person_id": str(args.get("person_id") or ""),
            "name": str(args.get("name") or ""),
            "org": str(args.get("org") or ""),
            "items": items,
        },
    )


def execute_gated_action(session, kind: str, payload: dict[str, Any], decision: dict[str, Any]) -> str:
    """用户决策后执行门控动作（真正写库只发生在这里），返回喂回 LLM 的文本。"""
    decision = decision or {}
    if kind == "select_person":
        person = session.get(PersonORM, str(decision.get("choice") or ""))
        if person is None:
            return "用户选择的人物不存在。"
        return f"用户已选定人物：{json.dumps(_person_brief(person, session), ensure_ascii=False)}"

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

    if kind == "review_reputation":
        from agi_talent_radar.core.db.orm import ReputationReportORM
        from agi_talent_radar.core.persons import get_or_create_person

        items = [it for it in (payload.get("items") or []) if isinstance(it, dict)]
        verdicts: dict[int, str] = {}
        for v in decision.get("verdicts") or []:
            # index 可能是 0，不能用 or 判空；isdigit 校验后再 int
            if isinstance(v, dict) and str(v.get("index", "")).isdigit():
                verdicts[int(v["index"])] = str(v.get("action") or "")
        confirmed, dismissed = [], []
        for index, item in enumerate(items):
            action = verdicts.get(index, "dismissed")
            (confirmed if action == "confirmed" else dismissed).append(item)
        person = None
        if payload.get("person_id"):
            person = session.get(PersonORM, str(payload["person_id"]))
        if person is None:
            name = str(payload.get("name") or "").strip()
            if not name:
                return "舆情核验失败：缺少人物姓名。"
            person = get_or_create_person(
                session, name=name, org=str(payload.get("org") or ""), person_type="guest"
            )
        events = []
        for index, item in enumerate(items):
            action = verdicts.get(index, "dismissed")
            events.append({**item, "review_status": "confirmed" if action == "confirmed" else "dismissed"})
        has_negative = any(e.get("sentiment") == "negative" for e in events if e["review_status"] == "confirmed")
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        record = ReputationReportORM(
            person_id=person.id,
            level="red" if has_negative else "green",
            events=events,
            review_status="confirmed",
            reviewer="chat_user",
            review_note="问答页逐条人工核验",
            reviewed_at=now,
        )
        session.add(record)
        session.commit()
        lines = [f"舆情核验完成（报告 #{record.id}，人物 {person.name}，等级 {record.level}）。"]
        if confirmed:
            lines.append("用户【已确认】的条目（可写入总结，须标注“已经人工核验”）：")
            lines.extend(f"- {it.get('title')}（{it.get('url') or '无链接'}）" for it in confirmed)
        if dismissed:
            lines.append("用户【已驳回】的条目（严禁再出现在总结或后续回答中，视为不成立）：")
            lines.extend(f"- {it.get('title')}" for it in dismissed)
        return "\n".join(lines)

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
        "label_en": "Search talent knowledge base",
        "description": "在人才知识向量库语义检索（简历画像/原文/评估/外部事实），返回带 citation_id 的事实。",
        "parameters": _obj(
            {"query": _str("检索问题或关键词"), "top_k": {"type": "integer", "description": "返回条数，默认 8"}},
            ["query"],
        ),
        "handler": tool_search_knowledge,
        "gated": False,
    },
    {
        "name": "list_talent_groups",
        "label": "查看人才分组",
        "label_en": "List talent groups",
        "description": "列出人才库的全部分组（手工分类）及每组人数，帮助了解人才分类概况。",
        "parameters": _obj({}),
        "handler": tool_list_talent_groups,
        "gated": False,
    },
    {
        "name": "search_persons",
        "label": "筛选库内人物",
        "label_en": "Filter in-pool persons",
        "description": "按姓名/学校/方向/学历/分组筛选人才库人物，返回候选人卡片（含 person_id 和分组名）。",
        "parameters": _obj(
            {
                "name": _str("姓名（可空）"),
                "school": _str("学校关键词（可空）"),
                "direction": _str("研究方向关键词（可空）"),
                "degree": _str("学历关键词，如 博士/硕士（可空）"),
                "group": _str("分组名关键词（可空），如 AI Infra；填 未分组/ungrouped 查未分组的人"),
            }
        ),
        "handler": tool_search_persons,
        "gated": False,
    },
    {
        "name": "get_person_profile",
        "label": "读取人物简历画像",
        "label_en": "Read person resume profile",
        "description": "读取人物最新简历的结构化画像（教育/实习/技能/论文自述）。",
        "parameters": _obj({"person_id": _str("人物 ID")}, ["person_id"]),
        "handler": tool_get_person_profile,
        "gated": False,
    },
    {
        "name": "get_person_evaluation",
        "label": "读取人物评估结果",
        "label_en": "Read person evaluation",
        "description": "读取人物最新评估：总分/层级/优势/风险/论文核验结论/推荐 Track。",
        "parameters": _obj({"person_id": _str("人物 ID")}, ["person_id"]),
        "handler": tool_get_person_evaluation,
        "gated": False,
    },
    {
        "name": "get_resume_versions",
        "label": "读取简历版本时间线",
        "label_en": "Read resume version timeline",
        "description": "读取人物全部简历版本（按时间升序的技能/论文/实习列表），用于成长对比。",
        "parameters": _obj({"person_id": _str("人物 ID")}, ["person_id"]),
        "handler": tool_get_resume_versions,
        "gated": False,
    },
    {
        "name": "aggregate_persons",
        "label": "库内统计排名",
        "label_en": "Pool statistics & ranking",
        "description": "库内统计排名：按 degree/school/direction/group 过滤 + count/avg_score/pub_count 聚合。",
        "parameters": _obj(
            {
                "degree": _str("学历过滤（可空）"),
                "school": _str("学校过滤（可空）"),
                "direction": _str("方向过滤（可空）"),
                "group": _str("分组过滤（可空），填分组名或 未分组"),
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
        "label_en": "AMiner scholar search",
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
        "name": "search_papers",
        "label": "论文检索",
        "label_en": "Paper search",
        "description": "按标题检索论文，自动多源降级（AMiner→CrossRef→arXiv→OpenAlex），返回标题/作者/年份/venue/被引/DOI。",
        "parameters": _obj({"title": _str("论文标题或关键词"), "count": {"type": "integer", "description": "返回数量（默认5）"}}, ["title"]),
        "handler": tool_search_papers,
        "gated": False,
    },
    {
        "name": "search_dblp",
        "label": "DBLP 发文检索",
        "label_en": "DBLP publication search",
        "description": "按作者名检索 DBLP 论文（题名/venue/年份），用于发文核验。中文名会自动补拼音变体；已知英文名/其他拼写可放进 name_variants。",
        "parameters": _obj(
            {
                "name": _str("作者姓名"),
                "name_variants": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "姓名变体（英文名/常见拼写，可空）",
                },
            },
            ["name"],
        ),
        "handler": tool_search_dblp,
        "gated": False,
    },
    {
        "name": "search_web",
        "label": "联网检索舆情",
        "label_en": "Web reputation search",
        "description": "联网检索公开信息/舆情，返回标题/摘要/发布时间/链接。",
        "parameters": _obj({"query": _str("检索词")}, ["query"]),
        "handler": tool_search_web,
        "gated": False,
    },
    {
        "name": "check_reputation",
        "label": "舆情双面监测",
        "label_en": "Two-sided reputation check",
        "description": "人物舆情背调的首选：综合查询+负面信号查询双轨返回。需要看正/负两面舆情时必须用它，而不是只跑一次 search_web。",
        "parameters": _obj({"name": _str("人物姓名"), "org": _str("机构（可空）")}, ["name"]),
        "handler": tool_check_reputation,
        "gated": False,
    },
    {
        "name": "get_github_repo",
        "label": "GitHub 仓库核查",
        "label_en": "GitHub repo check",
        "description": "核查 GitHub 仓库 stars/近 90 天提交活跃度/描述，接受 owner/repo 或完整 URL。",
        "parameters": _obj({"repo": _str("owner/repo 或 GitHub URL")}, ["repo"]),
        "handler": tool_get_github_repo,
        "gated": False,
    },
    {
        "name": "select_person",
        "label": "请用户选定人物",
        "label_en": "Ask user to pick a person",
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
        "label_en": "Propose adding to talent pool",
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
        "label_en": "Request fact-conflict ruling",
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
        "label_en": "Ask user for clarification",
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
    {
        "name": "request_reputation_review",
        "label": "提请舆情人工核验",
        "label_en": "Request reputation review",
        "description": (
            "舆情监测中发现无法确证的正面/负面评价类舆情（做了好事/被坏事波及）时调用，"
            "把这类条目逐条提交用户人工核验；用户驳回的条目严禁写入总结。"
            "事实类客观信息（任职/获奖/发文等）不要走这里，直接引用即可。"
        ),
        "parameters": _obj(
            {
                "person_id": _str("库内人物 ID（可空，库外人物留空）"),
                "name": _str("人物姓名"),
                "org": _str("机构（可空）"),
                "items": {
                    "type": "array",
                    "description": "待核验舆情条目",
                    "items": _obj(
                        {
                            "title": _str("舆情标题"),
                            "url": _str("原文链接"),
                            "snippet": _str("摘要片段"),
                            "sentiment": _str("positive | negative"),
                            "concern": _str("为什么无法确证、需要人工判断"),
                        },
                        ["title", "sentiment"],
                    ),
                },
            },
            ["name", "items"],
        ),
        "handler": tool_request_reputation_review,
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
