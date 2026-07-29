"""学术核查链：论文声称提取 → OpenAlex 核查 → 逐条对齐。

判定克制：查不到只标 unverifiable（待人工），不直接判假；
mismatch 只用于事实冲突（作者归属、发表状态、年份对不上）。
"""
from __future__ import annotations

from collections.abc import Callable

from pydantic import BaseModel, Field

from agi_talent_radar.core import llm_client
from agi_talent_radar.core.connectors import ConnectorUnavailableError, Fact, search_works
from agi_talent_radar.core.connectors.aminer_rest import search_aminer_papers_by_title

from agi_talent_radar.agents.academic.models import AcademicReport, ClaimAlignment, PaperClaim
from agi_talent_radar.core.models import NormalizedResume
from agi_talent_radar.core.stage_profile import profile_for_stage

CLAIM_EXTRACTOR_PROMPT = """
你是论文声称提取 Agent。只输出 JSON 对象，顶层字段必须是 claims。

任务：从候选人的论文/成果列表中提取每一条可核查的论文声称。

每条 claim 输出字段：
- title: 论文标题（保留原文，不要翻译）
- venue: 声称发表的会议/期刊，没有则空串
- year: 声称年份，没有则空串
- claimed_role: 一作 / 共同一作 / 通讯 / 其他作者 / 不明
- claimed_status: 草稿 / 已投稿 / 在审 / 已接收 / 已发表 / 不明

规则：
1. 只提取论文/预印本，专利、竞赛、项目不是论文声称。
2. 没有明确作者位次信息时 claimed_role 给 不明。
3. 草稿、已投稿、在审、已接收和已发表必须区分；"投稿中"归已投稿，"under review"归在审。
""".strip()

ALIGNMENT_PROMPT = """
你是学术事实对齐 Agent。只输出 JSON 对象，顶层字段必须是 alignments。

任务：把候选人的每条论文声称与外部学术数据库（AMiner / OpenAlex）检索结果逐条对齐。

候选人姓名：{name}（注意中文姓名的拼音变体，如 张三 = San Zhang / Zhang S.）

每条 alignment 输出字段：
- claim_title: 对应输入声称的标题（原样引用）
- verdict: verified / mismatch / unverifiable
- verified_status: 外部可确认的状态，只能是 已发表 / 不明
- matched_title: 匹配到的论文标题，无匹配则空串
- discrepancies: 事实冲突点列表，如 ["声称一作，作者列表无此人", "声称已发表实为预印本"]
- cited_by_count: 匹配论文的被引数，无匹配给 0
- is_retracted: 匹配论文是否已撤稿
- source_url: 匹配论文的外部链接（直接从检索结果的 source_url 字段取，原样返回），无匹配则空串
- note: 50 字内说明

判定规则：
1. verified：标题基本一致，且作者列表包含候选人（考虑拼音变体），作者位次与声称无冲突。
2. mismatch 仅限硬性事实冲突：作者列表无此人；声称一作但 first_author 是别人；论文已撤稿但声称正常发表。
3. 年份或版本差异（预印本/会议版多版本）不构成 mismatch，写进 note 即可。
4. unverifiable：检索结果中没有可对应的论文；不得把"查不到"说成"造假"。
5. 草稿、已投稿或在审且检索不到时，给 unverifiable 并在 note 说明该状态通常无法由公开数据库确认。
6. 不得编造检索结果中不存在的论文或作者信息。
7. source_url 必须从输入的检索结果中原样复制，不要自己编造 URL。
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


def search_papers(title: str, count: int = 5) -> list[Fact]:
    """统一论文搜索：优先 AMiner REST（内部、便宜），失败兜底 OpenAlex。

    AMiner 失败（缺 key / key 无效 / 网络）时不抛异常，静默降级到 OpenAlex，
    保证核验流程不被连接器问题阻断。
    """
    try:
        facts = search_aminer_papers_by_title(title, size=count)
        if facts:
            return facts
    except ConnectorUnavailableError:
        pass  # 静默降级
    # 兜底：OpenAlex
    return search_works(title, count=count)


def lookup_claim(
    claim: PaperClaim,
    search_fn: Callable[..., list[Fact]] = search_papers,
) -> tuple[list[dict], str | None]:
    """返回 (候选论文 payload 列表, warning)，按标题相似度排序。

    search_fn 默认走 search_papers（aminer 优先，openalex 兜底）。
    """
    try:
        facts = search_fn(claim.title, count=5)
    except ConnectorUnavailableError as exc:
        return [], str(exc)
    candidates = [fact.payload | {"source_url": fact.source_url, "source": fact.source} for fact in facts]
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
                {"claim": claim.model_dump(), "search_candidates": candidates}
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
    for claim, candidates in zip(claims, lookups):
        raw = by_title.get(claim.title, {})
        verdict = str(raw.get("verdict", "unverifiable"))
        if verdict not in {"verified", "mismatch", "unverifiable"}:
            verdict = "unverifiable"
        matched_title = str(raw.get("matched_title", ""))
        # URL 不信任 LLM 返回——直接从 candidates 里按 matched_title 找真实 source_url
        source_url = _find_source_url(matched_title, candidates)
        alignments.append(
            ClaimAlignment(
                claim=claim,
                verdict=verdict,
                verified_status=str(raw.get("verified_status", "不明")),
                matched_title=matched_title,
                discrepancies=[str(item) for item in raw.get("discrepancies", [])],
                cited_by_count=int(raw.get("cited_by_count", 0) or 0),
                is_retracted=bool(raw.get("is_retracted", False)),
                openalex_url=source_url,
                note=str(raw.get("note", "")),
            )
        )
    return alignments


def _find_source_url(matched_title: str, candidates: list[dict]) -> str:
    """根据 matched_title 从 candidates 里找真实 source_url，不信任 LLM 编的 URL。"""
    if not matched_title or not candidates:
        return ""
    # 精确匹配优先
    for c in candidates:
        if str(c.get("title", "")).strip().lower() == matched_title.strip().lower():
            return str(c.get("source_url", ""))
    # 相似度匹配
    best_url = ""
    best_score = 0.0
    for c in candidates:
        title = str(c.get("title", ""))
        score = _title_similarity(matched_title, title)
        if score > best_score and score > 0.8:
            best_score = score
            best_url = str(c.get("source_url", ""))
    return best_url


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
    try:
        alignments = align_claims(name, claims, lookups)
    except Exception as exc:
        # align_claims 抛异常（LLM 调用失败等）时，所有已提取的 claim 降级为 unverifiable
        warnings.append(f"论文对齐失败：{exc}")
        alignments = [
            ClaimAlignment(claim=claim, verdict="unverifiable", note="OpenAlex 核验失败，待人工核验")
            for claim in claims
        ]
    # 补齐：extract_claims 可能漏掉某些 publications（如「参与」措辞），
    # 确保每篇原始 publication 都至少有一条 alignment，避免前端卡在「核验中」。
    aligned_titles = {a.claim.title for a in alignments}
    for pub in publications:
        pub_title = str(pub).strip()
        if not pub_title:
            continue
        # 粗匹配：已对齐的 title 是否出现在 publication 文本里
        if any(at and at in pub_title for at in aligned_titles):
            continue
        alignments.append(
            ClaimAlignment(
                claim=PaperClaim(title=pub_title),
                verdict="unverifiable",
                note="未能提取为可核查论文声称，待人工核验",
            )
        )
    return AcademicReport(alignments=alignments, warnings=warnings)


def run_resume_academic_check(state: dict) -> dict:
    normalized = NormalizedResume.model_validate(state["normalized"])
    profile = profile_for_stage(normalized.stage)
    if not profile.external_verification_expected or not normalized.publications:
        return {**state, "academic_report": AcademicReport().model_dump()}
    try:
        report = run_academic_check(
            name=normalized.name,
            publications=normalized.publications,
            raw_text=normalized.raw_text,
        )
    except Exception as exc:
        report = AcademicReport(warnings=[f"论文外部核验暂不可用：{exc}"])
    return {**state, "academic_report": report.model_dump()}
