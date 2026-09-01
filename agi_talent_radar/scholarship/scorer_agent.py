"""奖学金评分 ReAct agent：读材料 → 查证 → 舆情 → 提交评分。

循环骨架移植自 knowledge_agent.agent（砍掉对话历史与 HITL 门控），
trace 以 segments 形态实时写入 evaluation.trace，SSE 事件流给前端
渲染成"agent 工作记录"（复用问答的 ToolCallCard/ThinkingOrb 动效）。
"""
from __future__ import annotations

import copy
import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Callable

from agi_talent_radar.core.db.orm import (
    ScholarshipApplicationORM,
    ScholarshipEvaluationORM,
    ScholarshipMaterialORM,
)
from agi_talent_radar.scholarship.anonymize import anonymize_text
from agi_talent_radar.scholarship.scorer_tools import (
    MAX_ROUNDS,
    TOOL_RESULT_MAX_CHARS,
    ScorerContext,
    execute_tool,
    tools_schema,
)
from agi_talent_radar.scholarship.scoring import DIMENSIONS, EVIDENCE_LEVELS, FOCUS_DIRECTIONS, config_version

logger = logging.getLogger(__name__)

Emit = Callable[[str, dict[str, Any]], None]


def _system_prompt(app: ScholarshipApplicationORM, ctx: ScorerContext) -> str:
    dims = "\n".join(
        f"- {d['key']}｜{d['label']}｜满分折算 {d['max_points']} 分｜锚点：{d['anchors']}" for d in DIMENSIONS
    )
    levels = "\n".join(f"- {k}：{v}" for k, v in EVIDENCE_LEVELS.items())
    return f"""你是 Z.AI Scholarship 的匿名评审 agent。所有材料已脱敏（[申请人A]/[学校A]/[导师B] 等占位符），
严禁猜测或还原任何身份，只依据材料与公开查证结果评分。

# 评分维度与行为锚点
{dims}

# 申请人概况（脱敏）
- 年级：{anonymize_text(app.grade or '未知', ctx.identities)}｜学位：{app.degree_type or '未知'}｜预计毕业：{app.expected_graduation or '未知'}
- 研究方向：{app.direction or '未填写'}
- 教育与科研经历（脱敏节选）：{anonymize_text((app.education_history or '')[:800], ctx.identities)}

# 工作方式
1. 先 list_files 盘点全部材料；逐一 read_file（分页读完关键材料；图片/视频会自动转译为文字描述）。
2. 核心产出 claim（论文/奖项/系统）走证据分级瀑布：
   verify_paper 查到 → verified；
   未查到 → 读佐证原文，完整可信 → supported；
   仅自述/截图 → claimed。
3. 简要 web_search 申请人方向与导师的公开负面信息（学术不端/撤稿/争议），发现记入 reputation_findings。
4. 全部材料读过、证据定级完成后 submit_scores。

# 反偏差铁律（违反即无效评分）
1. 材料的数量与包装精美度不计分——30MB 作品集和 1 页 CV 起点完全相同。
2. 分数锚定在可验证的实质上：一篇 verified 论文 > 十份 claimed 截图；claimed 证据相关维度封顶 2.5 分。
3. 佐证材料的详细程度只证明"存在性"，不构成额外分数。
4. 舆情结果只作风险标注（reputation_findings），绝不因搜到负面直接扣分、也绝不因搜到荣誉加分。
5. 每条 reason 必须引用具体证据（材料名/论文标题/数据）并给出该维度主要证据分级。

# 证据分级
{levels}

# 重点支持方向（背景参考，不单独计分）
{'; '.join(FOCUS_DIRECTIONS)}"""


def run_scorer_agent(session, app: ScholarshipApplicationORM, evaluation: ScholarshipEvaluationORM, emit: Emit) -> ScholarshipEvaluationORM:
    """跑一次评分 agent。evaluation 由调用方建好（status=running）并 commit。"""
    from agi_talent_radar.core.llm_client import call_llm_tools

    materials = (
        session.query(ScholarshipMaterialORM)
        .filter_by(application_id=app.id)
        .order_by(ScholarshipMaterialORM.id)
        .all()
    )
    ctx = ScorerContext(app, materials)
    # GLM 1214：messages 不能只含 system，必须有 user 起手
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": _system_prompt(app, ctx)},
        {"role": "user", "content": "开始评审。请按工作方式逐步执行：先盘点并读完材料，"
         "对核心产出查证定级，简要核查公开舆情，最后调用 submit_scores 提交。"},
    ]
    segments: list[dict[str, Any]] = []

    def save_trace() -> None:
        # 深拷贝再赋值：就地改 list 时 SQLAlchemy 按 == 判等会漏更新
        evaluation.trace = copy.deepcopy(segments)
        session.commit()

    try:
        submitted = False
        for round_no in range(MAX_ROUNDS):
            result = call_llm_tools(messages, tools_schema(), temperature=0.2,
                                    reasoning_effort=os.getenv("OPENAI_EFFORT_SCORING", "high"))
            tool_calls = result.get("tool_calls") or []
            if not tool_calls:
                break
            messages.append({
                "role": "assistant",
                "content": result.get("text") or "",
                "tool_calls": [
                    {"id": tc["id"], "type": "function",
                     "function": {"name": tc["name"], "arguments": tc["arguments"]}}
                    for tc in tool_calls
                ],
            })
            for tc in tool_calls:
                args = _parse_args(tc.get("arguments"))
                emit("tool_start", {"call_id": tc["id"], "tool": tc["name"], "args_summary": _brief(args)})
                output = execute_tool(ctx, tc["name"], args)
                summary = str(output.get("summary") or "完成")
                detail = json.dumps(output.get("detail"), ensure_ascii=False, default=str)
                segments.append({
                    "type": "tool", "call_id": tc["id"], "tool": tc["name"],
                    "label": _TOOL_LABELS.get(tc["name"], tc["name"]),
                    "status": "ok", "summary": summary, "detail": detail,
                })
                emit("tool_end", {"call_id": tc["id"], "tool": tc["name"], "status": "ok", "summary": summary, "detail": detail})
                save_trace()
                messages.append({
                    "role": "tool", "tool_call_id": tc["id"],
                    "content": detail[:TOOL_RESULT_MAX_CHARS],
                })
                if ctx.final is not None:
                    submitted = True
                    break
            if submitted:
                break
        if ctx.final is None:
            # 未走到终态：预算耗尽/循环提前结束 → 失败留痕（不发无效分）
            evaluation.status = "failed"
            evaluation.error_message = f"agent 未提交终态评分（{round_no + 1} 轮）"
            segments.append({"type": "text", "text": "⚠ 评分未完成：agent 未能在预算内提交评分。"})
            save_trace()
            return evaluation
        _finalize(evaluation, ctx, segments)
        save_trace()
        emit("final", {"evaluation_id": evaluation.id, "blind_score": evaluation.blind_score})
        return evaluation
    except Exception as exc:  # noqa: BLE001
        logger.exception("评分 agent 失败")
        evaluation.status = "failed"
        evaluation.error_message = str(exc)[:500]
        segments.append({"type": "text", "text": f"⚠ 评分失败：{exc}"})
        try:
            save_trace()
        except Exception:  # noqa: BLE001
            session.rollback()
        return evaluation


def _finalize(evaluation: ScholarshipEvaluationORM, ctx: ScorerContext, segments: list[dict[str, Any]]) -> None:
    final = ctx.final
    by_key = {d["key"]: d for d in DIMENSIONS}
    dims = []
    for d in final["dimensions"]:
        spec = by_key.get(str(d.get("key")))
        if not spec:
            continue
        hi = 10.0 if spec["key"] == "integrity_risk" else 5.0
        dims.append({**spec, "score": max(0.0, min(hi, float(d.get("score") or 0))),
                     "reason": str(d.get("reason") or ""),
                     "evidence_level": str(d.get("evidence_level") or "")})
    blind = round(sum(d["score"] / (10.0 if d["key"] == "integrity_risk" else 5.0) * d["max_points"] for d in dims), 1)
    evaluation.dimensions = dims
    evaluation.blind_score = blind
    evaluation.highlights = final["highlights"]
    evaluation.risks = final["risks"]
    evaluation.config_version = config_version()
    evaluation.status = "completed"
    evaluation.completed_at = datetime.now(timezone.utc).replace(tzinfo=None)
    # 舆情发现的 subject/note 过脱敏闸门：trace 是可展示物（subject 多为申请人/导师名）
    findings = [
        {
            **f,
            "subject": anonymize_text(str(f.get("subject") or ""), ctx.identities),
            "title": anonymize_text(str(f.get("title") or ""), ctx.identities),
            "note": anonymize_text(str(f.get("note") or ""), ctx.identities),
        }
        for f in final["reputation_findings"]
    ]
    segments.append({
        "type": "final",
        "text": f"评分完成：盲评 {blind} 分，推荐档位 {final['recommend_tier']}",
        "blind_score": blind,
        "recommend_tier": final["recommend_tier"],
        "reputation_findings": findings,
    })


_TOOL_LABELS = {
    "list_files": "盘点材料",
    "read_file": "读取材料",
    "verify_paper": "论文查证",
    "web_search": "全网检索",
    "submit_scores": "提交评分",
}


def _brief(args: dict[str, Any]) -> str:
    return json.dumps(args, ensure_ascii=False, default=str)[:80]


def _parse_args(raw: str) -> dict[str, Any]:
    try:
        parsed = json.loads(raw or "{}")
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        return {}
