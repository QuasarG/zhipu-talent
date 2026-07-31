"""教育经历自由文本 → 结构化学校条目（规则式，不调 LLM）。

简历里的教育经历是自由文本，如：
  "博士联培：中关村学院人工智能算法安全性研究与应用项目组 2024.09 至今"
  "博士：南开大学计算机与网络空间安全学院硕博连读 2022.09 至今"
本模块抽出 学校 / 学位层级 / 起始时间，并给出"最高学历学校"裁决：
学位层级优先，同层级时学位授予校优先于联合培养，再按入学时间取最近。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

# 校名截取：中文校名取到 大学/学院/研究院/研究所，英文校名取到 University/Institute/College/School/Polytechnic
# "南开大学计算机与网络空间安全学院" → "南开大学"；"Nanjing University of Aeronautics..." → "Nanjing University"
_SCHOOL_RE = re.compile(
    r"(?:"
    r"[一-龥A-Za-z]{2,12}?(?:大学|学院|研究院|研究所)"             # 中文校名
    r"|"
    r"[A-Z][A-Za-z.&\- ]{2,60}?(?:University|Institute|College|School|Polytechnic|Academy)"  # 英文校名
    r")"
)
_PERIOD_RE = re.compile(r"(\d{4})[./年](\d{1,2})")

_DEGREE_RULES = (
    (3, ("博士", "直博", "硕博连读", "phd", "doctor")),
    (2, ("硕士", "研究生", "master")),
    (1, ("本科", "学士", "大专", "专科", "bachelor")),
)
_JOINT_MARKERS = ("联培", "联合培养", "交换", "访问")


@dataclass
class EducationEntry:
    school: str = ""
    degree: str = ""
    period: str = ""
    level: int = 0           # 3 博士 / 2 硕士 / 1 本科 / 0 未知
    is_joint: bool = False   # 联合培养/交换，不作为学位授予校
    start: str = ""          # YYYYMM 可比较字符串
    raw: str = ""
    extra: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"school": self.school, "degree": self.degree, "period": self.period}


def _degree_level(text: str) -> tuple[int, str]:
    lowered = text.lower()
    for level, markers in _DEGREE_RULES:
        for marker in markers:
            if marker in lowered or marker in text:
                return level, marker
    return 0, ""


def parse_education_entries(education: list) -> list[EducationEntry]:
    """把候选人 education 自由文本列表解析成结构化条目（无校名的条目丢弃）。"""
    entries: list[EducationEntry] = []
    for item in education or []:
        if isinstance(item, dict):
            text = str(item.get("school") or item.get("organization") or "")
            degree_text = str(item.get("degree") or "")
            period = str(item.get("period") or item.get("year") or "")
        else:
            text = str(item)
            degree_text = text
            period = text
        if not text.strip():
            continue
        match = _SCHOOL_RE.search(text)
        if not match:
            continue
        level, degree_marker = _degree_level(degree_text)
        start_match = _PERIOD_RE.search(period)
        entries.append(
            EducationEntry(
                school=match.group(0),
                degree=degree_marker,
                period=period if isinstance(item, dict) else text,
                level=level,
                is_joint=any(m in text for m in _JOINT_MARKERS),
                start=f"{start_match.group(1)}{int(start_match.group(2)):02d}" if start_match else "",
                raw=text,
            )
        )
    return entries


def highest_school(entries: list[EducationEntry]) -> str:
    """最高学历学校：学位层级 > 学位授予校优先于联培 > 入学时间最近。"""
    if not entries:
        return ""
    best = max(entries, key=lambda e: (e.level, not e.is_joint, e.start))
    return best.school


def top_school_names(schools: list[dict]) -> list[str]:
    """最高学位层级的全部学校（联培也算）：张向宇 → [中关村学院, 南开大学]。"""
    entries = [s for s in schools or [] if isinstance(s, dict) and s.get("school")]
    if not entries:
        return []
    top = max(_degree_level(str(s.get("degree", "")))[0] for s in entries)
    names: list[str] = []
    for s in entries:
        if _degree_level(str(s.get("degree", "")))[0] == top and s["school"] not in names:
            names.append(s["school"])
    return names
