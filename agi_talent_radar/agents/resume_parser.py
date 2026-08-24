from __future__ import annotations

import json
import re
from collections.abc import Iterable
from datetime import datetime

from json_repair import loads as repair_json_loads
from pydantic import BaseModel, Field, field_validator

from agi_talent_radar.core import llm_client
from agi_talent_radar.core.models import CandidateResume, ResumeExperience, ResumeProject


# LLM 自注"标题缺失/不列为论文" = 它自己都知道不是论文，兜底过滤
_VENUE_SELF_NOTE_RE = re.compile(r"标题缺失|不列为论文|无独立标题|非论文|OCR.*截断|残余.*期刊", re.IGNORECASE)


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


RESUME_PARSER_PROMPT = """
你是简历一次流式结构化 Agent。一次读取整份简历，一次完成全部字段提取。

只输出 JSON Lines（JSONL），禁止 Markdown、代码围栏、数组、说明文字和空行。
每一行必须是一个完整、单行、可独立解析的 JSON 对象；字符串中的换行必须转义为 \\n。
必须严格按以下顺序输出 6 行，即使某组没有信息也要输出 fields 为空值的对应行：
1. {"section":"basic","fields":{"name":"","target_role":"","stage":"","directions":[],"screening_tags":[]}}
2. {"section":"education","fields":{"education":[]}}
3. {"section":"experiences","fields":{"experiences":[]}}
4. {"section":"projects","fields":{"projects":[]}}
5. {"section":"publications","fields":{"publications":[]}}
6. {"section":"skills","fields":{"skills":[]}}

每一行输出前，必须确认该字段组已经从全文中提取完整；一行结束后不得在后续行补写该组。
不要重复 section，不要把同一条信息放入多个字段组。

字段规则：
- name: 姓名，如果没有则留空。
- target_role: 目标岗位/求职意向。
- stage: 根据 current_date 和入学/毕业年份换算当前实际年级，如「博二」「研一」；无法推算才用「博士在读」等模糊描述。
- directions: 研究方向列表。
- screening_tags: 筛选用方向、岗位关键词。
- education: 教育背景列表，每项必须是 JSON 对象，禁止输出 "学校:X；专业:Y" 这种合并字符串。
  字段：{"school": "院校", "degree": "学历层次", "major": "专业", "period": "起止时间", "year": "毕业年份"}。
  正确示例：{"school": "清华大学", "degree": "本科", "major": "计算机科学", "period": "2018-2022", "year": "2022"}。
  学历层次必须根据学位/阶段推断：本科/Bachelor/BEng/BS/Undergraduate → 本科；硕士/Master/MPhil/MSc → 硕士；
  博士/PhD/Doctoral → 博士。专业从原文学位名提取。每条教育经历的字段尽量都填，无对应信息留空字符串。
- experiences: 实习/工作/产业研究经历列表，每项 {"organization": "机构", "role": "岗位", "experience_type": "实习/全职/访问研究", "start_date": "", "end_date": "", "period": "", "details": ["职责/成果"]}
- projects: 项目/科研经历列表，每项 {"name": "项目名", "details": ["细节1", "细节2"]}
- publications: 代表成果/论文列表。每条必须是**有明确标题的具体论文**；
  期刊名/会议名本身（如 "Information Processing & Management 2025"）不是论文，禁止单独列为成果；
  标题被 OCR 截断或缺失时，宁缺毋滥，不要把残余的期刊/分区信息当成论文
- skills: 技能关键词列表。

规则：
1. 不要编造不存在的信息。
2. 对整份 raw_text 做全量解析，不得遗漏任意页面；visual_section_names 仅是版面提示。
3. 保留原文中的关键动作动词、技术栈和量化结果，不要过度改写。
4. 如果文本包含多位候选人，只解析当前这一位。
5. 实习/工作经历不得混入 projects；经历中的具体项目可保留在 details 中。
6. 期刊简介段落不是论文，禁止放进 publications。
7. has_ocr 为 true 时结合上下文修正明显 OCR 错字；无法辨认的乱码宁缺毋滥。
8. 原文段落可能被截断、中英文粘连；先在上下文中还原语义，再提取字段，但不要输出重组过程。
""".strip()


_STREAM_SECTIONS = {
    "basic": "基本信息",
    "education": "教育经历",
    "experiences": "工作经历",
    "projects": "项目经历",
    "publications": "论文成果",
    "skills": "技能",
}
_STREAM_SECTION_ALIASES = {
    **{key: key for key in _STREAM_SECTIONS},
    "基本信息": "basic",
    "教育": "education",
    "教育经历": "education",
    "经历": "experiences",
    "工作经历": "experiences",
    "项目": "projects",
    "项目经历": "projects",
    "论文": "publications",
    "论文成果": "publications",
    "技能": "skills",
}


def _decode_stream_line(line: str) -> tuple[str, ParsedResume] | None:
    """解析一条完整 JSONL 字段组；代码围栏行仅作兼容性忽略。"""
    text = line.strip()
    if not text or text.startswith("```"):
        return None
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        data = repair_json_loads(text)
    if not isinstance(data, dict):
        raise ValueError(f"简历结构化流不是 JSON 对象：{text[:120]}")
    section = _STREAM_SECTION_ALIASES.get(str(data.get("section", "")).strip())
    fields = data.get("fields")
    if section is None or not isinstance(fields, dict):
        raise ValueError(f"简历结构化流缺少合法 section/fields：{text[:120]}")
    return section, ParsedResume.model_validate(fields)


def _merge_parsed_resumes(parts: list[ParsedResume]) -> ParsedResume:
    """合并响应流字段组：单值取首个非空，列表按序拼接去重。"""
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
    pre_sections: list[dict[str, str]] | None = None,
) -> Iterable[tuple[str, str, int, int, object]]:
    """整份简历只调用一次 LLM，以 JSONL 字段组逐行增量 yield。

    每当一个字段组完整到达就 yield section，前端立即填充；流结束并校验六组
    齐全后 yield complete。一次简历解析只有一个 GLM 请求，不再按分节并发。
    """
    if not raw_text.strip():
        return
    current_date = datetime.now().strftime("%Y-%m-%d")
    total = len(_STREAM_SECTIONS)
    buffer = ""
    parts: list[ParsedResume] = []
    seen: set[str] = set()
    chunks = llm_client.call_llm_stream(
        RESUME_PARSER_PROMPT,
        {
            "raw_text": raw_text,
            "visual_section_names": [
                str(section.get("name", "")) for section in (pre_sections or []) if section.get("name")
            ],
            "current_date": current_date,
            "has_ocr": has_ocr,
        },
        temperature=0.1,
    )
    for chunk in chunks:
        buffer += chunk
        while "\n" in buffer:
            line, buffer = buffer.split("\n", 1)
            decoded = _decode_stream_line(line)
            if decoded is None:
                continue
            section, partial = decoded
            if section in seen:
                raise ValueError(f"简历结构化流重复字段组：{_STREAM_SECTIONS[section]}")
            parts.append(partial)
            seen.add(section)
            yield ("section", _STREAM_SECTIONS[section], len(seen), total, partial)
    decoded = _decode_stream_line(buffer)
    if decoded is not None:
        section, partial = decoded
        if section in seen:
            raise ValueError(f"简历结构化流重复字段组：{_STREAM_SECTIONS[section]}")
        parts.append(partial)
        seen.add(section)
        yield ("section", _STREAM_SECTIONS[section], len(seen), total, partial)

    missing = [key for key in _STREAM_SECTIONS if key not in seen]
    if missing:
        labels = "、".join(_STREAM_SECTIONS[key] for key in missing)
        raise ValueError(f"简历结构化流不完整，缺少字段组：{labels}")

    merged = _merge_parsed_resumes(parts)
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


def parse_raw_resume(
    resume_id: str, raw_text: str, has_ocr: bool = False, pre_sections: list[dict[str, str]] | None = None,
) -> CandidateResume:
    """同步解析（薄壳）：消费流式生成器，只返回完整结果。"""
    result = CandidateResume(id=resume_id)
    for kind, _, _, _, payload in iter_parse_resume_chunks(resume_id, raw_text, has_ocr=has_ocr, pre_sections=pre_sections):
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
