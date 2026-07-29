"""AMiner 开放平台 REST 连接器：论文搜索 + 论文详情。

认证流程（按 aminer 官方文档）：
  1. 控制台拿 API Key（AMINER_API_KEY）+ 用户 ID（AMINER_USER_ID）
  2. 用 API Key 当 HMAC-SHA256 密钥，组装 JWT（header sign_type=SIGN）
  3. JWT 放 Authorization 头（不加 Bearer）+ X-Platform: openclaw

API 用途：
  - paper_search(title)  免费，按标题搜论文，返回 id/title/year
  - paper_detail(id)    ¥0.01/次，返回作者列表/venue/被引数

本连接器作为论文核验的主力源；OpenAlex 作为兜底（见 openalex.py）。
"""
from __future__ import annotations

import os
import time
import json
import urllib.request
import urllib.parse
import urllib.error

import jwt

from agi_talent_radar.core.connectors.base import ConnectorUnavailableError, Fact

AMINER_BASE = "https://datacenter.aminer.cn/gateway/open_platform"
_REQUEST_TIMEOUT = 15


def _check_auth() -> tuple[str, str]:
    """返回 (api_key, user_id)，缺失抛 ConnectorUnavailableError。"""
    api_key = os.getenv("AMINER_API_KEY", "").strip()
    user_id = os.getenv("AMINER_USER_ID", "").strip()
    if not api_key:
        raise ConnectorUnavailableError("缺少 AMINER_API_KEY，AMiner REST 连接器不可用。")
    if not user_id:
        raise ConnectorUnavailableError("缺少 AMINER_USER_ID，AMiner REST 连接器不可用。")
    return api_key, user_id


def _generate_token() -> str:
    """用 API Key 生成 2 小时有效的 JWT。"""
    api_key, user_id = _check_auth()
    now = int(time.time())
    payload = {
        "user_id": user_id,
        "exp": now + 7200,
        "timestamp": now,
    }
    headers = {"alg": "HS256", "sign_type": "SIGN"}
    return jwt.encode(payload, api_key, algorithm="HS256", headers=headers)


def _request(path: str, params: dict | None = None) -> dict:
    """发 GET 请求，返回解析后的 JSON dict。"""
    token = _generate_token()
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
    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=_REQUEST_TIMEOUT) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise ConnectorUnavailableError(f"AMiner HTTP {exc.code}: {body}") from exc
    except Exception as exc:
        raise ConnectorUnavailableError(f"AMiner 请求失败: {exc}") from exc


def search_aminer_papers_by_title(title: str, size: int = 5) -> list[Fact]:
    """按标题搜索论文，返回 Fact 列表（含 id/title/year/authors）。

    免费接口，返回的 Fact.payload 供 align_claims 的 LLM 对齐用。
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
    return [_paper_to_fact(p, title) for p in papers if isinstance(p, dict)]


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


def _paper_to_fact(query_title: str, paper: dict) -> Fact:
    """AMiner paper_search 结果 -> 标准 Fact（与 openalex 同构）。"""
    authors_raw = paper.get("authors") or []
    if isinstance(authors_raw, list):
        author_names = [
            str(a.get("name") or a.get("name_zh") or "") if isinstance(a, dict) else str(a)
            for a in authors_raw
        ]
    else:
        author_names = []
    paper_id = str(paper.get("id") or paper.get("_id") or "")
    return Fact(
        source="aminer",
        fact_type="paper",
        payload={
            "title": str(paper.get("title") or ""),
            "title_zh": str(paper.get("title_zh") or ""),
            "year": paper.get("year"),
            "doi": str(paper.get("doi") or ""),
            "authors": author_names,
            "query_title": query_title,
        },
        source_url=f"https://www.aminer.cn/pub/{paper_id}" if paper_id else "",
    )
