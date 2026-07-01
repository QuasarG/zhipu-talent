from __future__ import annotations

import json

from pydantic import BaseModel, Field

from agi_talent_radar.core import llm_client
from agi_talent_radar.core.models import CandidateResume, ImportClassification


class ImportItem(BaseModel):
    id: str
    name: str
    target_role: str = ""
    stage: str = ""
    category: str
    level: str = ""
    confidence: float = Field(ge=0, le=1)
    reason: str


class ImportOutput(BaseModel):
    candidates: list[ImportItem]


IMPORT_PROMPT = """
你是人才库批量导入 Agent。对导入的候选人做基本信息提取和轻量分类。

输出格式（必须严格遵守）：
- 只输出 JSON Lines，每行一个候选人
- 每行必须是一个完整、独立的 JSON 对象
- 每个对象包含字段：id, name, target_role, stage, category, level, confidence, reason
- 不要输出 markdown 代码块、不要输出顶层数组、不要输出任何解释文字

字段说明：
- id: 候选人 ID
- name: 姓名
- target_role: 目标岗位/方向
- stage: 当前阶段（如博一、博二、应届博士等）
- category: 初步分类短标签，建议从以下选择：
  - 研究探索型
  - 工程闭环型
  - Agent / 工具杠杆型
  - 平台系统型
  - 应用验证型
  - 需补证观察型
- level: 初筛潜力等级 S / A / B / C，用于导入后的初次排序（S 最高，C 最低），不是岗位职级
- confidence: 分类置信度 0-1
- reason: 一句话分类理由

示例输出：
{"id": "c1", "name": "张三", "target_role": "大模型算法研究员", "stage": "博士在读", "category": "研究探索型", "level": "A", "confidence": 0.9, "reason": "方向匹配度高"}
{"id": "c2", "name": "李四", "target_role": "AI 工程师", "stage": "硕士", "category": "工程闭环型", "level": "B", "confidence": 0.8, "reason": "工程能力强"}

必须覆盖输入里的每一位候选人。
""".strip()


def run_import_agent(resumes: list[CandidateResume], persist: bool = True) -> list[ImportClassification]:
    return list(run_import_agent_stream(resumes, persist=persist))


def run_import_agent_stream(
    resumes: list[CandidateResume], persist: bool = True
):
    """流式返回 ImportClassification，检测到一个完整候选人即 yield。

    使用 LLM 流式输出 + JSON Lines 解析，边接收边持久化，
    保证第一个候选人出现后即可被前端展示和评估。
    """
    compact = [_compact_resume(resume) for resume in resumes]
    stream = llm_client.call_llm_stream(
        IMPORT_PROMPT,
        {"candidates": compact},
        temperature=0.1,
    )
    resume_by_id = {resume.id: resume for resume in resumes}

    seen_ids: list[str] = []
    buffer = ""

    def _parse_line(line: str) -> ImportClassification | None:
        line = line.strip()
        if not line or line.startswith("```"):
            return None
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            return None
        item = ImportItem.model_validate(data)
        classification = ImportClassification(
            id=item.id,
            name=item.name,
            category=item.category,
            level=item.level,
            confidence=item.confidence,
            reason=item.reason,
        )
        if persist:
            _persist_single_import(resume_by_id[item.id], classification)
        return classification

    for token in stream:
        buffer += token
        lines = buffer.split("\n")
        buffer = lines.pop() if lines else ""
        for line in lines:
            classification = _parse_line(line)
            if classification:
                seen_ids.append(classification.id)
                yield classification

    if buffer.strip():
        classification = _parse_line(buffer)
        if classification:
            seen_ids.append(classification.id)
            yield classification

    _ensure_all_ids(seen_ids, [resume.id for resume in resumes])


def _persist_single_import(resume: CandidateResume, classification: ImportClassification) -> None:
    try:
        from agi_talent_radar.core.database import get_session, save_candidate

        with get_session() as session:
            save_candidate(session, resume, classification)
    except Exception as exc:
        import warnings

        warnings.warn(f"保存候选人到数据库失败: {exc}", stacklevel=2)


def _compact_resume(resume: CandidateResume) -> dict:
    return {
        "id": resume.id,
        "name": resume.name,
        "target_role": resume.target_role,
        "stage": resume.stage,
        "directions": resume.directions,
        "raw_text": resume.raw_text[:2000] if resume.raw_text else "",
        "project_names": [project.name for project in resume.projects],
        "project_details": [detail for project in resume.projects for detail in project.details[:2]],
        "skills": resume.skills,
        "screening_tags": resume.screening_tags,
    }


def _ensure_all_ids(returned_ids: list[str], expected_ids: list[str]) -> None:
    missing = sorted(set(expected_ids) - set(returned_ids))
    extra = sorted(set(returned_ids) - set(expected_ids))
    if missing or extra:
        raise ValueError(f"导入 Agent 返回候选人 ID 不完整，missing={missing}, extra={extra}")
