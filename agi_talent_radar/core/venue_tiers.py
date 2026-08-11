"""会议/期刊 CCF 分级查找表。

用于 publication_scorer 给论文按档次打基础分。
匹配逻辑:venue 字符串归一化(小写+去标点+去年份)后查表。
"""
from __future__ import annotations

import re


# 顶会(CCF-A 或公认同级)
_TIER_A = frozenset({
    # 机器学习 / AI
    "neurips", "nips", "neural information processing systems",
    "icml", "international conference on machine learning",
    "iclr", "international conference on learning representations",
    "aaai", "ijcai",
    # CV
    "cvpr", "iccv", "eccv",
    # NLP(EMNLP 按公认顶会归 A)
    "acl", "emnlp", "annual meeting of the association for computational linguistics",
    # 软工 / 系统
    "icse", "international conference on software engineering",
    "fse", "foundations of software engineering", "european software engineering conference",
    "ase", "automated software engineering",
    "issta", "international symposium on software testing and analysis",
    "sigmod", "vldb", "kdd",
    # 安全
    "usenix security", "ieee symposium on security and privacy",
    "s&p", "oakland",
    "ccs", "computer and communications security",
    "ndss", "network and distributed system security",
    # 期刊顶刊
    "tpami", "ieee transactions on pattern analysis and machine intelligence",
    "tifs", "ieee transactions on information forensics and security",
    "tosem", "acm transactions on software engineering and methodology",
    "tse", "ieee transactions on software engineering",
    "ieeetpami",  # 常见简写
})

# 一流(CCF-B 或公认强会)
_TIER_B = frozenset({
    "naacl", "coling",
    "www", "wsdm", "cikm",
    "mm", "acm multimedia",
    "wacv",
    "icra", "iros",  # 机器人
    "jmlr", "journal of machine learning research",
    "ieee tnnls", "tnnls", "ieee transactions on neural networks and learning systems",
    "ieee tmm", "transactions on multimedia",
    "icme",
    "ecai",
    "prcv",
})

# 其它已发表(CCF-C 或未分级但有正式发表)
_TIER_C = frozenset({
    "icassp",
    "acml",
    "icip",
    "icpr",
    "apnoms", "metacom",
    "icic",
})


def _normalize(venue: str) -> str:
    """归一化venue:小写+去年份+去标点+压缩空格。"""
    v = venue.lower()
    v = re.sub(r"\b(19|20)\d{2}\b", "", v)  # 去年份
    v = re.sub(r"[^a-z&\s]", " ", v)  # 去标点(保留&)
    v = re.sub(r"\s+", " ", v).strip()
    # 去常见后缀
    for suffix in (" conference", " symposium", " workshop", " proceedings", " of the", " international"):
        v = v.replace(suffix, "")
    return v.strip()


def classify_venue(venue: str) -> str | None:
    """venue → 'A' | 'B' | 'C' | None(无分级)。

    优先精确匹配归一化串,回退子串包含(处理 'neurips 2025 poster' 这种)。
    """
    if not venue:
        return None
    norm = _normalize(venue)
    if not norm:
        return None
    # 精确匹配
    if norm in _TIER_A:
        return "A"
    if norm in _TIER_B:
        return "B"
    if norm in _TIER_C:
        return "C"
    # 子串包含(处理复合 venue 名)
    for key in _TIER_A:
        if key in norm:
            return "A"
    for key in _TIER_B:
        if key in norm:
            return "B"
    for key in _TIER_C:
        if key in norm:
            return "C"
    return None
