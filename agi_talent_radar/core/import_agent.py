from __future__ import annotations

from pydantic import BaseModel, Field

from agi_talent_radar.core import llm_client
from agi_talent_radar.core.models import CandidateResume, ImportClassification


class ImportItem(BaseModel):
    id: str
    name: str
    target_role: str = ""
    stage: str = ""
    category: str
    confidence: float = Field(ge=0, le=1)
    reason: str


class ImportOutput(BaseModel):
    items: list[ImportItem]


IMPORT_PROMPT = """
你是人才库批量导入 Agent。只输出 JSON 对象，顶层字段 items。

任务：
对导入的候选人做基本信息提取和轻量分类，用于前端人才库列表展示。
不要打分、不要筛选、不要淘汰任何人。

每个 items 元素必须包含：
- id: 候选人 ID
- name: 姓名
- target_role: 目标岗位/方向
- stage: 当前阶段（如博一、博二、应届博士等）
- category: 初步分类短标签，建议从以下选择，也可给更准确的短标签：
  - 研究探索型
  - 工程闭环型
  - Agent / 工具杠杆型
  - 平台系统型
  - 应用验证型
  - 需补证观察型
- confidence: 分类置信度 0-1
- reason: 一句话分类理由

必须覆盖输入里的每一位候选人。
""".strip()


def run_import_agent(resumes: list[CandidateResume]) -> list[ImportClassification]:
    compact = [_compact_resume(resume) for resume in resumes]
    response = llm_client.call_llm_json(
        IMPORT_PROMPT,
        {"candidates": compact},
        temperature=0.1,
    )
    parsed = ImportOutput.model_validate(response)
    _ensure_all_ids([item.id for item in parsed.items], [resume.id for resume in resumes])
    return [
        ImportClassification(
            id=item.id,
            name=item.name,
            category=item.category,
            confidence=item.confidence,
            reason=item.reason,
        )
        for item in parsed.items
    ]


def _compact_resume(resume: CandidateResume) -> dict:
    return {
        "id": resume.id,
        "name": resume.name,
        "target_role": resume.target_role,
        "stage": resume.stage,
        "directions": resume.directions,
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
