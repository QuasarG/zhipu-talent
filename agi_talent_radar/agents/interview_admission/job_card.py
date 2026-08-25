from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

from agi_talent_radar.core import llm_client

from .contracts import AssessmentCard, CardQualityReview


CARD_GENERATION_PROMPT = """
你是面试准入系统的岗位评估卡生成 Agent。只输出 JSON 对象。

目标：把 JD 转成 3–5 个、最多 6 个可稳定评分的核心任务。真正判定的是候选人能否完成
岗位核心任务；学历和专业只能作为背景证据，不能成为硬门槛。到岗时间、实习时长、地点、
薪资、工作时段等可用性条件不得进入岗位评估卡。

每个任务必须描述清楚实际要完成的工作、评价时看什么项目事实，并提供任务化等级锚点：
- level_2：有真实参与并完成局部工作；
- level_3：能够独立完成核心任务；
- level_4：在复杂场景中成熟胜任并形成可靠结果。
不要机械要求数字、特定技能栏关键词或某个框架名；应从项目实际内容判断能力。未写某工具不等于不会。

importance 只能是 primary / major / supporting，分别表示首要 / 主要 / 补充。
id 只能用小写字母、数字和下划线。

输出：
{
  "role_summary": "岗位核心使命",
  "core_tasks": [{
    "id": "task_slug",
    "title": "任务名",
    "description": "该任务实际要完成什么",
    "importance": "primary|major|supporting",
    "evaluation_focus": "从候选人的哪些真实工作、难度、贡献和结果判断",
    "anchors": {"level_2": "...", "level_3": "...", "level_4": "..."}
  }],
  "background_evidence_guidance": "学历、专业和研究背景如何只作为迁移理解的辅助证据",
  "excluded_requirements": ["从原 JD 中排除的可用性条件"]
}
""".strip()


CARD_REVIEW_PROMPT = """
你是岗位评估卡质检 Agent。只输出 JSON 对象。

检查任务覆盖是否完整、任务是否重复、粒度是否适合逐项评分、importance 是否合理、2/3/4
锚点是否能区分参与/独立/成熟胜任。学历专业只能是背景证据；到岗、实习时长、地点、薪资等
可用性条件不得参与能力评估。任务不得依赖技能栏是否写出某个工具，也不得机械要求数字。

输出：{"passed": true|false, "issues": ["问题"], "revision_instructions": ["具体修改要求"]}
""".strip()


LlmCallable = Callable[[str, dict[str, Any]], dict[str, Any]]
EventObserver = Callable[[dict[str, Any]], None]


def generate_assessment_card(
    title: str,
    team: str,
    raw_text: str,
    supplements: list[str] | None = None,
    llm: LlmCallable | None = None,
    on_event: EventObserver | None = None,
    on_call: llm_client.CallObserver | None = None,
) -> AssessmentCard:
    """生成并质检岗位卡；质检不通过时最多按反馈修正一次。"""
    invoke = llm or _default_llm(on_call)
    payload: dict[str, Any] = {
        "title": title,
        "team": team,
        "jd": raw_text,
        "supplementary_requirements": supplements or [],
    }
    _emit(on_event, "card_generation", "running", "正在从 JD 提炼核心任务")
    candidate = _validated_card(invoke(CARD_GENERATION_PROMPT, payload))
    _emit(on_event, "card_generation", "completed", f"生成 {len(candidate.core_tasks)} 个核心任务")

    for review_round in range(2):
        _emit(on_event, "card_quality_review", "running", "正在检查任务覆盖与评分锚点")
        review = CardQualityReview.model_validate(
            invoke(
                CARD_REVIEW_PROMPT,
                {"jd": raw_text, "supplementary_requirements": supplements or [], "card": candidate.model_dump()},
            )
        )
        if review.passed:
            _emit(on_event, "card_quality_review", "completed", "岗位评估卡质检通过")
            return candidate
        _emit(
            on_event,
            "card_quality_review",
            "needs_revision",
            "；".join(review.issues) or "岗位卡需要修正",
        )
        if review_round == 1:
            raise ValueError("岗位评估卡自动修正后仍未通过质检：" + "；".join(review.issues))
        _emit(on_event, "card_revision", "running", "正在按质检反馈修正岗位卡")
        candidate = _validated_card(
            invoke(
                CARD_GENERATION_PROMPT,
                {
                    **payload,
                    "previous_card": candidate.model_dump(),
                    "quality_issues": review.issues,
                    "revision_instructions": review.revision_instructions,
                },
            )
        )
        _emit(on_event, "card_revision", "completed", "岗位卡修正完成")

    raise RuntimeError("岗位评估卡生成流程异常结束")


def _default_llm(on_call: llm_client.CallObserver | None) -> LlmCallable:
    def invoke(prompt: str, payload: dict[str, Any]) -> dict[str, Any]:
        node_id = "card_generation" if prompt == CARD_GENERATION_PROMPT else "card_quality_review"
        return llm_client.call_llm_json(
            prompt,
            payload,
            temperature=0.2 if prompt == CARD_GENERATION_PROMPT else 0.05,
            deep=True,
            on_call=(lambda item: on_call({**item, "node_id": node_id})) if on_call else None,
        )

    return invoke


def _validated_card(raw: dict[str, Any]) -> AssessmentCard:
    normalized = dict(raw)
    tasks = []
    for index, item in enumerate(raw.get("core_tasks", [])):
        if not isinstance(item, dict):
            continue
        task = dict(item)
        slug = re.sub(r"[^a-z0-9_]+", "_", str(task.get("id", "")).lower()).strip("_")
        task["id"] = slug or f"core_task_{index + 1}"
        tasks.append(task)
    normalized["core_tasks"] = tasks[:6]
    return AssessmentCard.model_validate(normalized)


def _emit(
    observer: EventObserver | None,
    node_id: str,
    status: str,
    summary: str,
) -> None:
    if observer is not None:
        observer({"node_id": node_id, "status": status, "summary": summary})
