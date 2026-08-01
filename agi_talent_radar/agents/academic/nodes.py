"""学术核查链：论文声称提取 → OpenAlex 核查 → 逐条对齐。

判定克制：查不到只标 unverifiable（待人工），不直接判假；
mismatch 只用于事实冲突（作者归属、发表状态、年份对不上）。
"""
from __future__ import annotations

import re
from collections.abc import Callable

from pydantic import BaseModel, Field

from agi_talent_radar.core import llm_client
from agi_talent_radar.core.connectors import ConnectorUnavailableError, Fact, search_works
from agi_talent_radar.core.connectors.aminer_rest import search_aminer_papers_by_title

from agi_talent_radar.agents.academic.models import (
    AcademicReport,
    ClaimAlignment,
    ExternalPaperRecord,
    PaperClaim,
    VerificationChecks,
)
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
2. 期刊名或会议名本身（含年份、分区信息）不是论文；没有明确论文标题的条目不要提取。
3. 没有明确作者位次信息时 claimed_role 给 不明。
4. 草稿、已投稿、在审、已接收和已发表必须区分；"投稿中"归已投稿，"under review"归在审。
""".strip()

ALIGNMENT_PROMPT = """
你是学术事实对齐 Agent。只输出 JSON 对象，顶层字段必须是 alignments。

任务：把候选人的每条论文声称与外部学术数据库（AMiner / OpenAlex）检索结果逐条对齐。

候选人姓名：{name}（注意中文姓名的拼音变体，如 张三 = San Zhang / Zhang S. / S. Zhang / Zhang San）

每条 alignment 输出字段：
- claim_title: 对应输入声称的标题（原样引用）
- verdict: verified / mismatch / unverifiable
- verified_status: 外部可确认的状态，只能是 已发表 / 不明
- matched_title: 匹配到的论文标题，无匹配则空串
- discrepancies: 事实冲突点列表，如 ["声称一作，实际为第 3 作者", "声称已发表实为预印本"]
- cited_by_count: 匹配论文的被引数，无匹配给 0
- is_retracted: 匹配论文是否已撤稿
- source_url: 匹配论文的外部链接（直接从检索结果的 source_url 字段取，原样返回），无匹配则空串
- candidate_author_position: 候选人在匹配论文 authors 数组中的位次（整数，1 表示第一位；0 表示未找到/无匹配论文）
- candidate_author_name: 匹配到的那个外部作者名字（从 authors 数组原样引用；未找到给空串）
- is_co_first: 该论文是否标注了共同一作（† 符号 / "equal contribution" / "co-first" / "These authors contributed equally"）
- title_match: match / mismatch / pending
- author_identity_match: match / mismatch / pending
- author_position_match: match / mismatch / pending
- publication_status_match: match / mismatch / pending
- note: 50 字内说明（如有共一标注请说明）

判定规则：
1. 作者身份与位次判定（必须按顺序两步走，先身份后位次）：
   a. 身份确认：在匹配论文的 authors 数组里寻找候选人。学术界署名形式多变，
      你必须主动识别以下变体（不要因串不全就判 mismatch）：
      - 中英对应：张三 = San Zhang；洪宇杨 = Hongyu Yang
      - 姓氏顺序：「姓 名」(Yang Haowen) 与「名 姓」(Hongyu Yang) 都常见，要都认
      - 名字缩写：Hongyu Yang = H. Yang / H Yang / Yang H. —— 缩写只保留姓或首字母
      - 姓氏+缩写组合：Wang H. / H. Wang 都可能是 Hongyu Wang
      - 拼音首字母：Y. Yang 可能是任何 Y 开头名字的 Yang 姓学者
      判断时优先看姓氏是否吻合（同姓是强信号），再看名字首字母或缩写是否兼容。
      找到 → candidate_author_name 填该名字原样，candidate_author_position 填其在数组中的位次（index+1），author_identity_match=match。
      未找到 → candidate_author_position=0，candidate_author_name=空串，author_identity_match=mismatch。
   b. 位次确认：把 candidate_author_position 与 claimed_role 对比：
      - 共同一作识别：论文若标注 † / "equal contribution" / "co-first" /
        "These authors contributed equally"，is_co_first=true，位次放宽到≤3。
      - is_co_first=true 时：声称一作/共一 → candidate_author_position≤3 即 match
      - is_co_first=false 时：
        - claimed_role=一作 → 要求 candidate_author_position=1，否则 mismatch
        - claimed_role=共同一作 → 要求 candidate_author_position≤2，否则 mismatch
      - claimed_role=通讯 → 通常不约束位次 → match
      - claimed_role=其他作者 / 不明 → match（顺序不构成冲突）
2. verdict 联动：
   - verified：标题基本一致，且 author_identity_match=match，且 author_position_match=match。
   - mismatch：author_identity_match=mismatch（作者列表无此人）；或 author_position_match=mismatch 且 claimed_role∈{{一作,共同一作}}（谎报位次是硬伤）；或论文已撤稿但声称正常发表。
   - unverifiable：检索结果中没有可对应的论文；不得把"查不到"说成"造假"。
3. discrepancies 必须写明具体位次，如"声称一作，实际为第 3 作者"。
4. 年份或版本差异（预印本/会议版多版本）不构成 mismatch，写进 note 即可。
5. 草稿、已投稿或在审且检索不到时，给 unverifiable 并在 note 说明该状态通常无法由公开数据库确认。
6. 不得编造检索结果中不存在的论文或作者信息。禁止仅凭"作者列表包含候选人"就判顺序一致——顺序判定必须有明确的 candidate_author_position 支撑。
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


def _expand_search_queries(title: str) -> list[str]:
    """从论文标题生成多个检索查询，提升召回。

    AMiner/OpenAlex 对整个标题做整体匹配，OCR 错字/连字符丢失/省略副标题
    都会导致召回 0。这里纯规则拆分出稳定查询变体：
    1. 原标题（覆盖精确匹配）
    2. 冒号/破折号前的主标题（去掉副标题，如 "HingeMem: ..." → "HingeMem"）
    3. 去掉特殊符号的纯净版（Long-Term → Long Term，救连字符/OCR 差异）
    """
    title = (title or "").strip()
    if not title:
        return []
    queries = [title]
    # 冒号/破折号切主标题（论文标题通常是 "Acronym: Full Name"）
    head = re.split(r"[:：—\-–]", title, maxsplit=1)[0].strip()
    if head and len(head) >= 4 and head.lower() != title.lower():
        queries.append(head)
    # 去特殊符号纯净版（救连字符/空格/OCR 差异），保留字母数字和空格
    cleaned = re.sub(r"[^0-9A-Za-z\s]", " ", title)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    cleaned = re.sub(r"\b(and|the|a|an|of|for|with|to|in|on|via|using)\b", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if cleaned and cleaned.lower() not in {q.lower() for q in queries} and len(cleaned) >= 6:
        queries.append(cleaned)
    return queries


def lookup_claim(
    claim: PaperClaim,
    search_fn: Callable[..., list[Fact]] = search_papers,
) -> tuple[list[dict], str | None]:
    """返回 (候选论文 payload 列表, warning)，按标题相似度排序。

    对标题做多种拆分查询（原文 + 主标题 + 纯净版），合并去重后排序，
    避免单次整体匹配召回 0 导致核验无_candidates 可对齐。
    """
    queries = _expand_search_queries(claim.title)
    seen_titles: set[str] = set()
    merged: list[dict] = []
    warning: str | None = None
    for query in queries:
        try:
            facts = search_fn(query, count=5)
        except ConnectorUnavailableError as exc:
            warning = str(exc)
            continue
        for fact in facts:
            candidate = fact.payload | {"source_url": fact.source_url, "source": fact.source}
            t = str(candidate.get("title", "")).strip().lower()
            if t and t not in seen_titles:
                seen_titles.add(t)
                merged.append(candidate)
    merged.sort(key=lambda item: _title_similarity(claim.title, str(item.get("title", ""))), reverse=True)
    return merged[:10], warning  # 保留 top10，足够 LLM 对齐挑拣


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
        matched_title = str(raw.get("matched_title", ""))
        matched = _find_matched_candidate(matched_title, candidates)
        source_url = str(matched.get("source_url", ""))
        authors = [str(author) for author in matched.get("authors", [])]
        has_match = bool(matched)

        # 后端确定性复核：候选人在 authors 数组的实际位次（防 LLM 幻觉）
        llm_position = int(raw.get("candidate_author_position", 0) or 0)
        llm_name = str(raw.get("candidate_author_name", ""))
        verified_pos, verified_name = _verify_author_position(
            llm_name, llm_position, authors, fallback_name=name,
        )

        # 单一真相源派生所有结论，杜绝 verdict/checks/disc/note 互相矛盾
        normalized_role = _normalize_role(claim.claimed_role)
        is_co_first = bool(raw.get("is_co_first", False))
        checks = _derive_checks(has_match, verified_pos, normalized_role, raw, is_co_first)
        discrepancies = _derive_discrepancies(
            [str(item) for item in raw.get("discrepancies", [])],
            has_match, verified_pos, normalized_role, is_co_first,
        )
        verdict = _derive_verdict(
            str(raw.get("verdict", "unverifiable")), has_match, verified_pos, normalized_role, is_co_first,
        )
        note = _derive_note(
            str(raw.get("note", "")), llm_position, verified_pos, has_match,
        )

        alignments.append(
            ClaimAlignment(
                claim=claim,
                verdict=verdict,
                verified_status=str(raw.get("verified_status", "不明")),
                matched_title=matched_title,
                discrepancies=discrepancies,
                cited_by_count=int(raw.get("cited_by_count", 0) or 0),
                is_retracted=bool(raw.get("is_retracted", False)),
                openalex_url=source_url,
                source_url=source_url,
                candidate_author_position=verified_pos,
                candidate_author_name=verified_name,
                is_co_first=is_co_first,
                external_record=ExternalPaperRecord(
                    source=str(matched.get("source", "")),
                    source_url=source_url,
                    title=str(matched.get("title", "")),
                    authors=authors,
                    venue=str(matched.get("venue", "")),
                    year=str(matched.get("year", "") or ""),
                    publication_status=str(raw.get("verified_status", "不明")),
                    cited_by_count=int(raw.get("cited_by_count", 0) or 0),
                    is_retracted=bool(raw.get("is_retracted", False)),
                ),
                checks=checks,
                note=note,
            )
        )
    return alignments


def _find_matched_candidate(matched_title: str, candidates: list[dict]) -> dict:
    """按标题返回真实候选记录，不信任 LLM 生成的外部事实。"""
    if not matched_title or not candidates:
        return {}
    for c in candidates:
        if str(c.get("title", "")).strip().lower() == matched_title.strip().lower():
            return c
    best: dict = {}
    best_score = 0.0
    for c in candidates:
        title = str(c.get("title", ""))
        score = _title_similarity(matched_title, title)
        if score > best_score and score > 0.8:
            best_score = score
            best = c
    return best


def _find_source_url(matched_title: str, candidates: list[dict]) -> str:
    return str(_find_matched_candidate(matched_title, candidates).get("source_url", ""))


def _check_status(value, fallback: str) -> str:
    text = str(value or "").strip().lower()
    return text if text in {"match", "mismatch", "pending"} else fallback


def _verify_author_position(
    candidate_name: str,
    llm_position: int,
    authors: list[str],
    fallback_name: str = "",
) -> tuple[int, str]:
    """复核候选人在 authors 数组的位次。

    作者身份与缩写/中英变体匹配全权交给 align LLM 判断；后端只做最简复核：
    信任 LLM 报的位次，核对那个位置的作者名与 LLM 报的匹配名是否一致
    （子串或首字母包含），防止位次幻觉。返回 (位次, 作者名)；0=未找到。
    """
    if not authors:
        return 0, ""
    # LLM 位次范围合法 + 报了匹配名 → 核对那个位置确实是这个名字
    if llm_position and 1 <= llm_position <= len(authors):
        seat = authors[llm_position - 1]
        if _names_consistent(candidate_name, seat):
            return llm_position, seat
    # LLM 报了匹配名但位次对不上 → 在 authors 里找该名字所在位置
    target = (candidate_name or "").strip().lower()
    if target:
        for idx, author in enumerate(authors):
            if _names_consistent(target, author):
                return idx + 1, author
    return 0, ""


def _names_consistent(a: str, b: str) -> bool:
    """姓名一致性最简复核：去掉标点/空格/大小写后，其一包含另一个。

    LLM 已做缩写/拼音判断；后端只兜底防「LLM 报错名字但位次碰巧有效」。
    """
    import re
    norm = lambda s: re.sub(r"[\s.\-_,]", "", str(s or "")).lower()
    na, nb = norm(a), norm(b)
    if not na or not nb:
        return False
    # 单字母缩写（如 h）：首字母对上即可；否则子串包含
    if len(na) <= 2 or len(nb) <= 2:
        return na[0] == nb[0]
    return na in nb or nb in na


def _normalize_role(claimed_role: str) -> str:
    """把简历里五花八门的角色措辞归一成标准四类：一作/共同一作/通讯/其他。"""
    text = str(claimed_role or "").strip().lower()
    if not text or text == "不明":
        return "其他"
    if "共同一作" in text or "co-first" in text or "coauthor" in text or "共一" in text:
        return "共同一作"
    if "一作" in text or "第一作者" in text or "first author" in text or "lead author" in text:
        return "一作"
    if "通讯" in text or "corresponding" in text:
        return "通讯"
    return "其他"


_VERDICTS = {"verified", "mismatch", "unverifiable"}


def _derive_checks(has_match: bool, verified_pos: int, role: str, raw: dict, is_co_first: bool = False) -> VerificationChecks:
    """从真相源派生 4 维度 check，杜绝互相矛盾。

    检索不到论文（has_match=False）→ 作者相关维度一律 pending（无从谈起）；
    检索到但候选人不在列表（verified_pos=0）→ identity/position 双 mismatch；
    在列表则 identity=match，position 按角色位次要求判定。
    is_co_first（论文标注共一）时位次放宽到≤3。
    """
    if not has_match:
        return VerificationChecks(
            title=_check_status(raw.get("title_match"), "pending"),
            author_identity="pending",
            author_position="pending",
            publication_status="pending",
        )
    verified_status = str(raw.get("verified_status", ""))
    return VerificationChecks(
        title=_check_status(raw.get("title_match"), "match"),
        author_identity="match" if verified_pos > 0 else "mismatch",
        author_position=_position_check(role, verified_pos, is_co_first),
        publication_status=_check_status(
            raw.get("publication_status_match"),
            "match" if verified_status == "已发表" else "pending",
        ),
    )


def _position_check(role: str, position: int, is_co_first: bool = False) -> str:
    """作者顺序维度判定：仅一作/共同一作约束位次，通讯/其他不约束。

    候选人不在列表（position=0）时，身份维度已标 mismatch，此处同样 mismatch。
    is_co_first（论文标注 †/equal contribution）：一作/共一位次放宽到 ≤3。
    """
    if position <= 0:
        return "mismatch"
    max_allowed = 3 if is_co_first else (2 if role == "共同一作" else 1)
    if role in {"一作", "共同一作"}:
        return "match" if position <= max_allowed else "mismatch"
    return "match"  # 通讯 / 其他：不约束位次


def _derive_verdict(
    raw_verdict: str, has_match: bool, verified_pos: int, role: str, is_co_first: bool = False,
) -> str:
    """从真相源派生总 verdict。

    verified：匹配到论文 且 候选人在作者列表 且 位次符合声称角色。
    mismatch：匹配到论文 但 候选人不在列表（身份不符），
             或位次严重不符（非前 3 位且未标共一）。
    unverifiable：位次轻微信号疑但可能是共一（一作/共一声称 + pos 2-3 位 + 无共一标注）
                 —— AMiner/OpenAlex 不返共一标注，2-3 位很可能是共一，
                 不判造假，改待人工核实。
    """
    verdict = raw_verdict if raw_verdict in _VERDICTS else "unverifiable"
    if not has_match:
        return "unverifiable"
    if verified_pos == 0:
        return "mismatch"  # 作者列表无此人 = 硬事实冲突
    if _position_check(role, verified_pos, is_co_first) == "mismatch" and role in {"一作", "共同一作"}:
        # 位次落在 2-3 位且无共一标注时，可能是共一（API 不返共一标注）。
        # 不判造假，改待人工核实，让 HR 确认是否共一后放行。
        if not is_co_first and 2 <= verified_pos <= 3:
            return "unverifiable"
        return "mismatch"  # 位次严重靠后（≥4）或共一仍不匹配 → 硬伤
    return "verified"


def _derive_discrepancies(
    raw_discrepancies: list[str],
    has_match: bool, verified_pos: int, role: str, is_co_first: bool = False,
) -> list[str]:
    """从真相源派生 discrepancies，剔除 LLM 幻觉位次文案。

    只保留与作者身份/位次无关的旧条目（如发表状态冲突），
    再按真相源补一条权威描述，保证 disc 与 checks/verdict 完全一致。
    is_co_first 时位次放宽，不再追加剧烈位次差异描述。
    """
    kept = [
        d for d in raw_discrepancies
        if "作者列表无此人" not in d
        and "实际为第" not in d
        and "实际第" not in d
        and "声称一作" not in d
        and "声称共同一作" not in d
    ]
    if not has_match:
        return kept  # 检索不到，不追加作者相关描述
    if verified_pos == 0:
        kept.append("作者列表中无候选人")
    elif _position_check(role, verified_pos, is_co_first) == "mismatch" and role in {"一作", "共同一作"}:
        if not is_co_first and 2 <= verified_pos <= 3:
            kept.append(f"声称{role}，实际为第 {verified_pos} 作者，可能是共同一作，待人工核实")
        else:
            kept.append(f"声称{role}，实际为第 {verified_pos} 作者")
    return kept


def _derive_note(
    raw_note: str, llm_position: int, verified_pos: int, has_match: bool,
) -> str:
    """从真相源派生 note，剥离与结论矛盾的幻觉文案。

    后端复核与 LLM note 矛盾时（如 note 说"位次第5"但 pos=0），
    清掉幻觉并补权威说明，避免 note 与 checks 自相矛盾。
    """
    note = raw_note.strip()
    author_hallucination_marks = ("作者匹配", "位次", "第 ", "一作", "通讯", "候选人")
    if "作者" in note or any(m in note for m in author_hallucination_marks):
        # note 提到了作者相关结论，必须与真相源一致，否则视为幻觉清空
        contradicts = (
            (verified_pos == 0)
            or (llm_position and llm_position != verified_pos)
        )
        if contradicts:
            note = ""
    if not note:
        if not has_match:
            return "未取得可用的外部论文记录。"
        if verified_pos == 0:
            return "后端复核：候选人不在作者列表。"
        if llm_position and llm_position != verified_pos:
            return f"后端复核：候选人为第 {verified_pos} 作者。"
    return note


def run_academic_check(
    name: str,
    publications: list[str],
    raw_text: str = "",
    search_fn: Callable[..., list[Fact]] | None = None,
) -> AcademicReport:
    paper_search = search_fn or search_papers
    claims = extract_claims(publications, raw_text)
    lookups: list[list[dict]] = []
    warnings: list[str] = []
    for claim in claims:
        candidates, warning = lookup_claim(claim, search_fn=paper_search)
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
    if "academic_report" in state:
        return state
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
