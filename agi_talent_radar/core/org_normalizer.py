"""机构名标准化：用 LLM 把俗称/简称转成检索关键词。

把「北航」「智谱」这种用户输入，标准化成「北京航空航天大学 OR Beihang University」
这样的检索词，提升 AMiner 和 web_search 的命中与消歧精度。
"""
from __future__ import annotations

from agi_talent_radar.core import llm_client

ORG_NORMALIZER_PROMPT = """
你是机构名标准化助手。只输出 JSON 对象，顶层字段必须是 keywords。

任务：把用户输入的机构名（可能是简称、俗称、英文缩写）标准化为检索关键词，
覆盖该机构的常见写法，用于提升数据库检索和网页检索的命中率。

输出字段：
- keywords: list[string]，该机构的检索关键词变体，按常用度排序。
  - 中文全称、中文简称、英文全称、英文缩写都要覆盖。
  - 每个元素是一个独立的变体（如「北京航空航天大学」「北航」「Beihang University」「BUAA」）。
  - 不要加引号、不要加 OR 等逻辑连接词，每个变体单独一个元素。
- normalized: string，最规范的中文全称（无对应机构时原样返回输入）。
- confidence: string，high / medium / low（输入太模糊或不像机构时给 low）。

规则：
1. 输入已经是规范全称时，keywords 只补英文/缩写变体，不重复。
2. 输入是空串或明显不是机构（如「不知道」「无」），confidence 给 low，keywords 只含原输入。
3. 不得编造不存在的机构。
""".strip()


class OrgNormalizationResult:
    """机构标准化结果。"""

    def __init__(self, keywords: list[str], normalized: str, confidence: str, raw: str):
        self.keywords = keywords
        self.normalized = normalized
        self.confidence = confidence
        self.raw = raw

    @property
    def search_terms(self) -> list[str]:
        """用于检索的词列表（去重去空）。"""
        seen: set[str] = set()
        terms: list[str] = []
        for kw in self.keywords or [self.raw]:
            kw = kw.strip()
            if kw and kw.lower() not in seen:
                seen.add(kw.lower())
                terms.append(kw)
        return terms


def normalize_org(org: str) -> OrgNormalizationResult:
    """标准化机构名，返回检索关键词变体。输入为空时返回原样。"""
    raw = (org or "").strip()
    if not raw:
        return OrgNormalizationResult(keywords=[], normalized="", confidence="low", raw="")
    response = llm_client.call_llm_json(
        ORG_NORMALIZER_PROMPT,
        {"org": raw},
        temperature=0.0,
    )
    keywords = [str(k).strip() for k in response.get("keywords", []) if str(k).strip()]
    normalized = str(response.get("normalized", raw)).strip() or raw
    confidence = str(response.get("confidence", "medium")).strip().lower()
    if confidence not in {"high", "medium", "low"}:
        confidence = "medium"
    return OrgNormalizationResult(
        keywords=keywords or [raw],
        normalized=normalized,
        confidence=confidence,
        raw=raw,
    )
