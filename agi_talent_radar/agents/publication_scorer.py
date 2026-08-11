"""论文质量加分节点(publication_scorer)。

读 academic_report.alignments,按 CCF 分级+发表状态+核验结果+作者位次
算一个 publication_score(0-15),写回 state。

overall 公式由 portfolio_aggregator 汇总:common + track + publication。
本节点不改任何维度分,只额外加分。
"""
from __future__ import annotations

from typing import Any

from agi_talent_radar.core.venue_tiers import classify_venue


# 基础分(CCF 档次)
_BASE_SCORE = {"A": 3.0, "B": 2.0, "C": 1.0}

# 发表状态系数
_STATUS_COEF = {
    "已发表": 1.0,
    "published": 1.0,
    "已接收": 0.7,
    "已录用": 0.7,
    "accepted": 0.7,
    "在投": 0.3,
    "在审": 0.3,
    "under review": 0.3,
    "under review at": 0.3,
    "已投稿": 0.15,
    "submitted": 0.15,
    "投稿中": 0.15,
    "草稿": 0.0,
    "draft": 0.0,
    "未发表": 0.0,
}

# 核验结果系数
_VERDICT_COEF = {
    "verified": 1.0,
    "unverifiable": 0.6,
    "mismatch": 0.3,
}

# 作者位次系数
_ROLE_COEF = {
    "一作": 1.0,
    "第一作者": 1.0,
    "first author": 1.0,
    "共同一作": 0.8,
    "共一": 0.8,
    "co-first": 0.8,
    "通讯": 0.8,
    "通讯作者": 0.8,
    "corresponding": 0.8,
}

PUBLICATION_MAX = 15.0


def _normalize_status(raw: str) -> str:
    """归一化发表状态字符串,返回 key 或原值(兜底 0.3)。"""
    s = (raw or "").strip().lower()
    for key in _STATUS_COEF:
        if key.lower() == s or key.lower() in s:
            return key
    return s  # 未知,后续查表兜底


def run_publication_scorer(state: dict[str, Any]) -> dict[str, Any]:
    report = state.get("academic_report") or {}
    if not isinstance(report, dict):
        return {"publication_score": 0.0, "publication_details": []}

    total = 0.0
    details: list[dict[str, Any]] = []

    for align in report.get("alignments") or []:
        if not isinstance(align, dict):
            continue
        claim = align.get("claim") or {}

        # venue:优先核验报告的外部记录,回退简历自述
        ext = align.get("external_record") or {}
        venue = (ext.get("venue") or claim.get("venue") or "").strip()
        ccf = classify_venue(venue)
        if ccf is None:
            continue  # 无法分级的不计分

        base = _BASE_SCORE.get(ccf, 0.0)

        # 发表状态系数(未知状态兜底 0.3)
        status_key = _normalize_status(claim.get("claimed_status") or "")
        status_coef = _STATUS_COEF.get(status_key, 0.3)

        # 核验结果系数
        verdict = (align.get("verdict") or "").strip().lower()
        verdict_coef = _VERDICT_COEF.get(verdict, 0.6)

        # 作者位次系数
        role = (claim.get("claimed_role") or "").strip().lower()
        role_coef = _ROLE_COEF.get(role, 0.3)

        score = round(base * status_coef * verdict_coef * role_coef, 2)
        if score <= 0:
            continue
        total += score
        details.append({
            "title": (claim.get("title") or "")[:80],
            "venue": venue[:60],
            "ccf": ccf,
            "status": status_key,
            "verdict": verdict or "unknown",
            "role": role,
            "score": score,
            "formula": f"{base}×{status_coef}×{verdict_coef}×{role_coef}",
        })

    total = round(min(total, PUBLICATION_MAX), 2)
    return {"publication_score": total, "publication_details": details}
