"""奖学金管道：资格筛选（评分走 scorer_agent ReAct 循环，旧舆情扫描已并入 agent）。

LLM 与外部检索都做成可注入参数，测试用 fake 替换，不打外网。
"""
from __future__ import annotations

import logging
from typing import Callable

from agi_talent_radar.core.db.orm import (
    ScholarshipApplicationORM,
    ScholarshipEvaluationORM,
    ScholarshipMaterialORM,
)
from agi_talent_radar.scholarship.scoring import (
    ELIGIBILITY,
    FOCUS_DIRECTIONS,
    MIN_LETTERS,
    REQUIRED_KINDS,
)

logger = logging.getLogger(__name__)

_DIRECTION_KEYWORDS = (
    "人工智能", "机器学习", "深度学习", "大模型", "llm", "foundation", "多模态", "multimodal",
    "agent", "智能体", "强化学习", "reinforcement", "ai infra", "ai4s", "science",
    "具身", "embodied", "计算机", "computer", "自然语言", "nlp", "cv", "视觉", "agi",
    "基础科学", "数学", "物理", "neural", "transformer", "diffusion",
)


# ---------------------------------------------------------------------------
# 阶段 1：资格与完整性（确定性规则；方向不明确时才问 LLM）
# ---------------------------------------------------------------------------


def _materials(session, app: ScholarshipApplicationORM) -> list[ScholarshipMaterialORM]:
    """直接查库：relationship 集合在长会话里可能是旧快照。"""
    return (
        session.query(ScholarshipMaterialORM)
        .filter_by(application_id=app.id)
        .order_by(ScholarshipMaterialORM.id)
        .all()
    )


def screen_application(session, app: ScholarshipApplicationORM, llm_judge: Callable | None = None) -> dict:
    kinds = [m.kind for m in _materials(session, app)]
    missing = [k for k in REQUIRED_KINDS if k not in kinds]
    if kinds.count("letter") < MIN_LETTERS:
        missing.append("letter")

    reasons: list[str] = []
    if app.degree_type not in ELIGIBILITY["degree_types"]:
        reasons.append("申请人须为硕士或博士研究生")
    grad = (app.expected_graduation or "").strip()
    if not grad:
        reasons.append("缺少预计毕业时间")
    elif grad < ELIGIBILITY["min_graduation"]:
        reasons.append(f"预计毕业时间须不早于 {ELIGIBILITY['min_graduation']}")
    direction_ok, direction_reason = _direction_relevant(app.direction, llm_judge)
    if not direction_ok:
        reasons.append(direction_reason)

    if missing:
        status = "material_incomplete"
    elif reasons:
        status = "ineligible"
    else:
        status = "eligible"
    app.status = status
    app.screening_detail = {"missing": missing, "reasons": reasons}
    session.commit()
    return {"status": status, "missing": missing, "reasons": reasons}


def _direction_relevant(direction: str, llm_judge: Callable | None) -> tuple[bool, str]:
    text = (direction or "").strip()
    if not text:
        return False, "缺少研究方向"
    lowered = text.lower()
    if any(k in lowered or k in text for k in _DIRECTION_KEYWORDS):
        return True, ""
    if llm_judge is None:
        from agi_talent_radar.core.llm_client import call_llm_json

        def llm_judge(prompt: str, payload: dict) -> dict:
            return call_llm_json(prompt, payload)

    try:
        data = llm_judge(
            "判断给定研究方向是否与人工智能、计算机科学、基础科学或 AGI 前沿相关。"
            '只输出 JSON：{"relevant": true/false, "reason": "一句话"}',
            {"direction": text, "focus_directions": FOCUS_DIRECTIONS},
        )
        if data.get("relevant"):
            return True, ""
        return False, f"研究方向与 AGI 前沿不相关：{data.get('reason', '')}"
    except Exception as exc:  # noqa: BLE001
        logger.warning("方向相关性判断失败：%s", exc)
        return False, "方向相关性自动判断失败，需人工确认"


# ---------------------------------------------------------------------------
# 总分与排序（评分由 scorer_agent 完成；舆情已并入 agent，人工参考不计自动分）
# ---------------------------------------------------------------------------


def total_score(session, app: ScholarshipApplicationORM) -> float | None:
    completed = (
        session.query(ScholarshipEvaluationORM)
        .filter_by(application_id=app.id, status="completed")
        .order_by(ScholarshipEvaluationORM.id.desc())
        .first()
    )
    if not completed:
        return None
    return round(completed.blind_score, 1)
