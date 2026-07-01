from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from agi_talent_radar.core.models import CandidateEvaluation, CandidateResume, ResumeProject


def load_resumes(path: str | Path) -> list[CandidateResume]:
    source = Path(path)
    if not source.exists():
        raise FileNotFoundError(f"找不到简历文件: {source}")
    if source.suffix.lower() == ".jsonl":
        return _load_jsonl(source)
    if source.suffix.lower() == ".md":
        return _load_markdown(source)
    if source.suffix.lower() == ".txt":
        return _load_text(source)
    raise ValueError(f"暂不支持的简历格式: {source.suffix}")


def _load_jsonl(path: Path) -> list[CandidateResume]:
    items: list[CandidateResume] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        data = json.loads(line)
        items.append(CandidateResume.model_validate(data))
    return items


def _load_markdown(path: Path) -> list[CandidateResume]:
    text = path.read_text(encoding="utf-8")
    chunks = re.split(r"\n---\n\s*\n", text)
    resumes: list[CandidateResume] = []
    for chunk in chunks:
        title_match = re.search(r"##\s+候选人\s*(\d+).*", chunk)
        if not title_match:
            continue
        number = title_match.group(1).zfill(2)
        name = f"候选人{number}"
        target_role = _first_group(chunk, r"\*\*求职意向\*\*：(.+)")
        stage = _first_group(chunk, r"\*\*当前阶段\*\*：(.+)")
        education = _list_after_heading(chunk, r"\*\*教育背景\*\*：")
        directions_text = _first_group(chunk, r"\*\*研究方向\*\*：(.+)")
        directions = _split_terms(directions_text)
        projects = _projects_from_markdown(chunk)
        publications = _list_after_heading(chunk, r"\*\*代表成果\*\*：")
        skills_text = _first_group(chunk, r"\*\*技能关键词\*\*：(.+)")
        resumes.append(
            CandidateResume(
                id=f"candidate_{number}",
                name=name,
                target_role=target_role,
                stage=stage,
                education=education,
                directions=directions,
                projects=projects,
                publications=publications,
                skills=_split_terms(skills_text),
                screening_tags=[],
            )
        )
    return resumes


def _load_text(path: Path) -> list[CandidateResume]:
    """单个 .txt 文件视为一位候选人的原始简历文本。"""
    raw_text = path.read_text(encoding="utf-8")
    return [CandidateResume(id=path.stem, raw_text=raw_text)]


def _first_group(text: str, pattern: str) -> str:
    match = re.search(pattern, text)
    return match.group(1).strip() if match else ""


def _split_terms(text: str) -> list[str]:
    clean = text.replace("、", ",").replace("，", ",").replace("。", "")
    return [part.strip() for part in clean.split(",") if part.strip()]


def _list_after_heading(text: str, heading_pattern: str) -> list[str]:
    match = re.search(heading_pattern + r"\s*(?P<body>.*?)(?:\n\*\*|\n##|\Z)", text, re.S)
    if not match:
        return []
    body = match.group("body")
    return [
        re.sub(r"^\s*-\s*", "", line).strip()
        for line in body.splitlines()
        if line.strip().startswith("-")
    ]


def _projects_from_markdown(text: str) -> list[ResumeProject]:
    section_match = re.search(r"\*\*(?:科研|项目|实习)经历\*\*：(?P<body>.*?)(?:\n\*\*代表成果|\n##|\Z)", text, re.S)
    if not section_match:
        return []
    body = section_match.group("body")
    projects: list[ResumeProject] = []
    for line in body.splitlines():
        line = line.strip()
        if not line.startswith("-"):
            continue
        name = _first_group(line, r"\*\*(.+?)\*\*")
        detail = re.sub(r"^\s*-\s*\*\*.+?\*\*：?", "", line).strip()
        if name:
            projects.append(ResumeProject(name=name, details=[detail] if detail else []))
    return projects


def save_json(path: str | Path, payload: Any) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def render_summary_markdown(evaluations: list[CandidateEvaluation]) -> str:
    lines = [
        "# AI 人才潜力初评结果",
        "",
        "## 横向排序",
        "",
        "| 排名 | 候选人 | 综合分 | 潜力等级 | 分层 | 一句话画像 |",
        "| ---: | --- | ---: | --- | --- | --- |",
    ]
    for index, item in enumerate(evaluations, start=1):
        lines.append(
            f"| {index} | {item.name} | {item.overall_score} | {item.level} | {item.tier} | {item.one_liner} |"
        )
    lines.extend(["", "## 候选人明细", ""])
    for item in evaluations:
        lines.extend(
            [
                f"### {item.name}｜{item.target_role}",
                "",
                f"- 综合评分：{item.overall_score} / 100（潜力等级 {item.level}，{item.tier}）",
                f"- 决策方式：{item.decision_method}",
                f"- 人才画像：{item.one_liner}",
                f"- 核心优势：{'；'.join(item.core_strengths)}",
                f"- 风险 / 待验证：{'；'.join(item.potential_risks)}",
                f"- 建议培养方向：{'；'.join(item.cultivation_direction)}",
                "- 面谈追问：",
            ]
        )
        for question in item.interview_questions:
            lines.append(f"  - {question}")
        lines.extend(["", "- 关键证据："])
        for evidence in item.evidence[:5]:
            lines.append(f"  - [{evidence.source}] {evidence.quote}")
        lines.append("")
    return "\n".join(lines)
