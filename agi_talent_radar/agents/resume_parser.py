from __future__ import annotations

import re
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from agi_talent_radar.core import llm_client
from agi_talent_radar.core.models import CandidateResume, ResumeExperience, ResumeProject


# LLM 自注"标题缺失/不列为论文" = 它自己都知道不是论文，兜底过滤
_VENUE_SELF_NOTE_RE = re.compile(r"标题缺失|不列为论文|无独立标题|非论文|OCR.*截断|残余.*期刊", re.IGNORECASE)
_SECTION_MAX_CHARS = 3000
_SECTION_WORKERS = 4


def _looks_like_venue_only(text: str) -> bool:
    """兜底过滤：只拦 LLM 自注"标题缺失/不列为论文"的条目。

    期刊名误判等语义问题交给结构化 LLM 的规则约束（prompt 里已写明
    "期刊名/会议名本身不是论文"），后端不做严苛规则判定。
    """
    return bool(_VENUE_SELF_NOTE_RE.search(text or ""))


class ParsedResume(BaseModel):
    name: str = ""
    target_role: str = ""
    stage: str = ""
    education: list[dict | str] = Field(default_factory=list)
    directions: list[str] = Field(default_factory=list)
    experiences: list[ResumeExperience] = Field(default_factory=list)
    projects: list[ResumeProject] = Field(default_factory=list)
    publications: list[str] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    screening_tags: list[str] = Field(default_factory=list)

    @field_validator("education", mode="before")
    @classmethod
    def _normalize_education(cls, value: object) -> list[dict | str]:
        """兜底：把"学校:X；学位:Y；专业:Z"格式的字符串拆回结构化对象。

        LLM 即使被 prompt 强制要求对象，输出混乱时仍可能吐字符串。
        这里识别 "k:v; k:v" 或 "k: v; k: v" 模式，拆成 edu dict。
        """
        if not isinstance(value, list):
            return []
        result: list[dict | str] = []
        for item in value:
            if isinstance(item, dict):
                result.append(item)
            elif isinstance(item, str):
                parsed = _parse_education_string(item)
                result.append(parsed if parsed else item)
        return result

    @field_validator("directions", "skills", "screening_tags", mode="before")
    @classmethod
    def _coerce_str_list(cls, value: object) -> list[str]:
        """LLM 可能把字符串列表项输出成 dict，归一成拼接字符串。"""
        return _coerce_to_str_list(value)

    @field_validator("publications", mode="before")
    @classmethod
    def _coerce_publications(cls, value: object) -> list[str]:
        """论文优先取 title；title 为空（期刊简介）丢弃，避免脏数据。"""
        items = _coerce_to_str_list(value, join_keys=("title", "venue", "year"), require_key="title")
        return [item for item in items if item.strip()]


def _coerce_to_str_list(
    value: object,
    join_keys: tuple[str, ...] = (),
    require_key: str = "",
) -> list[str]:
    """把 LLM 输出的字符串/对象列表归一成字符串列表。

    字符串原样保留；dict 按 join_keys 拼接成 "a. b. c" 格式
    （论文保持 "标题. 期刊 年份"，教育保持 "学校 学位"）；其他类型丢弃。
    require_key 指定时，该 key 为空的 dict 直接丢弃（如空 title 的期刊简介）。
    """
    if not isinstance(value, list):
        return []
    items: list[str] = []
    for item in value:
        if isinstance(item, str):
            items.append(item)
        elif isinstance(item, dict):
            if require_key and not str(item.get(require_key, "")).strip():
                continue  # 空 title 丢弃
            keys = join_keys or tuple(item.keys())
            parts = [str(item.get(k, "")).strip() for k in keys]
            parts = [p for p in parts if p]
            if parts:
                items.append(". ".join(parts))
    return items


class _ReorganizedSections(BaseModel):
    sections: list[dict[str, str]] = Field(default_factory=list)


REORGANIZE_PROMPT = """
你是简历文字重组 Agent。只输出 JSON 对象，顶层字段必须是 sections。

任务：把 OCR/PDF 提取的简历原始文字重新组织成逻辑分节。原始文字可能有
以下缺陷，需要修复：
1. 同一段落被截断到不同块（如"一区Information Processing&Management（IPM）2025.针对
   现有信息抽取..."），要把被拆散的句子重新拼回同一节。
2. 中英文之间粘连（如"一区Information"），按语义补空格。
3. OCR 错字漏字（0/O、1/l、形近字、断词），结合上下文修正明显错误。

要求：
1. 按语义把全文分成若干节，每节输出 {{"name": "节名", "text": "该节重组后的文字"}}。
   节名用：基本信息 / 教育 / 经历 / 论文 / 项目 / 技能 / 其他。
2. 内容只能重组和修复，不得增删编造；无法辨认的乱码保留原文。
3. 每节 text 长度不得超过 3000 字符；超长自动拆成多节（如 论文1 / 论文2）。
4. 保持原文顺序，不要打乱各节先后关系。
5. 期刊简介段落（介绍某期刊/会议本身的文字，不是候选人成果）单独归入"其他"，
   不得与"论文"节混在一起。
""".strip()


_EDU_KEY_ALIASES = {
    "学校": "school", "院校": "school", "university": "school", "college": "school", "school": "school",
    "学位": "degree", "学历": "degree", "degree": "degree", "阶段": "degree", "program": "degree",
    "专业": "major", "major": "major", "program": "major", "subject": "major", "方向": "major",
    "时间": "period", "period": "period", "起止": "period", "duration": "period", "日期": "period",
    "年份": "year", "year": "year", "入学": "year", "毕业": "year",
}


def _parse_education_string(text: str) -> dict | None:
    """把 "学校: X；学位: Y；专业: Z；时间: T" 字符串拆成 edu dict。

    识别 "键: 值" 的分号分隔列表。匹配不到键模式返回 None。
    """
    import re
    raw = (text or "").strip()
    if not raw:
        return None
    # 必须明确是 "k: v; k: v" 结构（至少 2 组），否则不误拆普通院校名
    parts = re.split(r"[;；]+", raw)
    pairs: list[tuple[str, str]] = []
    for part in parts:
        m = re.match(r"\s*([A-Za-z\u4e00-\u9fff]{1,6})\s*[:：]\s*(.+?)\s*$", part)
        if m:
            key_raw = m.group(1).strip().lower()
            value = m.group(2).strip()
            key = _EDU_KEY_ALIASES.get(key_raw)
            if key and value:
                pairs.append((key, value))
    if len(pairs) < 2:
        return None  # 不够当成结构化对象
    edu: dict[str, str] = {}
    for key, value in pairs:
        # 同一 key 出现多次时取首个非空
        if key not in edu:
            edu[key] = value
    return edu


def reorganize_resume_text(raw_text: str) -> list[dict[str, str]]:
    """第一层：修复 OCR 碎片并重组为逻辑分节，供并行结构化。"""
    if not raw_text.strip():
        return []
    response = llm_client.call_llm_json(
        REORGANIZE_PROMPT,
        {"raw_text": raw_text},
        temperature=0.1,
    )
    sections = _ReorganizedSections.model_validate(response).sections
    return [s for s in sections if str(s.get("text", "")).strip()]


RESUME_PARSER_PROMPT = """
你是简历结构化 Agent。只输出 JSON 对象。

当前系统时间：{current_date}

任务：
从简历文本中提取结构化字段。本输入是简历的一个分节（节名：{section_name}），
只提取这一节中出现的信息，其他字段给空。

输出字段：
- name: 姓名，如果没有则留空
- target_role: 目标岗位/求职意向
- stage: 当前阶段。根据上面的系统时间和简历中的入学/毕业年份，换算成当前实际年级（如「博二」「研一」「博四」）。只有无法推算时才用模糊描述（如「博士在读」）。
- education: 教育背景列表，**每项必须是 JSON 对象**，禁止输出 "学校:X；专业:Y" 这种合并字符串。
  字段：{{"school": "院校", "degree": "学历层次", "major": "专业", "period": "起止时间", "year": "毕业年份"}}。
  正确示例：{{"school": "清华大学", "degree": "本科", "major": "计算机科学", "period": "2018-2022", "year": "2022"}}。
  学历层次必须根据学位/阶段推断：本科/Bachelor/BEng/BS/Undergraduate → 本科；硕士/Master/MPhil/MSc → 硕士；
  博士/PhD/Doctoral → 博士。专业从原文学位名提取。每条教育经历的字段尽量都填，无对应信息留空字符串。
- directions: 研究方向列表
- experiences: 实习/工作/产业研究经历列表，每项 {{"organization": "机构", "role": "岗位", "experience_type": "实习/全职/访问研究", "start_date": "", "end_date": "", "period": "", "details": ["职责/成果"]}}
- projects: 项目/科研经历列表，每项 {{"name": "项目名", "details": ["细节1", "细节2"]}}
- publications: 代表成果/论文列表。每条必须是**有明确标题的具体论文**；
  期刊名/会议名本身（如 "Information Processing & Management 2025"）不是论文，禁止单独列为成果；
  标题被 OCR 截断或缺失时，宁缺毋滥，不要把残余的期刊/分区信息当成论文
- skills: 技能关键词列表
- screening_tags: 筛选用标签，如方向、岗位关键词

规则：
1. 不要编造不存在的信息。
2. 如果本分节中确实没有，给空值或空列表。
3. 保留原文中的关键动作动词、技术栈和量化结果，不要过度改写。
4. 如果文本包含多位候选人，只解析当前这一位。
5. 实习/工作经历不得混入 projects；经历中的具体项目可保留在 details 中。
6. 本分节不含某个字段时，该字段必须给空值，禁止从分节外脑补。
7. 期刊简介段落（介绍期刊本身的文字）不是论文，禁止放进 publications。
{ocr_rule}""".strip()

_OCR_RULE = (
    "8. 本分节含 OCR 识别结果，可能有错字漏字（0/O、1/l、形近字、断词）。"
    "请结合上下文修正明显识别错误；无法辨认的乱码不要照抄，宁缺毋滥。"
)


def _extract_section_fields(section: dict[str, str], current_date: str, has_ocr: bool) -> ParsedResume:
    """第二层：单个分节的结构化提取（并行单元）。"""
    response = llm_client.call_llm_json(
        RESUME_PARSER_PROMPT.format(
            current_date=current_date,
            section_name=str(section.get("name", "")),
            ocr_rule=_OCR_RULE if has_ocr else "",
        ),
        {"raw_text": str(section.get("text", "")), "current_date": current_date},
        temperature=0.1,
    )
    return ParsedResume.model_validate(response)


def _merge_parsed_resumes(parts: list[ParsedResume]) -> ParsedResume:
    """合并并行分节的解析结果：单值取首个非空，列表按序拼接去重。"""
    merged = ParsedResume()
    for part in parts:
        for field in ("name", "target_role", "stage"):
            if not getattr(merged, field) and getattr(part, field):
                setattr(merged, field, getattr(part, field))
        for field in (
            "education", "directions", "experiences", "projects",
            "publications", "skills", "screening_tags",
        ):
            values = getattr(merged, field) + getattr(part, field)
            seen: set[str] = set()
            unique = []
            for value in values:
                key = value.model_dump_json() if hasattr(value, "model_dump_json") else str(value)
                if key not in seen:
                    seen.add(key)
                    unique.append(value)
            setattr(merged, field, unique)
    return merged


def iter_parse_resume_chunks(
    resume_id: str,
    raw_text: str,
    has_ocr: bool = False,
) -> Iterable[tuple[str, str, int, int, object]]:
    """流式解析：先重组分节，再并行结构化，逐节 yield。

    每完成一节 yield ("section", 节名, 已完成数, 总节数, ParsedResume)；
    全部完成 yield ("complete", "", 总节数, 总节数, CandidateResume)。
    消费方（导入 SSE 流）可边收边展示，不必等全部解析完。
    """
    if not raw_text.strip():
        return
    current_date = datetime.now().strftime("%Y-%m-%d")
    sections = reorganize_resume_text(raw_text)
    if not sections:
        return
    total = len(sections)
    parts: list[tuple[int, ParsedResume]] = []
    with ThreadPoolExecutor(max_workers=_SECTION_WORKERS) as executor:
        futures = {
            executor.submit(_extract_section_fields, section, current_date, has_ocr): (index, section)
            for index, section in enumerate(sections)
        }
        for done, future in enumerate(as_completed(futures), start=1):
            index, section = futures[future]
            partial = future.result()
            parts.append((index, partial))
            yield ("section", str(section.get("name", "")), done, total, partial)
    parts.sort(key=lambda item: item[0])  # 保持原节序合并，结果稳定
    merged = _merge_parsed_resumes([partial for _, partial in parts])
    publications = [p for p in merged.publications if not _looks_like_venue_only(p)]
    yield (
        "complete", "", total, total,
        CandidateResume(
            id=resume_id,
            name=merged.name,
            target_role=merged.target_role,
            stage=merged.stage,
            education=merged.education,
            directions=merged.directions,
            experiences=merged.experiences,
            projects=merged.projects,
            publications=publications,
            skills=merged.skills,
            screening_tags=merged.screening_tags,
            raw_text=raw_text,
        ),
    )


def parse_raw_resume(resume_id: str, raw_text: str, has_ocr: bool = False) -> CandidateResume:
    """同步解析（薄壳）：消费流式生成器，只返回完整结果。"""
    result = CandidateResume(id=resume_id)
    for kind, _, _, _, payload in iter_parse_resume_chunks(resume_id, raw_text, has_ocr=has_ocr):
        if kind == "complete":
            result = payload
    return result


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
    parsed = parse_raw_resume(resume.id, resume.raw_text, has_ocr=bool(resume.ocr_pages))
    return parsed.model_copy(
        update={
            "source_format": resume.source_format,
            "document_analysis": resume.document_analysis,
            "ocr_pages": resume.ocr_pages,
        }
    )
