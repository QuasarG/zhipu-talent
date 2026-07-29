from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from agi_talent_radar.core import llm_client
from agi_talent_radar.core.models import CandidateResume, ResumeExperience, ResumeProject


class ParsedResume(BaseModel):
    name: str = ""
    target_role: str = ""
    stage: str = ""
    education: list[str] = Field(default_factory=list)
    directions: list[str] = Field(default_factory=list)
    experiences: list[ResumeExperience] = Field(default_factory=list)
    projects: list[ResumeProject] = Field(default_factory=list)
    publications: list[str] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    screening_tags: list[str] = Field(default_factory=list)


RESUME_PARSER_PROMPT = """
你是简历解析 Agent。只输出 JSON 对象。

当前系统时间：{current_date}

任务：
从任意格式的简历文本中提取结构化字段。文本可能是 Markdown、纯文本、JSONL 片段或 OCR 结果。

输出字段：
- name: 姓名，如果没有则留空
- target_role: 目标岗位/求职意向
- stage: 当前阶段。根据上面的系统时间和简历中的入学/毕业年份，换算成当前实际年级（如「博二」「研一」「博四」）。只有无法推算时才用模糊描述（如「博士在读」）。
- education: 教育背景列表，每项一条字符串
- directions: 研究方向列表
- experiences: 实习/工作/产业研究经历列表，每项 {{"organization": "机构", "role": "岗位", "experience_type": "实习/全职/访问研究", "start_date": "", "end_date": "", "period": "", "details": ["职责/成果"]}}
- projects: 项目/科研经历列表，每项 {{"name": "项目名", "details": ["细节1", "细节2"]}}
- publications: 代表成果/论文列表
- skills: 技能关键词列表
- screening_tags: 筛选用标签，如方向、岗位关键词

规则：
1. 不要编造不存在的信息。
2. 如果某字段在文本中确实没有，给空值或空列表。
3. 保留原文中的关键动作动词、技术栈和量化结果，不要过度改写。
4. 如果文本包含多位候选人，只解析当前这一位。
5. 实习/工作经历不得混入 projects；经历中的具体项目可保留在 details 中。
""".strip()


def parse_raw_resume(resume_id: str, raw_text: str) -> CandidateResume:
    if not raw_text.strip():
        return CandidateResume(id=resume_id)
    current_date = datetime.now().strftime("%Y-%m-%d")
    response = llm_client.call_llm_json(
        RESUME_PARSER_PROMPT.format(current_date=current_date),
        {"resume_id": resume_id, "raw_text": raw_text, "current_date": current_date},
        temperature=0.1,
    )
    parsed = ParsedResume.model_validate(response)
    return CandidateResume(
        id=resume_id,
        name=parsed.name,
        target_role=parsed.target_role,
        stage=parsed.stage,
        education=parsed.education,
        directions=parsed.directions,
        experiences=parsed.experiences,
        projects=parsed.projects,
        publications=parsed.publications,
        skills=parsed.skills,
        screening_tags=parsed.screening_tags,
        raw_text=raw_text,
    )


def ensure_structured_resume(resume: CandidateResume) -> CandidateResume:
    """如果简历只有 raw_text 而缺少结构化字段，调用 LLM 解析。"""
    has_structure = any([
        resume.name,
        resume.target_role,
        resume.stage,
        resume.education,
        resume.directions,
        resume.experiences,
        resume.projects,
        resume.publications,
        resume.skills,
    ])
    if has_structure:
        return resume
    if not resume.raw_text:
        return resume
    parsed = parse_raw_resume(resume.id, resume.raw_text)
    return parsed.model_copy(
        update={
            "source_format": resume.source_format,
            "document_analysis": resume.document_analysis,
        }
    )
