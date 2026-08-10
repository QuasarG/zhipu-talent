"""脱敏：评分前把身份信息从材料文本中替换掉。

身份是已知答案（申请人姓名/学校/导师在创建时就登记了），所以用确定性
字符串+变体替换，比 NER 可靠；LLM 泄漏检查做兜底。
"""
from __future__ import annotations

import re


def _variants(name: str) -> list[str]:
    """姓名/机构的常见写法变体：去空格、大小写、中英文括号内容。"""
    name = (name or "").strip()
    if not name:
        return []
    variants = {name, name.replace(" ", "")}
    # "李博杰（Bojie Li）" 这种：括号内外各自也算变体
    for part in re.split(r"[（(）)]", name):
        part = part.strip()
        if len(part) >= 2:
            variants.add(part)
            variants.add(part.replace(" ", ""))
    return sorted(variants, key=len, reverse=True)  # 长串优先，防短串截胡


def anonymize_text(text: str, identities: dict[str, list[str]]) -> str:
    """把 identities（role → [姓名/机构]）在 text 里替换为占位符。"""
    out = text or ""
    counters: dict[str, int] = {}
    for role, names in identities.items():
        for name in names:
            for variant in _variants(name):
                if variant and variant in out:
                    counters[role] = counters.get(role, 0) + 1
                    out = out.replace(variant, f"[{role}{chr(64 + counters[role])}]")
    return out


def build_identities(app) -> dict[str, list[str]]:
    """从申请人主档收集身份线索。"""
    identities = {
        "申请人": [app.name],
        "学校": [app.school] if app.school else [],
        "导师": list(app.advisors or []),
    }
    return {k: v for k, v in identities.items() if v}


def check_leak(anonymized_text: str, identities: dict[str, list[str]]) -> list[str]:
    """确定性泄漏检查：返回仍残留在文本里的身份串。"""
    leaks = []
    for names in identities.values():
        for name in names:
            for variant in _variants(name):
                if variant and variant in anonymized_text:
                    leaks.append(variant)
    return leaks
