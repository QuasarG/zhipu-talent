from __future__ import annotations

import json
from datetime import datetime

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
    identity_decision: str = "new_person"
    matched_candidate_id: str = ""
    identity_confidence: float = Field(default=0, ge=0, le=1)
    identity_evidence: list[str] = Field(default_factory=list)
    identity_conflicts: list[str] = Field(default_factory=list)


class ImportOutput(BaseModel):
    candidates: list[ImportItem]


IMPORT_PROMPT = """
你是人才库批量导入 Agent。对导入的候选人做基本信息提取和轻量分类。

当前系统时间：{current_date}

输出格式（必须严格遵守）：
- 只输出 JSON Lines，每行一个候选人
- 每行必须是一个完整、独立的 JSON 对象
- 每个对象包含字段：id, name, target_role, stage, category, confidence, reason,
  identity_decision, matched_candidate_id, identity_confidence,
  identity_evidence, identity_conflicts
- 不要输出 markdown 代码块、不要输出顶层数组、不要输出任何解释文字

字段说明：
- id: 候选人 ID
- name: 姓名
- target_role: 目标岗位/方向
- stage: 当前阶段。根据上面的系统时间和简历中的入学/毕业年份，换算成当前实际年级（如「博二」「研一」「博四」）。只有无法推算时才用模糊描述（如「博士在读」）。
- category: 初步分类短标签，建议从以下选择：
  - 研究探索型
  - 工程闭环型
  - Agent / 工具杠杆型
  - 平台系统型
  - 应用验证型
  - 需补证观察型
- confidence: 分类置信度 0-1
- reason: 一句话分类理由
- identity_decision: 只能是 same_person 或 new_person。你必须综合新简历与
  existing_candidates 中的姓名变体、教育/任职时间线、研究方向、论文与项目判断。
- matched_candidate_id: 仅 same_person 时填写 existing_candidates 中真实存在的 id。
- identity_confidence: 身份判断置信度 0-1。
- identity_evidence: 支持身份判断的具体证据列表。
- identity_conflicts: 身份信息的冲突点列表，无冲突给空数组。

身份判断规则：
1. 是否同一人必须由你基于完整证据判断，服务端不使用姓名、邮箱或文本哈希硬编码归并。
2. 仅姓名相同不足以判 same_person；需要时间线、机构、方向、论文或项目等交叉证据。
3. existing_candidates 为空时只能判 new_person。
4. 不得编造 existing_candidates 中不存在的 matched_candidate_id。

示例输出（假设当前为 2025 年）：
{{"id": "c1", "name": "张三", "target_role": "大模型算法研究员", "stage": "博二", "category": "研究探索型", "confidence": 0.9, "reason": "研究经历以方法探索为主", "identity_decision": "same_person", "matched_candidate_id": "existing-1", "identity_confidence": 0.94, "identity_evidence": ["教育与任职时间线一致", "代表论文一致"], "identity_conflicts": []}}
{{"id": "c2", "name": "李四", "target_role": "AI 工程师", "stage": "硕士应届", "category": "工程闭环型", "confidence": 0.8, "reason": "工程项目闭环完整", "identity_decision": "new_person", "matched_candidate_id": "", "identity_confidence": 0.88, "identity_evidence": ["已有候选中没有一致的教育与项目经历"], "identity_conflicts": []}}

必须覆盖输入里的每一位候选人。
""".strip()


def run_import_agent(
    resumes: list[CandidateResume],
    persist: bool = True,
    identity_candidates: list[dict] | None = None,
) -> list[ImportClassification]:
    return list(run_import_agent_stream(resumes, persist=persist, identity_candidates=identity_candidates))


def run_import_agent_stream(
    resumes: list[CandidateResume],
    persist: bool = True,
    identity_candidates: list[dict] | None = None,
):
    """流式返回 ImportClassification，检测到一个完整候选人即 yield。

    使用 LLM 流式输出 + JSON Lines 解析，边接收边持久化，
    保证第一个候选人出现后即可被前端展示和评估。
    """
    compact = [_compact_resume(resume) for resume in resumes]
    current_date = datetime.now().strftime("%Y-%m-%d")
    stream = llm_client.call_llm_stream(
        IMPORT_PROMPT.format(current_date=current_date),
        {
            "candidates": compact,
            "existing_candidates": identity_candidates or [],
            "current_date": current_date,
        },
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
        known_ids = {str(candidate.get("id", "")) for candidate in (identity_candidates or [])}
        if item.identity_decision not in {"same_person", "new_person"}:
            raise ValueError(f"初筛 Agent 返回非法 identity_decision: {item.identity_decision}")
        if item.identity_decision == "same_person" and item.matched_candidate_id not in known_ids:
            raise ValueError(f"初筛 Agent 返回未知 matched_candidate_id: {item.matched_candidate_id}")
        classification = ImportClassification(
            id=item.id,
            name=item.name,
            category=item.category,
            confidence=item.confidence,
            reason=item.reason,
            identity_decision=item.identity_decision,
            matched_candidate_id=item.matched_candidate_id,
            identity_confidence=item.identity_confidence,
            identity_evidence=item.identity_evidence,
            identity_conflicts=item.identity_conflicts,
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
        "experiences": [experience.model_dump() for experience in resume.experiences],
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
