"""奖学金四阶段管道：资格筛选 → 脱敏评分 → 舆情扫描 → 总分计算。

LLM 与外部检索都做成可注入参数，测试用 fake 替换，不打外网。
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Callable

from agi_talent_radar.core.db.orm import (
    ScholarshipApplicationORM,
    ScholarshipEvaluationORM,
    ScholarshipMaterialORM,
    ScholarshipReputationItemORM,
)
from agi_talent_radar.scholarship.anonymize import anonymize_text, build_identities, check_leak
from agi_talent_radar.scholarship.scoring import (
    DIMENSIONS,
    ELIGIBILITY,
    FOCUS_DIRECTIONS,
    MIN_LETTERS,
    REQUIRED_KINDS,
    REPUTATION_CAP,
    REPUTATION_ITEM_POINTS,
    config_version,
)

logger = logging.getLogger(__name__)

_TEXT_BUDGET = 6000  # 每类材料喂给评分 LLM 的最大字符数

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
# 阶段 2：脱敏 + 评分
# ---------------------------------------------------------------------------


def evaluate_application(session, app: ScholarshipApplicationORM, llm: Callable | None = None) -> ScholarshipEvaluationORM:
    if llm is None:
        from agi_talent_radar.core.llm_client import call_llm_json

        llm = call_llm_json

    evaluation = ScholarshipEvaluationORM(
        application_id=app.id, config_version=config_version(), status="running"
    )
    session.add(evaluation)
    session.commit()
    try:
        identities = build_identities(app)
        bundle = _anonymized_bundle(_materials(session, app), app.direction, identities)
        data = llm(_SCORING_PROMPT, bundle)
        dimensions = _parse_dimensions(data)
        blind = round(sum(d["score"] / 5.0 * d["max_points"] for d in dimensions), 1)
        evaluation.dimensions = dimensions
        evaluation.blind_score = blind
        evaluation.highlights = [str(x) for x in (data.get("highlights") or [])][:8]
        evaluation.risks = [str(x) for x in (data.get("risks") or [])][:8]
        evaluation.status = "completed"
        evaluation.completed_at = datetime.now(timezone.utc).replace(tzinfo=None)
        app.status = "scored"
    except Exception as exc:  # noqa: BLE001
        logger.exception("奖学金评分失败")
        evaluation.status = "failed"
        evaluation.error_message = str(exc)
    session.commit()
    return evaluation


def _anonymized_bundle(materials: list[ScholarshipMaterialORM], direction: str, identities: dict[str, list[str]]) -> dict[str, Any]:
    """各材料脱敏后按类拼接；泄漏残留直接抹掉（二次替换兜底）。"""
    parts: dict[str, list[str]] = {}
    for material in materials:
        text = anonymize_text(material.raw_text or "", identities)
        leaks = check_leak(text, identities)
        for leak in leaks:
            text = text.replace(leak, "[已脱敏]")
        material.anonymized_text = text
        parts.setdefault(material.kind, []).append(text[:_TEXT_BUDGET])
    return {
        "materials": {kind: "\n\n".join(texts) for kind, texts in parts.items()},
        "focus_directions": FOCUS_DIRECTIONS,
        "dimensions": [{"key": d["key"], "label": d["label"], "max_points": d["max_points"]} for d in DIMENSIONS],
        "declared_direction": direction,
    }


_SCORING_PROMPT = """你是 Z.AI Scholarship 的匿名评审。所有材料已脱敏（[学校A]/[导师B] 等占位符），
严禁猜测或还原任何身份，只允许依据材料内容评分。

对每个维度给 0-5 分并给一句理由（证据封顶：无量化指标/产物/正式发表的陈述封顶 2.5；
仅方向性描述封顶 3）。推荐信只看背书内容的具体程度。

只输出 JSON：
{"dimensions": [{"key": "...", "score": 0-5, "reason": "..."}],
 "highlights": ["最多5条亮点"], "risks": ["最多5条风险点"]}"""


def _parse_dimensions(data: dict[str, Any]) -> list[dict[str, Any]]:
    by_key = {d["key"]: d for d in DIMENSIONS}
    result = []
    for item in data.get("dimensions") or []:
        key = str(item.get("key") or "")
        spec = by_key.get(key)
        if not spec:
            continue
        score = max(0.0, min(5.0, float(item.get("score") or 0)))
        result.append({**spec, "score": score, "reason": str(item.get("reason") or "")})
    for spec in DIMENSIONS:
        if spec["key"] not in {d["key"] for d in result}:
            result.append({**spec, "score": 0.0, "reason": "LLM 未返回该维度"})
    return result


# ---------------------------------------------------------------------------
# 阶段 3：舆情扫描 + 人工核验计分
# ---------------------------------------------------------------------------


def run_reputation_scan(session, app: ScholarshipApplicationORM, search_fn: Callable | None = None) -> list[ScholarshipReputationItemORM]:
    """对申请人+每位导师做正负双轨检索，生成待核验条目。"""
    if search_fn is None:
        from agi_talent_radar.core.connectors.web_search import search_web

        search_fn = search_web

    subjects = [(app.name, "applicant")] + [(a, "advisor") for a in (app.advisors or []) if str(a).strip()]
    created: list[ScholarshipReputationItemORM] = []
    for name, role in subjects:
        for sentiment, query in (
            ("negative", f"{name} 争议 质疑 学术不端 翻车"),
            ("positive", f"{name} 获奖 成就 表彰"),
        ):
            try:
                facts = search_fn(query, count=5)
            except Exception as exc:  # noqa: BLE001
                logger.warning("舆情检索失败 %s：%s", name, exc)
                continue
            for fact in facts:
                payload = fact.payload or {}
                title = str(payload.get("title") or "")
                snippet = str(payload.get("content") or "")[:200]
                if name and name not in (title + snippet):
                    continue  # 同名新闻降噪
                item = ScholarshipReputationItemORM(
                    application_id=app.id,
                    subject=name,
                    subject_role=role,
                    sentiment=sentiment,
                    title=title,
                    url=fact.source_url or "",
                    snippet=snippet,
                    concern="检索命中，需人工判断真伪与相关性",
                )
                session.add(item)
                created.append(item)
    session.commit()
    return created


def review_reputation_item(session, item_id: int, action: str, reviewer: str = "") -> ScholarshipReputationItemORM | None:
    """人工确认/驳回；确认才计分。"""
    if action not in {"confirmed", "dismissed"}:
        raise ValueError("action 必须是 confirmed 或 dismissed。")
    item = session.get(ScholarshipReputationItemORM, item_id)
    if item is None:
        return None
    item.review_status = action
    item.reviewer = reviewer
    item.reviewed_at = datetime.now(timezone.utc)
    item.adjustment = (
        REPUTATION_ITEM_POINTS if item.sentiment == "positive" else -REPUTATION_ITEM_POINTS
    ) if action == "confirmed" else 0.0
    session.commit()
    return item


# ---------------------------------------------------------------------------
# 阶段 4：总分与排序
# ---------------------------------------------------------------------------


def reputation_adjustment(session, app: ScholarshipApplicationORM) -> float:
    total = (
        session.query(ScholarshipReputationItemORM)
        .filter_by(application_id=app.id, review_status="confirmed")
        .with_entities(ScholarshipReputationItemORM.adjustment)
        .all()
    )
    value = sum(row[0] for row in total)
    return max(-REPUTATION_CAP, min(REPUTATION_CAP, value))


def total_score(session, app: ScholarshipApplicationORM) -> float | None:
    completed = (
        session.query(ScholarshipEvaluationORM)
        .filter_by(application_id=app.id, status="completed")
        .order_by(ScholarshipEvaluationORM.id.desc())
        .first()
    )
    if not completed:
        return None
    # 现行奖学金分数只由脱敏评分和已确认舆情调整构成。
    # brand_bonus 字段保留在旧数据库中，仅用于兼容历史数据，不再参与计算。
    return round(completed.blind_score + reputation_adjustment(session, app), 1)
