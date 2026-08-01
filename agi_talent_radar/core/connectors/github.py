"""GitHub 连接器：仓库活跃度核查（stars / 近 90 天提交 / 描述）。

无 token 时限流 60 次/时；配 GITHUB_TOKEN（可选）提高到 5000 次/时。
"""
from __future__ import annotations

import os
import re
from datetime import datetime, timedelta, timezone

from agi_talent_radar.core.connectors.base import ConnectorUnavailableError, Fact

GITHUB_API = "https://api.github.com"
TIMEOUT_SECONDS = 15
RECENT_DAYS = 90


def _parse_repo(repo: str) -> str:
    """接受 "owner/repo" 或完整 GitHub URL，归一化为 "owner/repo"。"""
    text = (repo or "").strip()
    if not text:
        return ""
    match = re.search(r"github\.com[:/]([^/\s]+)/([^/\s#?]+)", text)
    if match:
        owner, name = match.group(1), match.group(2)
    else:
        parts = [part for part in text.split("/") if part]
        if len(parts) != 2:
            return ""
        owner, name = parts
    return f"{owner}/{name.removesuffix('.git')}"


def get_repo_stats(repo: str) -> Fact:
    """拉取仓库基础信息与近 90 天提交活跃度；失败抛 ConnectorUnavailableError。"""
    full_name = _parse_repo(repo)
    if not full_name:
        raise ConnectorUnavailableError(f"无法解析 GitHub 仓库标识: {repo!r}")
    try:
        import httpx
    except ImportError as exc:
        raise ConnectorUnavailableError("缺少 httpx 依赖。") from exc

    headers = {"Accept": "application/vnd.github+json"}
    token = os.getenv("GITHUB_TOKEN", "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        with httpx.Client(base_url=GITHUB_API, headers=headers, timeout=TIMEOUT_SECONDS) as client:
            response = client.get(f"/repos/{full_name}")
            response.raise_for_status()
            info = response.json()
            since = (datetime.now(timezone.utc) - timedelta(days=RECENT_DAYS)).isoformat()
            commits_response = client.get(
                f"/repos/{full_name}/commits", params={"since": since, "per_page": 1}
            )
            commits_response.raise_for_status()
            recent_commits = _recent_commit_count(commits_response)
    except Exception as exc:
        raise ConnectorUnavailableError(f"GitHub 调用失败: {exc}") from exc

    return Fact(
        source="github",
        fact_type="github_repo",
        payload={
            "repo": full_name,
            "description": str(info.get("description") or ""),
            "stars": info.get("stargazers_count", 0),
            "forks": info.get("forks_count", 0),
            "language": str(info.get("language") or ""),
            "pushed_at": str(info.get("pushed_at") or ""),
            # None=拿不到精确数；0/正数=近 90 天提交数（Link 头估算）
            "recent_commits_90d": recent_commits,
            "active_90d": bool(recent_commits),
        },
        source_url=str(info.get("html_url") or f"https://github.com/{full_name}"),
    )


def _recent_commit_count(commits_response) -> int | None:
    """用 Link 头 last 页码估算提交总数（per_page=1）；估算不出退化为 有/无。"""
    link = commits_response.headers.get("Link", "")
    match = re.search(r'[?&]page=(\d+)>;\s*rel="last"', link)
    if match:
        return int(match.group(1))
    try:
        items = commits_response.json()
    except Exception:  # noqa: BLE001
        return None
    return len(items) if isinstance(items, list) else None
