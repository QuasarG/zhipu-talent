from __future__ import annotations

import re

from pydantic import BaseModel, Field

from agi_talent_radar.core import llm_client
from agi_talent_radar.core.models import (
    BackgroundSignalTiers,
    CandidateResume,
    NormalizedResume,
    OrganizationSignalTier,
    ResumeExperience,
    ResumeProject,
)


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

ORGANIZATION_TIER_DEFINITIONS = {
    "organization_tier": {
        "large_scale": "成熟大型组织，仅表示协作和工程环境规模。",
        "established": "成熟专业组织或稳定研发团队。",
        "growth_stage": "成长阶段技术组织。",
        "early_stage": "早期或小型团队。",
        "academic_or_nonprofit": "学术、研究或非营利组织。",
        "public_sector": "政府、事业或公共部门。",
        "unknown": "缺少足够信息。",
    },
    "organization_type": {
        "technology_company": "技术企业",
        "industry_company": "行业企业",
        "startup": "初创团队",
        "research_institute": "研究机构",
        "university_lab": "高校实验室",
        "public_or_nonprofit": "公共或非营利组织",
        "unknown": "未知",
    },
    "sector": {
        "foundation_model_ai": "基础模型与 AI",
        "semiconductors_systems": "半导体与计算系统",
        "internet_software": "互联网与软件",
        "enterprise_software": "企业软件",
        "automotive_robotics": "汽车与机器人",
        "finance": "金融",
        "healthcare_lifescience": "医疗与生命科学",
        "security": "安全",
        "research_education": "科研与教育",
        "other_or_unknown": "其他或未知",
    },
}


NORMALIZER_PROMPT = """
你是 AI 人才潜力初评系统里的【背景信号标准化 Agent】。
只输出 JSON 对象，字段必须是 background_signal_tiers、education_notes 和 organization_signals。

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
6. 对每条实习/工作经历按 index 输出 organization_tier、organization_type 和 sector，只能使用 allowed_organization_tiers 的枚举。
7. organization_signals.rationale 不得出现机构全称、简称、品牌、产品或 Logo；机构档位只是低权重环境信号，不是候选人能力结论。

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
  ],
  "organization_signals": [
    {"index": 0, "organization_tier": "large_scale", "organization_type": "technology_company", "sector": "semiconductors_systems", "rationale": "成熟大型技术组织环境，仅用于理解工作约束。"}
  ]
}
""".strip()


class NormalizerOutput(BaseModel):
    background_signal_tiers: BackgroundSignalTiers
    education_notes: list[str] = Field(default_factory=list)
    organization_signals: list[OrganizationSignalTier] = Field(default_factory=list)


def run_normalizer(state: dict) -> dict:
    resume = CandidateResume.model_validate(state["resume"])
    rule_tiers = _infer_background_tiers(resume.education)
    rule_organizations = _infer_organization_signals(resume.experiences)
    adjudicated = _adjudicate_background_tiers(resume, rule_tiers, rule_organizations)
    education_blind = _blind_education(resume.education, adjudicated.background_signal_tiers, adjudicated.education_notes)
    experiences_blind = _blind_experiences(resume.experiences, adjudicated.organization_signals)
    scoring_resume = _redact_resume_organization_references(resume)
    normalized = NormalizedResume(
        id=resume.id,
        name=resume.name,
        target_role=scoring_resume.target_role,
        stage=resume.stage,
        education_raw=resume.education,
        education_blind=education_blind,
        background_signal_tiers=adjudicated.background_signal_tiers,
        directions=scoring_resume.directions,
        experiences_raw=resume.experiences,
        experiences_blind=experiences_blind,
        organization_signal_tiers=adjudicated.organization_signals,
        projects=scoring_resume.projects,
        publications=scoring_resume.publications,
        skills=scoring_resume.skills,
        screening_tags=scoring_resume.screening_tags,
        raw_text=_resume_to_text(scoring_resume, education_blind, experiences_blind),
    )
    return {
        **state,
        "normalized": normalized.model_dump(),
        "loop_count": int(state.get("loop_count", 0)),
    }


def _adjudicate_background_tiers(
    resume: CandidateResume,
    rule_tiers: BackgroundSignalTiers,
    rule_organizations: list[OrganizationSignalTier],
) -> NormalizerOutput:
    try:
        response = llm_client.call_llm_json(
            NORMALIZER_PROMPT,
            {
                "allowed_tiers": TIER_DEFINITIONS,
                "allowed_organization_tiers": ORGANIZATION_TIER_DEFINITIONS,
                "rule_guess": rule_tiers.model_dump(),
                "organization_rule_guess": [item.model_dump() for item in rule_organizations],
                "education_raw": resume.education,
                "experiences_raw": [item.model_dump() for item in resume.experiences],
                "target_role": resume.target_role,
                "stage": resume.stage,
            },
            temperature=0,
        )
        output = NormalizerOutput.model_validate(response)
        output.background_signal_tiers = _sanitize_tiers(output.background_signal_tiers, rule_tiers)
        output.education_notes = _sanitize_notes(output.education_notes)
        output.organization_signals = _sanitize_organization_signals(
            output.organization_signals,
            rule_organizations,
        )
        return output
    except Exception:
        return NormalizerOutput(
            background_signal_tiers=rule_tiers,
            education_notes=["背景信号由规则分级折叠，后续仅低权重参考。"],
            organization_signals=rule_organizations,
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


def _infer_organization_signals(experiences: list[ResumeExperience]) -> list[OrganizationSignalTier]:
    return [_infer_organization_signal(index, experience) for index, experience in enumerate(experiences)]


def _infer_organization_signal(index: int, experience: ResumeExperience) -> OrganizationSignalTier:
    text = " ".join(
        [experience.organization, experience.role, experience.experience_type, *experience.details]
    ).lower()
    if any(token in text for token in ("大学", "university", "实验室", "laboratory", "lab")):
        tier, organization_type = "academic_or_nonprofit", "university_lab"
    elif any(token in text for token in ("研究院", "研究所", "institute", "research center")):
        tier, organization_type = "academic_or_nonprofit", "research_institute"
    elif any(token in text for token in ("政府", "委员会", "事业单位", "government", "nonprofit")):
        tier, organization_type = "public_sector", "public_or_nonprofit"
    elif any(token in text for token in ("初创", "startup", "创业团队")):
        tier, organization_type = "early_stage", "startup"
    elif any(token in text for token in ("集团", "股份", "corporation", "company", " inc", "科技")):
        tier, organization_type = "established", "technology_company"
    else:
        tier, organization_type = "unknown", "unknown"
    sector = _organization_sector(text)
    return OrganizationSignalTier(
        index=index,
        organization_tier=tier,
        organization_type=organization_type,
        sector=sector,
        rationale="机构名称已折叠为低权重环境信号。",
    )


def _organization_sector(text: str) -> str:
    rules = (
        (("大模型", "基础模型", "llm", "artificial intelligence"), "foundation_model_ai"),
        (("芯片", "半导体", "gpu", "cuda", "compiler"), "semiconductors_systems"),
        (("安全", "security", "fuzz", "漏洞"), "security"),
        (("医疗", "生物", "药物", "health", "bio"), "healthcare_lifescience"),
        (("汽车", "机器人", "robot", "autonomous driving"), "automotive_robotics"),
        (("金融", "银行", "finance"), "finance"),
        (("大学", "研究院", "实验室", "university", "institute"), "research_education"),
        (("企业软件", "saas", "enterprise"), "enterprise_software"),
        (("互联网", "软件", "software", "internet"), "internet_software"),
    )
    for keywords, sector in rules:
        if any(keyword in text for keyword in keywords):
            return sector
    return "other_or_unknown"


def _sanitize_organization_signals(
    signals: list[OrganizationSignalTier],
    fallback: list[OrganizationSignalTier],
) -> list[OrganizationSignalTier]:
    by_index = {item.index: item for item in signals}
    result: list[OrganizationSignalTier] = []
    for default in fallback:
        item = by_index.get(default.index, default)
        data = item.model_dump()
        for key, allowed in ORGANIZATION_TIER_DEFINITIONS.items():
            if data.get(key) not in allowed:
                data[key] = getattr(default, key)
        data["index"] = default.index
        data["rationale"] = "机构名称已折叠为低权重环境信号，不直接参与能力加分。"
        result.append(OrganizationSignalTier.model_validate(data))
    return result


def _blind_experiences(
    experiences: list[ResumeExperience],
    signals: list[OrganizationSignalTier],
) -> list[ResumeExperience]:
    by_index = {item.index: item for item in signals}
    result: list[ResumeExperience] = []
    for index, experience in enumerate(experiences):
        signal = by_index.get(index, _infer_organization_signal(index, experience))
        organization = (
            f"机构规模={signal.organization_tier}；"
            f"机构类型={signal.organization_type}；"
            f"所属领域={signal.sector}；具体名称已脱敏"
        )
        result.append(
            experience.model_copy(
                update={
                    "organization": organization,
                    "role": _redact_organization(experience.role, experience.organization),
                    "experience_type": _redact_organization(experience.experience_type, experience.organization),
                    "details": [
                        _redact_organization(detail, experience.organization)
                        for detail in experience.details
                    ],
                }
            )
        )
    return result


def _redact_organization(text: str, organization: str) -> str:
    if not text or not organization:
        return text
    return re.sub(re.escape(organization), "[机构名称已脱敏]", text, flags=re.I)


def _redact_resume_organization_references(resume: CandidateResume) -> CandidateResume:
    organizations = [item.organization for item in resume.experiences if item.organization]
    if not organizations:
        return resume

    def redact(text: str) -> str:
        result = text
        for organization in organizations:
            result = _redact_organization(result, organization)
        return result

    projects = [
        ResumeProject(
            name=redact(project.name),
            details=[redact(detail) for detail in project.details],
        )
        for project in resume.projects
    ]
    return resume.model_copy(
        update={
            "target_role": redact(resume.target_role),
            "directions": [redact(item) for item in resume.directions],
            "projects": projects,
            "publications": [redact(item) for item in resume.publications],
            "skills": [redact(item) for item in resume.skills],
            "screening_tags": [redact(item) for item in resume.screening_tags],
        }
    )


def _education_to_text(education: list[dict | str]) -> str:
    """把 education 列表（含 dict 结构化对象）拍平成拼接文本。

    resumes 路径上 education 现在是 list[dict | str]，旧代码多处用
    " ".join(education) 假设纯字符串，遇到 dict 会崩。这里统一归一。
    """
    parts: list[str] = []
    for item in education or []:
        if isinstance(item, str):
            parts.append(item)
        elif isinstance(item, dict):
            # 结构化教育对象：拼成 "学校 学位 专业 时间"
            parts.append(" ".join(str(v) for v in item.values() if v))
    return " ".join(parts)


def _infer_background_tiers(education: list[dict | str]) -> BackgroundSignalTiers:
    text = _education_to_text(education)
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


def _blind_education(education: list[dict | str], tiers: BackgroundSignalTiers, notes: list[str]) -> list[str]:
    if not education:
        return notes
    result: list[str] = []
    for item in education:
        # education 现含结构化 dict，进 _degree_label/_field_hint 前先拍平成文本
        text = _education_item_to_text(item)
        degree = _degree_label(text, tiers.degree_tier)
        field = _field_hint(text)
        result.append(
            f"学校层级={_tier_label('school_tier', tiers.school_tier)}；"
            f"学历阶段={degree}；"
            f"学业信号={_tier_label('academic_signal_tier', tiers.academic_signal_tier)}；"
            f"专业方向={field}；具体学校/GPA/排名已折叠。"
        )
    return list(dict.fromkeys(result + notes))


def _education_item_to_text(item: dict | str) -> str:
    """单个 education 项拍平成文本：dict 取各字段值拼接，str 原样返回。"""
    if isinstance(item, str):
        return item
    if isinstance(item, dict):
        return " ".join(str(v) for v in item.values() if v)
    return str(item)


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


def _resume_to_text(
    resume: CandidateResume,
    education_blind: list[str],
    experiences_blind: list[ResumeExperience],
) -> str:
    sections: list[str] = [
        resume.id,
        resume.name,
        resume.target_role,
        resume.stage,
        " ".join(education_blind),
        " ".join(resume.directions),
    ]
    for experience in experiences_blind:
        sections.extend(
            [
                experience.organization,
                experience.role,
                experience.experience_type,
                experience.period,
                experience.start_date,
                experience.end_date,
                *experience.details,
            ]
        )
    for project in resume.projects:
        sections.append(project.name)
        sections.extend(project.details)
    sections.extend(resume.publications)
    sections.append("、".join(resume.skills))
    sections.append("、".join(resume.directions))
    sections.append("、".join(resume.screening_tags))
    return "\n".join(section for section in sections if section)
