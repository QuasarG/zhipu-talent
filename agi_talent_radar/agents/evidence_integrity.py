from __future__ import annotations

import re
import unicodedata

from agi_talent_radar.core.models import EvidenceItem


INTEGRITY_FLAG_PREFIX = "疑似幻觉证据"


def quote_integrity_flags(evidence: list[EvidenceItem], raw_text: str) -> list[str]:
    return [
        f"{INTEGRITY_FLAG_PREFIX}：{item.id} 的引文与原简历可追溯性不足，请回炉改用原文短句。"
        for item in evidence
        if not is_quote_traceable(item.quote, raw_text)
    ]


def is_quote_traceable(quote: str, raw_text: str) -> bool:
    quote_norm = _compact_text(quote)
    raw_norm = _compact_text(raw_text)
    if not quote_norm:
        return False
    if quote_norm in raw_norm:
        return True

    quote_numbers = _numbers(quote_norm)
    raw_numbers = set(_numbers(raw_norm))
    if any(number not in raw_numbers for number in quote_numbers):
        return False

    quote_terms = _meaningful_terms(quote)
    if not quote_terms:
        return False

    raw_terms_text = _terms_text(raw_text)
    matched = [term for term in quote_terms if _term_in_text(term, raw_terms_text)]
    coverage = len(matched) / len(quote_terms)
    if len(quote_terms) <= 2:
        return coverage == 1
    return coverage >= 0.72


def _compact_text(text: str) -> str:
    text = unicodedata.normalize("NFKC", str(text or "")).lower()
    return re.sub(r"[\s,，、;；:：。.!！?？'\"“”‘’()\[\]{}<>《》/\\|_+\-—–]+", "", text)


def _terms_text(text: str) -> str:
    return unicodedata.normalize("NFKC", str(text or "")).lower()


def _numbers(text: str) -> list[str]:
    return re.findall(r"\d+(?:\.\d+)?%?", text)


def _meaningful_terms(text: str) -> list[str]:
    normalized = unicodedata.normalize("NFKC", str(text or "")).lower()
    terms: list[str] = []
    terms.extend(_english_terms(normalized))
    terms.extend(_cjk_terms(normalized))
    return list(dict.fromkeys(term for term in terms if len(term) >= 2))


def _english_terms(text: str) -> list[str]:
    terms = re.findall(r"[a-z][a-z0-9+.#_-]{1,}", text)
    stopwords = {"with", "and", "for", "the", "data", "engine"}
    return [term for term in terms if term not in stopwords]


def _cjk_terms(text: str) -> list[str]:
    chunks = re.split(r"[\s,，、;；:：。.!！?？'\"“”‘’()\[\]{}<>《》/\\|_+\-—–]+", text)
    terms: list[str] = []
    for chunk in chunks:
        for part in re.split(r"[和及与的了为在对中上并或以及]+", chunk):
            cjk = "".join(re.findall(r"[\u4e00-\u9fff]+", part))
            if len(cjk) >= 2:
                terms.extend(_split_long_cjk_term(cjk))
    return terms


def _split_long_cjk_term(term: str) -> list[str]:
    if len(term) <= 8:
        return [term]
    result: list[str] = []
    for token in ["多智能体", "闭环", "系统", "构图", "出题", "求解", "验证", "反思", "符号求解", "数值采样", "逻辑一致性", "错误归因", "模型评测"]:
        if token in term:
            result.append(token)
    if result:
        return result
    return [term[index : index + 4] for index in range(0, len(term) - 3, 4)]


def _term_in_text(term: str, text: str) -> bool:
    if re.search(r"[a-z0-9]", term):
        pattern = re.escape(term).replace(r"\-", r"[-_\s]?")
        return re.search(pattern, text, re.I) is not None
    return term in _compact_text(text)
