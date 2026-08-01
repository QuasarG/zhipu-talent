"""AMiner 开放平台 REST 连接器：论文搜索 + 学者搜索 + 论文详情。

认证：直接用控制台生成的 JWT Token（AMINER_API_TOKEN），放 Authorization 头。
JWT 由 AMiner 控制台用 API Key 签发，含 user_id + exp；客户端无需自己生成。

全部走 HTTP REST（datacenter.aminer.cn），不再依赖 MCP 协议。

API 用途：
  - paper_search(title)  免费，GET /api/paper/search
  - paper_detail(id)    ¥0.01/次，GET /api/paper/detail
  - person_search(name) 免费，POST /api/person/search
"""
from __future__ import annotations

import os
import json
import urllib.request
import urllib.parse
import urllib.error

from agi_talent_radar.core.connectors.base import ConnectorUnavailableError, Fact

AMINER_BASE = "https://datacenter.aminer.cn/gateway/open_platform"
_REQUEST_TIMEOUT = 15


def _get_token() -> str:
    """取控制台生成的 JWT Token，缺失抛 ConnectorUnavailableError。"""
    token = os.getenv("AMINER_API_TOKEN", "").strip()
    if not token:
        raise ConnectorUnavailableError("缺少 AMINER_API_TOKEN，AMiner REST 连接器不可用。")
    return token


def _request(path: str, params: dict | None = None, method: str = "GET", body: dict | None = None) -> dict:
    """发 HTTP 请求，返回解析后的 JSON dict。"""
    token = _get_token()
    url = AMINER_BASE + path
    if params:
        query = urllib.parse.urlencode(
            {k: (json.dumps(v) if isinstance(v, (list, dict)) else v)
             for k, v in params.items() if v is not None}
        )
        url = f"{url}?{query}"
    headers = {
        "Authorization": token,
        "X-Platform": "openclaw",
        "Content-Type": "application/json;charset=utf-8",
    }
    data = json.dumps(body).encode("utf-8") if body else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=_REQUEST_TIMEOUT) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body_text = exc.read().decode("utf-8", errors="replace")
        raise ConnectorUnavailableError(f"AMiner HTTP {exc.code}: {body_text}") from exc
    except Exception as exc:
        raise ConnectorUnavailableError(f"AMiner 请求失败: {exc}") from exc


# ── 论文搜索 ──

def search_aminer_papers_by_title(title: str, size: int = 5) -> list[Fact]:
    """按标题搜索论文（免费），返回 Fact 列表。

    paper_search 的作者列表常不完整，命中后用免费的 paper/info 按 id 批量补齐。
    """
    title = (title or "").strip()
    if not title:
        return []
    try:
        resp = _request("/api/paper/search", {"title": title, "page": 1, "size": size})
    except ConnectorUnavailableError:
        raise
    if resp.get("code") != 200:
        raise ConnectorUnavailableError(f"AMiner 搜索失败: {resp.get('msg', '未知')}")
    papers = resp.get("data") or []
    facts = [_paper_to_fact(title, p) for p in papers if isinstance(p, dict)]
    _enrich_facts_with_paper_info(facts)
    return facts


def _paper_id_of(fact: Fact) -> str:
    url = fact.source_url or ""
    return url.rsplit("/pub/", 1)[1] if "/pub/" in url else ""


def _enrich_facts_with_paper_info(facts: list[Fact]) -> None:
    """用 paper/info 的完整记录就地补齐作者/期刊/年份/卷号；详情失败不拖死搜索。"""
    ids = [pid for pid in (_paper_id_of(fact) for fact in facts) if pid]
    if not ids:
        return
    try:
        info_by_id = get_aminer_papers_info(ids)
    except ConnectorUnavailableError:
        return
    for fact in facts:
        info = info_by_id.get(_paper_id_of(fact))
        if not info:
            continue
        authors = [
            str(a.get("name") or a.get("name_zh") or "")
            for a in (info.get("authors") or [])
            if isinstance(a, dict)
        ]
        authors = [name for name in authors if name]
        if authors:
            fact.payload["authors"] = authors
        venue = info.get("venue")
        if isinstance(venue, dict):
            venue = venue.get("raw") or venue.get("name") or ""
        if venue:
            fact.payload["venue"] = str(venue)
        if info.get("year"):
            fact.payload["year"] = info.get("year")
        if info.get("issue"):
            fact.payload["issue"] = str(info.get("issue"))


def get_aminer_papers_info(ids: list[str]) -> dict[str, dict]:
    """按论文 id 批量拉详情（免费，POST /api/paper/info），返回 {id: info}。

    详情含完整 authors、venue.raw 期刊名、issue 卷号、year 年份，
    用于补齐 paper_search 结果里不完整的作者列表。
    """
    clean = [str(i).strip() for i in ids if str(i).strip()][:100]
    if not clean:
        return {}
    try:
        resp = _request("/api/paper/info", method="POST", body={"ids": clean})
    except ConnectorUnavailableError:
        raise
    if resp.get("code") != 200:
        raise ConnectorUnavailableError(f"AMiner 论文详情失败: {resp.get('msg', '未知')}")
    data = resp.get("data") or []
    return {str(item.get("id")): item for item in data if isinstance(item, dict) and item.get("id")}


def get_aminer_paper_detail(paper_id: str) -> dict:
    """按论文 ID 查详情（¥0.01/次），返回完整论文信息 dict。"""
    try:
        resp = _request("/api/paper/detail", {"id": paper_id})
    except ConnectorUnavailableError:
        raise
    if resp.get("code") != 200:
        raise ConnectorUnavailableError(f"AMiner 详情失败: {resp.get('msg', '未知')}")
    data = resp.get("data")
    if isinstance(data, list) and data:
        return data[0]
    if isinstance(data, dict):
        return data
    return {}


# ── 学者搜索 ──

def search_aminer_scholar(
    name: str,
    org: str = "",
    size: int = 5,
    name_variants: list[str] | None = None,
) -> list[Fact]:
    """按姓名（+机构提示）检索学者（免费），返回画像 Fact。

    支持多名字变体（LLM 提供 + 中文名自动生成拼音变体），逐变体检索后按
    aminer_id 去重合并；org 只作排序提示（org_match 标注），不做硬过滤——
    AMiner 大量学者的 org 字段为空，硬过滤会把正确结果误杀。
    """
    variants: list[str] = []
    for v in [name, *(name_variants or []), *_pinyin_variants(name)]:
        v = (v or "").strip()
        if v and v not in variants:
            variants.append(v)
    if not variants:
        return []
    org_terms = _normalize_org_terms(org)
    merged: dict[str, Fact] = {}
    errors: list[str] = []
    for variant in variants:
        bodies: list[dict[str, object]] = []
        with_org: dict[str, object] = {"name": variant, "offset": 0, "size": max(1, min(10, size))}
        if org_terms:
            with_org["org"] = org_terms[0]
        bodies.append(with_org)
        # 服务端 org 只认标准机构实体名（"MIT" 这类缩写会直接零结果），空结果时去掉 org 重试
        if org_terms:
            bodies.append({"name": variant, "offset": 0, "size": max(1, min(10, size))})
        for body in bodies:
            try:
                resp = _request("/api/person/search", method="POST", body=body)
            except ConnectorUnavailableError as exc:
                errors.append(str(exc))
                break
            if resp.get("code") != 200:
                errors.append(f"{variant}: {resp.get('msg', '未知')}")
                break
            data = resp.get("data") or []
            if not data:
                continue  # 带 org 零结果 → 尝试下一个 body（无 org）
            for p in data:
                if not isinstance(p, dict):
                    continue
                pid = str(p.get("id") or "")
                if pid and pid not in merged:
                    merged[pid] = _scholar_to_fact(variant, p)
            break  # 有命中就不再重试该变体
    if not merged and errors and len(errors) == len(variants):
        raise ConnectorUnavailableError(f"AMiner 学者搜索失败: {errors[0]}")
    facts = list(merged.values())
    for fact in facts:
        org_text = str(fact.payload.get("org", "")) + str(fact.payload.get("org_zh", ""))
        fact.payload["org_match"] = bool(org_terms) and _org_matches_any(org_text, org_terms)
    # org 匹配优先，其次按引用数降序；稳定排序保持 API 原始相关性
    facts.sort(key=lambda f: -(f.payload.get("citation_count") or 0))
    facts.sort(key=lambda f: not f.payload["org_match"])
    return facts


def _pinyin_variants(name: str) -> list[str]:
    """中文名生成拼音变体（"何恺明" -> ["Kaiming He", "He Kaiming"]）。"""
    name = (name or "").strip()
    if not name or not any("一" <= ch <= "鿿" for ch in name):
        return []
    try:
        from pypinyin import Style, pinyin
    except ImportError:
        return []
    parts = [p[0] for p in pinyin(name, style=Style.NORMAL) if p and p[0]]
    if len(parts) < 2:
        return []
    surname, given = parts[0].capitalize(), "".join(parts[1:]).capitalize()
    return [f"{given} {surname}", f"{surname} {given}"]


def search_aminer_papers(name: str, size: int = 10) -> list[Fact]:
    """按作者姓名检索代表论文（免费 person_search 兜底）。

    开放平台没有直接按人名搜论文的免费接口；
    这里复用 person_search 返回的 interests 作为近似信号。
    """
    return []  # 保留接口签名兼容；真实实现需 person_paper_relation（¥1.50/次）


def check_aminer_connection() -> str:
    """连接测试：用 person_search 查一个知名学者，成功返回 'ok'。"""
    try:
        resp = _request("/api/person/search", method="POST", body={"name": "Yann LeCun", "offset": 0, "size": 1})
        if resp.get("code") == 200:
            return "ok"
        return f"error: {resp.get('msg', '未知')}"
    except ConnectorUnavailableError as exc:
        return f"unconfigured: {exc}"
    except Exception as exc:
        return f"error: {exc}"


# ── 内部工具 ──

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


def _org_matches_any(scholar_org: str, org_terms: list[str]) -> bool:
    """机构名宽松匹配：任一关键词变体子串命中即可；空机构不算命中。"""
    s = scholar_org.lower().strip()
    if not s:
        return False
    for term in org_terms:
        q = term.lower().strip()
        if q and (q in s or s in q):
            return True
    return False


def _paper_to_fact(query_title: str, paper: dict) -> Fact:
    """AMiner paper_search 结果 -> 标准 Fact（与 openalex 同构）。"""
    if not isinstance(paper, dict):
        return Fact(source="aminer", fact_type="paper", payload={"title": "", "query_title": query_title})
    paper_id = str(paper.get("id") or paper.get("_id") or "")
    authors_raw = paper.get("authors") or []
    if isinstance(authors_raw, list):
        author_names = [
            str(a.get("name") or a.get("name_zh") or "") if isinstance(a, dict) else str(a)
            for a in authors_raw
        ]
    else:
        author_names = []
    if not author_names and paper.get("first_author"):
        author_names = [str(paper["first_author"])]
    return Fact(
        source="aminer",
        fact_type="paper",
        payload={
            "title": str(paper.get("title") or ""),
            "title_zh": str(paper.get("title_zh") or ""),
            "year": paper.get("year"),
            "doi": str(paper.get("doi") or ""),
            "authors": author_names,
            "venue": str(paper.get("venue_name") or ""),
            "n_citation_bucket": str(paper.get("n_citation_bucket") or ""),
            "query_title": query_title,
        },
        source_url=f"https://www.aminer.cn/pub/{paper_id}" if paper_id else "",
    )


def _scholar_to_fact(query_name: str, person: dict) -> Fact:
    """AMiner person_search 字段 -> 标准化 payload。"""
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
