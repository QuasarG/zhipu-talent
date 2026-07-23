"""学术核查链：论文声称提取 → OpenAlex 核查 → 逐条对齐。

判定克制：查不到只标 unverifiable（待人工），不直接判假；
mismatch 只用于事实冲突（作者归属、发表状态、年份对不上）。
"""
from __future__ import annotations

from collections.abc import Callable

from pydantic import BaseModel, Field

from agi_talent_radar.core import llm_client
from agi_talent_radar.core.connectors import ConnectorUnavailableError, Fact, search_works

from agi_talent_radar.agents.academic.models import AcademicReport, ClaimAlignment, PaperClaim

CLAIM_EXTRACTOR_PROMPT = """
你是论文声称提取 Agent。只输出 JSON 对象，顶层字段必须是 claims。

任务：从候选人的论文/成果列表中提取每一条可核查的论文声称。

每条 claim 输出字段：
- title: 论文标题（保留原文，不要翻译）
- venue: 声称发表的会议/期刊，没有则空串
- year: 声称年份，没有则空串
- claimed_role: 一作 / 共同一作 / 通讯 / 其他作者 / 不明
- claimed_status: 已发表 / 已接收 / 在投 / 不明

规则：
1. 只提取论文/预印本，专利、竞赛、项目不是论文声称。
2. 没有明确作者位次信息时 claimed_role 给 不明。
3. 标注了"在投/投稿中/under review"的 claimed_status 必须是 在投。
""".strip()

ALIGNMENT_PROMPT = """
你是学术事实对齐 Agent。只输出 JSON 对象，顶层字段必须是 alignments。

任务：把候选人的每条论文声称与 OpenAlex 检索结果逐条对齐。

候选人姓名：{name}（注意中文姓名的拼音变体，如 张三 = San Zhang / Zhang S.）

每条 alignment 输出字段：
- claim_title: 对应输入声称的标题（原样引用）
- verdict: verified / mismatch / unverifiable
- matched_title: 匹配到的 OpenAlex 论文标题，无匹配则空串
- discrepancies: 事实冲突点列表，如 ["声称一作，OpenAlex 作者列表无此人", "声称已发表实为 2026 年预印本"]
- cited_by_count: 匹配论文的被引数，无匹配给 0
- is_retracted: 匹配论文是否已撤稿
- openalex_url: 匹配论文的 OpenAlex 链接
- note: 50 字内说明

判定规则：
1. verified：标题基本一致，且作者列表包含候选人（考虑拼音变体），作者位次与声称无冲突。
2. mismatch 仅限硬性事实冲突：作者列表无此人；声称一作但 first_author 是别人；论文已撤稿但声称正常发表。
3. 年份或版本差异（预印本/会议版多版本、数据库年份字段与版本更新年份不一致）不构成 mismatch，写进 note 即可。
4. unverifiable：检索结果中没有可对应的论文；不得把"查不到"说成"造假"。
5. 声称状态为在投且检索不到时，给 unverifiable 并在 note 说明"在投状态属正常查不到"。
6. 不得编造检索结果中不存在的论文或作者信息。
""".strip()


class _ClaimsPayload(BaseModel):
    claims: list[PaperClaim] = Field(default_factory=list)


def extract_claims(publications: list[str], raw_text: str = "") -> list[PaperClaim]:
    if not publications and not raw_text.strip():
        return []
    response = llm_client.call_llm_json(
        CLAIM_EXTRACTOR_PROMPT,
        {"publications": publications, "raw_text": raw_text[:6000]},
        temperature=0.1,
    )
    claims = _ClaimsPayload.model_validate(response).claims
    return [claim for claim in claims if claim.title.strip()]


def lookup_claim(
    claim: PaperClaim,
    search_fn: Callable[..., list[Fact]] = search_works,
) -> tuple[list[dict], str | None]:
    """返回 (OpenAlex 候选论文 payload 列表, warning)，按标题相似度排序。"""
    try:
        facts = search_fn(claim.title, count=5)
    except ConnectorUnavailableError as exc:
        return [], str(exc)
    candidates = [fact.payload | {"openalex_url": fact.source_url} for fact in facts]
    candidates.sort(key=lambda item: _title_similarity(claim.title, str(item.get("title", ""))), reverse=True)
    return candidates, None


def _title_similarity(a: str, b: str) -> float:
    from difflib import SequenceMatcher

    return SequenceMatcher(None, a.lower().strip(), b.lower().strip()).ratio()


def align_claims(
    name: str,
    claims: list[PaperClaim],
    lookups: list[list[dict]],
) -> list[ClaimAlignment]:
    if not claims:
        return []
    response = llm_client.call_llm_json(
        ALIGNMENT_PROMPT.format(name=name or "未知"),
        {
            "claims": [
                {"claim": claim.model_dump(), "openalex_candidates": candidates}
                for claim, candidates in zip(claims, lookups)
            ]
        },
        temperature=0.1,
    )
    by_title = {}
    for raw in response.get("alignments", []):
        if isinstance(raw, dict):
            by_title[str(raw.get("claim_title", ""))] = raw

    alignments: list[ClaimAlignment] = []
    for claim in claims:
        raw = by_title.get(claim.title, {})
        verdict = str(raw.get("verdict", "unverifiable"))
        if verdict not in {"verified", "mismatch", "unverifiable"}:
            verdict = "unverifiable"
        alignments.append(
            ClaimAlignment(
                claim=claim,
                verdict=verdict,
                matched_title=str(raw.get("matched_title", "")),
                discrepancies=[str(item) for item in raw.get("discrepancies", [])],
                cited_by_count=int(raw.get("cited_by_count", 0) or 0),
                is_retracted=bool(raw.get("is_retracted", False)),
                openalex_url=str(raw.get("openalex_url", "")),
                note=str(raw.get("note", "")),
            )
        )
    return alignments


def run_academic_check(
    name: str,
    publications: list[str],
    raw_text: str = "",
    search_fn: Callable[..., list[Fact]] = search_works,
) -> AcademicReport:
    claims = extract_claims(publications, raw_text)
    lookups: list[list[dict]] = []
    warnings: list[str] = []
    for claim in claims:
        candidates, warning = lookup_claim(claim, search_fn=search_fn)
        lookups.append(candidates)
        if warning:
            warnings.append(f"{claim.title[:30]}: {warning}")
    alignments = align_claims(name, claims, lookups)
    return AcademicReport(alignments=alignments, warnings=warnings)
