from __future__ import annotations

from pydantic import BaseModel, Field

from agi_talent_radar.core import llm_client
from agi_talent_radar.core.models import CandidateResume, ImportClassification


class InitialImportItem(BaseModel):
    id: str
    name: str
    initial_category: str
    confidence: float = Field(ge=0, le=1)
    reason: str


class InitialImportOutput(BaseModel):
    items: list[InitialImportItem]


class ReviewImportItem(BaseModel):
    id: str
    name: str
    final_category: str
    confidence: float = Field(ge=0, le=1)
    review_notes: str


class ReviewImportOutput(BaseModel):
    items: list[ReviewImportItem]


INITIAL_IMPORT_PROMPT = """
你是批量导入流程里的【初评分类 Agent】。
只输出 JSON 对象，顶层字段 items。

任务：
对导入的人才库做初步分类，只分类，不筛选、不淘汰。
分类用于前端左侧人才库快速浏览，不代表最终录用结论。

建议分类标签可从这些里面选，也可以给更准确的短标签：
- 研究探索型
- 工程闭环型
- Agent / 工具杠杆型
- 平台系统型
- 应用验证型
- 需补证观察型

每个 items 元素必须包含：
id, name, initial_category, confidence(0-1), reason。
必须覆盖输入里的每一位候选人。
""".strip()


REVIEW_IMPORT_PROMPT = """
你是批量导入流程里的【回顾确认 Agent】。
只输出 JSON 对象，顶层字段 items。

任务：
复核初评分类 Agent 的分类结果，修正明显不合适的类别。
不要筛掉任何候选人，只给 final_category、confidence 和 review_notes。
如果初评分类合理，可以沿用，但 review_notes 要说明为什么。

每个 items 元素必须包含：
id, name, final_category, confidence(0-1), review_notes。
必须覆盖输入里的每一位候选人。
""".strip()


def run_import_agents(resumes: list[CandidateResume]) -> tuple[list[ImportClassification], list[str]]:
    compact = [_compact_resume(resume) for resume in resumes]
    initial_response = llm_client.call_llm_json(
        INITIAL_IMPORT_PROMPT,
        {"candidates": compact},
        temperature=0.1,
    )
    initial = InitialImportOutput.model_validate(initial_response)
    _ensure_all_ids([item.id for item in initial.items], [resume.id for resume in resumes], "初评分类 Agent")

    review_response = llm_client.call_llm_json(
        REVIEW_IMPORT_PROMPT,
        {
            "candidates": compact,
            "initial_classifications": [item.model_dump() for item in initial.items],
        },
        temperature=0.1,
    )
    review = ReviewImportOutput.model_validate(review_response)
    _ensure_all_ids([item.id for item in review.items], [resume.id for resume in resumes], "回顾确认 Agent")

    initial_by_id = {item.id: item for item in initial.items}
    classifications = []
    for item in review.items:
        first = initial_by_id[item.id]
        classifications.append(
            ImportClassification(
                id=item.id,
                name=item.name,
                initial_category=first.initial_category,
                final_category=item.final_category,
                confidence=item.confidence,
                reason=first.reason,
                review_notes=item.review_notes,
            )
        )
    trace = [
        f"初评分类 Agent 已处理 {len(initial.items)} 位候选人。",
        f"回顾确认 Agent 已复核 {len(review.items)} 位候选人，未筛除任何候选人。",
    ]
    return classifications, trace


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


def _ensure_all_ids(returned_ids: list[str], expected_ids: list[str], node_name: str) -> None:
    missing = sorted(set(expected_ids) - set(returned_ids))
    extra = sorted(set(returned_ids) - set(expected_ids))
    if missing or extra:
        raise ValueError(f"{node_name} 返回候选人 ID 不完整，missing={missing}, extra={extra}")
