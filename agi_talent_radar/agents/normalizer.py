from __future__ import annotations

import re

from agi_talent_radar.core.models import CandidateResume, NormalizedResume


def run_normalizer(state: dict) -> dict:
    resume = CandidateResume.model_validate(state["resume"])
    normalized = NormalizedResume(
        id=resume.id,
        name=resume.name,
        target_role=resume.target_role,
        stage=resume.stage,
        education_raw=resume.education,
        education_blind=[_blind_education(item) for item in resume.education],
        directions=resume.directions,
        projects=resume.projects,
        publications=resume.publications,
        skills=resume.skills,
        screening_tags=resume.screening_tags,
        raw_text=_resume_to_text(resume),
    )
    return {
        **state,
        "normalized": normalized.model_dump(),
        "loop_count": int(state.get("loop_count", 0)),
    }


def _blind_education(text: str) -> str:
    replacements = [
        (r"某\s*985\s*高校|某985高校|985", "[Top-Tier Uni]"),
        (r"某\s*重点\s*(研究院|高校|大学)|某重点(研究院|高校|大学)", "[Research Institution]"),
        (r"某\s*双一流\s*高校|某双一流高校|双一流", "[Research Uni]"),
        (r"某\s*综合性\s*大学|某综合性大学", "[General Uni]"),
        (r"某\s*信息类\s*高校|某信息类高校", "[Specialized Uni]"),
        (r"某\s*航空航天类\s*高校|某航空航天类高校", "[Specialized Uni]"),
        (r"某\s*交通类\s*高校|某交通类高校", "[Specialized Uni]"),
        (r"某\s*理工类\s*高校|某理工类高校", "[STEM Uni]"),
        (r"某\s*创新型\s*大学|某创新型大学", "[Emerging Uni]"),
        (r"某\s*研究型\s*大学|某研究型大学", "[Research Uni]"),
    ]
    blinded = text
    for pattern, replacement in replacements:
        blinded = re.sub(pattern, replacement, blinded)
    blinded = re.sub(r"排名前\s*\d+%|专业排名前\s*\d+%|综合排名\s*\d+/\d+|GPA\s*[\d.]+/\d(?:\.\d)?|GPA\s*\d+/\d+", "[Academic Signal]", blinded)
    return blinded


def _resume_to_text(resume: CandidateResume) -> str:
    sections: list[str] = [
        resume.id,
        resume.name,
        resume.target_role,
        resume.stage,
        " ".join(resume.education),
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
