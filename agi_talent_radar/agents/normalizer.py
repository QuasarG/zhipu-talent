from __future__ import annotations

import re

from pydantic import BaseModel, Field

from agi_talent_radar.core import llm_client
from agi_talent_radar.core.models import BackgroundSignalTiers, CandidateResume, NormalizedResume


TIER_DEFINITIONS = {
    "school_tier": {
        "elite_research": "顶尖研究型院校/研究机构信号，如明确 985 顶尖、顶级研究院等。",
        "strong_research": "强研究型院校信号，如 985、双一流、研究型大学等。",
        "specialized_stem": "专业特色或 STEM 强相关院校信号，如信息类、理工类、交通类、航空航天类。",
        "general_university": "普通综合类或一般高校信号。",
        "emerging_or_unknown": "新型/创新型/无法判断学校层级。",
        "not_provided": "没有可用学校层级信号。",
    },
    "gpa_tier": {
        "top_5_or_gpa_3_8_plus": "GPA 约 3.8/4.0 以上或排名前 5%。",
        "top_10_or_gpa_3_6_plus": "GPA 约 3.6/4.0 以上或排名前 10%。",
        "solid_or_gpa_3_3_plus": "GPA 约 3.3/4.0 以上或成绩描述较好。",
        "weak_or_unclear": "成绩一般、描述模糊或无法换算。",
        "not_provided": "没有 GPA 或排名信号。",
    },
    "rank_tier": {
        "rank_1": "明确排名第 1。",
        "top_5_percent": "明确前 5%。",
        "top_10_percent": "明确前 10%。",
        "top_20_percent": "明确前 20%。",
        "not_provided": "没有排名信号。",
    },
    "degree_tier": {
        "phd_in_progress": "博士在读或博士研究生。",
        "phd_late_stage": "博士候选人、博士后期或接近毕业。",
        "master": "硕士阶段为最高明确学历。",
        "bachelor": "本科阶段为最高明确学历。",
        "mixed_or_unclear": "多阶段或无法确定最高阶段。",
    },
    "academic_signal_tier": {
        "very_strong": "学校/成绩/排名/学历组合非常强，但仍只作低权重背景信号。",
        "strong": "背景信号较强。",
        "moderate": "背景信号中等或信息不完整。",
        "weak_or_unknown": "背景信号较弱或未知。",
    },
}


NORMALIZER_PROMPT = """
你是 AI 人才潜力初评系统里的【背景信号标准化 Agent】。
只输出 JSON 对象，字段必须是 background_signal_tiers 和 education_notes。

任务：
把教育背景中的具体学校、GPA、排名等细节折叠成低权重档位，避免后续节点直接依赖具体学校名或精确成绩。
这不是完全脱敏，而是屏蔽具体细节，用分级信号替代。

只允许使用 payload.allowed_tiers 里的枚举值：
- school_tier
- gpa_tier
- rank_tier
- degree_tier
- academic_signal_tier

判断原则：
1. 不输出具体学校名、GPA 数值、排名数值。
2. 如果规则候选档 rule_guess 已经很明确，可以沿用；如果文本里有冲突信号，做综合裁决。
3. school_tier 只代表背景训练质量信号，不代表能力结论。
4. academic_signal_tier 综合 school_tier、gpa_tier、rank_tier、degree_tier，但不能压过项目证据。
5. education_notes 用 1-3 条短句说明分级结果，不出现具体学校名、GPA 数值、排名数值。

输出示例：
{
  "background_signal_tiers": {
    "school_tier": "strong_research",
    "gpa_tier": "top_10_or_gpa_3_6_plus",
    "rank_tier": "top_10_percent",
    "degree_tier": "phd_in_progress",
    "academic_signal_tier": "strong",
    "rationale": "博士阶段与较强学业信号叠加，但仅作为低权重履历参考。"
  },
  "education_notes": [
    "学校背景折叠为强研究型院校信号。",
    "学业表现折叠为前列档位，后续仅低权重参考。"
  ]
}
""".strip()


class NormalizerOutput(BaseModel):
    background_signal_tiers: BackgroundSignalTiers
    education_notes: list[str] = Field(default_factory=list)


def run_normalizer(state: dict) -> dict:
    resume = CandidateResume.model_validate(state["resume"])
    rule_tiers = _infer_background_tiers(resume.education)
    adjudicated = _adjudicate_background_tiers(resume, rule_tiers)
    education_blind = _blind_education(resume.education, adjudicated.background_signal_tiers, adjudicated.education_notes)
    normalized = NormalizedResume(
        id=resume.id,
        name=resume.name,
        target_role=resume.target_role,
        stage=resume.stage,
        education_raw=resume.education,
        education_blind=education_blind,
        background_signal_tiers=adjudicated.background_signal_tiers,
        directions=resume.directions,
        projects=resume.projects,
        publications=resume.publications,
        skills=resume.skills,
        screening_tags=resume.screening_tags,
        raw_text=_resume_to_text(resume, education_blind),
    )
    return {
        **state,
        "normalized": normalized.model_dump(),
        "loop_count": int(state.get("loop_count", 0)),
    }


def _adjudicate_background_tiers(resume: CandidateResume, rule_tiers: BackgroundSignalTiers) -> NormalizerOutput:
    try:
        response = llm_client.call_llm_json(
            NORMALIZER_PROMPT,
            {
                "allowed_tiers": TIER_DEFINITIONS,
                "rule_guess": rule_tiers.model_dump(),
                "education_raw": resume.education,
                "target_role": resume.target_role,
                "stage": resume.stage,
            },
            temperature=0,
        )
        output = NormalizerOutput.model_validate(response)
        output.background_signal_tiers = _sanitize_tiers(output.background_signal_tiers, rule_tiers)
        output.education_notes = _sanitize_notes(output.education_notes)
        return output
    except Exception:
        return NormalizerOutput(
            background_signal_tiers=rule_tiers,
            education_notes=["背景信号由规则分级折叠，后续仅低权重参考。"],
        )


def _sanitize_tiers(tiers: BackgroundSignalTiers, fallback: BackgroundSignalTiers) -> BackgroundSignalTiers:
    data = tiers.model_dump()
    fallback_data = fallback.model_dump()
    for key, allowed in TIER_DEFINITIONS.items():
        if data.get(key) not in allowed:
            data[key] = fallback_data.get(key)
    data["rationale"] = _strip_sensitive_academic_detail(str(data.get("rationale") or fallback.rationale))
    return BackgroundSignalTiers.model_validate(data)


def _sanitize_notes(notes: list[str]) -> list[str]:
    clean = [_strip_sensitive_academic_detail(str(item)) for item in notes if str(item).strip()]
    return clean[:3] or ["背景信号已折叠为分级档位，后续仅低权重参考。"]


def _infer_background_tiers(education: list[str]) -> BackgroundSignalTiers:
    text = " ".join(education)
    school_tier = _school_tier(text)
    gpa_tier = _gpa_tier(text)
    rank_tier = _rank_tier(text)
    degree_tier = _degree_tier(text)
    academic_signal_tier = _academic_signal_tier(school_tier, gpa_tier, rank_tier, degree_tier)
    return BackgroundSignalTiers(
        school_tier=school_tier,
        gpa_tier=gpa_tier,
        rank_tier=rank_tier,
        degree_tier=degree_tier,
        academic_signal_tier=academic_signal_tier,
        rationale="规则初判：学校、GPA/排名和学历阶段已折叠为低权重背景档位。",
    )


def _school_tier(text: str) -> str:
    if not text.strip():
        return "not_provided"
    if re.search(r"顶尖|985|重点研究院", text):
        return "elite_research"
    if re.search(r"双一流|研究型大学|重点高校|重点大学", text):
        return "strong_research"
    if re.search(r"信息类|理工类|交通类|航空航天类|医学交叉", text):
        return "specialized_stem"
    if re.search(r"综合性大学", text):
        return "general_university"
    return "emerging_or_unknown"


def _gpa_tier(text: str) -> str:
    gpa_match = re.search(r"GPA\s*([0-9.]+)\s*/\s*([0-9.]+)", text, re.I)
    if gpa_match:
        score = float(gpa_match.group(1))
        scale = float(gpa_match.group(2))
        normalized = score / scale * 4 if scale else 0
        if normalized >= 3.8:
            return "top_5_or_gpa_3_8_plus"
        if normalized >= 3.6:
            return "top_10_or_gpa_3_6_plus"
        if normalized >= 3.3:
            return "solid_or_gpa_3_3_plus"
        return "weak_or_unclear"
    if re.search(r"前\s*5%", text):
        return "top_5_or_gpa_3_8_plus"
    if re.search(r"前\s*10%|排名\s*1\s*/\s*50", text):
        return "top_10_or_gpa_3_6_plus"
    if re.search(r"排名|GPA", text, re.I):
        return "solid_or_gpa_3_3_plus"
    return "not_provided"


def _rank_tier(text: str) -> str:
    if re.search(r"排名\s*1\s*/", text):
        return "rank_1"
    if re.search(r"前\s*5%", text):
        return "top_5_percent"
    if re.search(r"前\s*10%", text):
        return "top_10_percent"
    if re.search(r"前\s*20%", text):
        return "top_20_percent"
    return "not_provided"


def _degree_tier(text: str) -> str:
    if re.search(r"博士候选人", text):
        return "phd_late_stage"
    if re.search(r"博士|直博|硕博连读", text):
        return "phd_in_progress"
    if re.search(r"硕士", text):
        return "master"
    if re.search(r"本科", text):
        return "bachelor"
    return "mixed_or_unclear"


def _academic_signal_tier(school_tier: str, gpa_tier: str, rank_tier: str, degree_tier: str) -> str:
    score = 0
    score += {"elite_research": 3, "strong_research": 2, "specialized_stem": 1, "general_university": 1}.get(school_tier, 0)
    score += {"top_5_or_gpa_3_8_plus": 2, "top_10_or_gpa_3_6_plus": 1, "solid_or_gpa_3_3_plus": 1}.get(gpa_tier, 0)
    score += {"rank_1": 2, "top_5_percent": 2, "top_10_percent": 1, "top_20_percent": 1}.get(rank_tier, 0)
    score += {"phd_late_stage": 2, "phd_in_progress": 1}.get(degree_tier, 0)
    if score >= 6:
        return "very_strong"
    if score >= 4:
        return "strong"
    if score >= 2:
        return "moderate"
    return "weak_or_unknown"


def _blind_education(education: list[str], tiers: BackgroundSignalTiers, notes: list[str]) -> list[str]:
    if not education:
        return notes
    result: list[str] = []
    for item in education:
        degree = _degree_label(item, tiers.degree_tier)
        field = _field_hint(item)
        result.append(
            f"学校层级={_tier_label('school_tier', tiers.school_tier)}；"
            f"学历阶段={degree}；"
            f"学业信号={_tier_label('academic_signal_tier', tiers.academic_signal_tier)}；"
            f"专业方向={field}；具体学校/GPA/排名已折叠。"
        )
    return list(dict.fromkeys(result + notes))


def _degree_label(text: str, fallback: str) -> str:
    if "博士候选人" in text:
        return "博士后期"
    if "博士" in text or "直博" in text or "硕博连读" in text:
        return "博士阶段"
    if "硕士" in text:
        return "硕士阶段"
    if "本科" in text:
        return "本科阶段"
    return _tier_label("degree_tier", fallback)


def _field_hint(text: str) -> str:
    fields = [
        "人工智能",
        "计算机科学与技术",
        "计算机科学",
        "模式识别与智能系统",
        "自动化",
        "软件工程",
        "通信工程",
        "物理学",
        "数学与应用数学",
        "生物医学工程",
        "电子信息",
    ]
    for field in fields:
        if field in text:
            return field
    return "未明确"


def _strip_sensitive_academic_detail(text: str) -> str:
    text = re.sub(r"GPA\s*[0-9.]+\s*/\s*[0-9.]+", "GPA档位", text, flags=re.I)
    text = re.sub(r"(排名|前)\s*\d+\s*(/\s*\d+|%)?", "排名档位", text)
    text = re.sub(r"985|211|双一流|重点(高校|大学|研究院)", "学校层级", text)
    return text


def _tier_label(key: str, value: str) -> str:
    labels: dict[str, dict[str, str]] = {
        "school_tier": {
            "elite_research": "顶尖研究型",
            "strong_research": "强研究型",
            "specialized_stem": "特色/STEM强相关",
            "general_university": "普通综合类",
            "emerging_or_unknown": "新型或未知",
            "not_provided": "未提供",
        },
        "gpa_tier": {
            "top_5_or_gpa_3_8_plus": "前5%/高GPA",
            "top_10_or_gpa_3_6_plus": "前10%/较高GPA",
            "solid_or_gpa_3_3_plus": "良好",
            "weak_or_unclear": "弱或不清晰",
            "not_provided": "未提供",
        },
        "rank_tier": {
            "rank_1": "排名第1",
            "top_5_percent": "前5%",
            "top_10_percent": "前10%",
            "top_20_percent": "前20%",
            "not_provided": "未提供",
        },
        "degree_tier": {
            "phd_in_progress": "博士阶段",
            "phd_late_stage": "博士后期",
            "master": "硕士阶段",
            "bachelor": "本科阶段",
            "mixed_or_unclear": "不清晰",
        },
        "academic_signal_tier": {
            "very_strong": "很强",
            "strong": "较强",
            "moderate": "中等",
            "weak_or_unknown": "弱或未知",
        },
    }
    return labels.get(key, {}).get(value, value)


def _resume_to_text(resume: CandidateResume, education_blind: list[str]) -> str:
    sections: list[str] = [
        resume.id,
        resume.name,
        resume.target_role,
        resume.stage,
        " ".join(education_blind),
        " ".join(resume.directions),
    ]
    for project in resume.projects:
        sections.append(project.name)
        sections.extend(project.details)
    sections.extend(resume.publications)
    sections.append("、".join(resume.skills))
    sections.append("、".join(resume.directions))
    sections.append("、".join(resume.screening_tags))
    return "\n".join(section for section in sections if section)
