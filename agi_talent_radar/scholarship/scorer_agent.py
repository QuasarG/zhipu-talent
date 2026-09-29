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
from agi_talent_radar.scholarship.scoring import DIMENSIONS, EVIDENCE_LEVELS, FAIRNESS_RULES, FOCUS_DIRECTIONS, config_version

logger = logging.getLogger(__name__)

Emit = Callable[[str, dict[str, Any]], None]


def _system_prompt(app: ScholarshipApplicationORM, ctx: ScorerContext) -> str:
    dims = "\n".join(
        f"- {d['key']}（{d['label']} / {d['label_en']}）｜满分 {d['max_points']} 分\n"
        f"  考察要点：{d['focus']}\n"
        f"  加分参考：{d['bonus_hints']}"
        for d in DIMENSIONS
    )
    levels = "\n".join(f"- {k}：{v}" for k, v in EVIDENCE_LEVELS.items())
    return f"""你是 Z.AI Scholarship 的匿名评审 agent。所有材料已脱敏（[申请人A]/[学校A]/[导师B] 等占位符），
严禁猜测或还原任何身份，只依据材料与公开查证结果评分。

# 评分维度（五维权重制，总分 100）
{dims}

**打分方式**：没有等级锚点，由你在每个维度的满分区间内自由判断给分。敢于拉开分差——
平庸者给低分、突出者给高分，不要把所有人都挤在中间地带。每个维度的分数必须能被
理由和证据支撑，但分值的裁量权完全在你。

{FAIRNESS_RULES}

# 申请人概况（脱敏）
- 年级：{anonymize_text(app.grade or '未知', ctx.identities)}｜学位：{app.degree_type or '未知'}｜预计毕业：{app.expected_graduation or '未知'}
- 研究方向：{app.direction or '未填写'}
- 教育与科研经历（脱敏节选）：{anonymize_text((app.education_history or '')[:800], ctx.identities)}

# 工作方式
0. 表达要求：每次调用工具前，先用一两句话说明「为什么调它、想从里面确认什么」。
   这些说明会展示给评审老师，写清楚目的与预期，不要沉默地连续调用。
1. 先 list_files 盘点全部材料；逐一 read_file（分页读完关键材料；图片/视频会自动转译为文字描述）。
2. 核心产出 claim（论文/奖项/系统）走证据分级瀑布：
   verify_paper 查到 → verified；
   未查到 → 读佐证原文，完整可信 → supported；
   仅自述/截图 → claimed。
3. 材料中若出现申请人个人网站/项目主页/GitHub 等链接，用 web_fetch 抓取正文——
   自述信息（项目介绍、Star 数、获奖列表）以页面实际内容为准，抓取结果同时会展示给评审老师。
4. 简要 web_search 申请人方向与导师的公开负面信息（学术不端/撤稿/争议），发现记入 reputation_findings。
5. 全部材料读过、证据定级完成后 submit_scores。提交内容除各维度分数理由外，还包括：
   - 每维度的 highlights[]（亮点）与 anomalies[]（疑点）——疑点仅提出供人工复核，你无权判定取消资格；
   - verified_papers[]：评审过程中 verify_paper 查证过的论文（含 venue/年份/引用/doi/similar），
     材料里附了原文 PDF 的标注 has_pdf 和 pdf_file_id；
   - special_sections[]：特别栏目（如"开源贡献""特别获奖"），标题与数量由你按材料实际情况决定；
   - highlights/risks（全局亮点与风险）：不限条数，尽量详细充分，宁可多写不可遗漏关键信息。

# 反偏差铁律（违反即无效评分）
1. 舆情结果只作风险标注（reputation_findings），绝不因搜到负面直接扣分、也绝不因搜到荣誉加分。
2. 每条 reason 必须引用具体证据（材料名/论文标题/数据）并给出该维度主要证据分级。
3. anomalies 只描述疑点本身与依据，不做"取消资格"之类的资格判断——那是人工评审的权力。

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
        # 弹性轮数：基础 20 + 每份材料预留 1 轮读取，上限 60 防跑飞。
        # 材料多的人（如 19 份）不会没读完就被掐；真耗尽时注入强制收尾指令再给最后机会。
        max_rounds = min(60, MAX_ROUNDS + len(materials))
        forced_final = False
        empty_rounds = 0
        for round_no in range(max_rounds):
            # 双流对齐问答 SSE 协议：reasoning→thinking_delta（思考卡）、content→answer_delta（正文）。
            # 两类 buffer 职责严格分离：emit_pending 只管发增量（发完即清），
            # trace_acc 是本轮全文累积（落库用）——之前共用一个 buffer 导致 trace 段反复重置、
            # SSE 与落库内容错位（chunk 碎片 bug 的根因）。
            emit_pending: dict[str, list[str]] = {"thinking": [], "answer": []}
            trace_acc: dict[str, str] = {"thinking": "", "answer": ""}
            emit_due = [0.0]
            last_flush = [0.0]
            # 重试轮保护：首轮流出的文本若整轮作废（流中途异常），丢弃已发内容并重置缓冲
            emitted_any = [False]

            def _on(kind: str, text: str) -> None:
                import time as _time

                emitted_any[0] = True
                emit_pending[kind].append(text)
                trace_acc[kind] += text
                now = _time.monotonic()
                if now - emit_due[0] > 0.15:
                    emit_due[0] = now
                    _drain()
                if now - last_flush[0] > 0.8:
                    last_flush[0] = now
                    _flush_open_segments()

            def on_reasoning(text: str) -> None:
                _on("thinking", text)

            def on_delta(text: str) -> None:
                _on("answer", text)

            def _drain() -> None:
                for kind in ("thinking", "answer"):
                    if emit_pending[kind]:
                        emit(f"{kind}_delta", {"text": "".join(emit_pending[kind])})
                        emit_pending[kind].clear()

            def _flush_open_segments() -> None:
                # trace 段 = 本轮到目前为止的全文（幂等覆盖同一段），落库可恢复
                for kind in ("thinking", "answer"):
                    merged = trace_acc[kind].strip()
                    if not merged:
                        continue
                    seg_type = "thinking" if kind == "thinking" else "text"
                    seg = {"type": seg_type, "text": merged}
                    idx = next((i for i, s in enumerate(segments)
                                if s.get("type") == seg_type and s.get("_open")), None)
                    seg["_open"] = True
                    if idx is None:
                        segments.append(seg)
                    else:
                        segments[idx] = seg
                save_trace()

            def _reset_round_streams() -> None:
                """重试轮作废：撤回本轮 open 段、清空累积（SSE 已发的碎片前端会随整轮覆盖）。"""
                for kind in ("thinking", "answer"):
                    emit_pending[kind].clear()
                    trace_acc[kind] = ""
                segments[:] = [s for s in segments if not s.get("_open")]
                emitted_any[0] = False

            # llm_client 重试轮不传回调（静默收集），SSE 侧只有首轮流出；
            # 首轮流中途作废重试时，下方以 result 完整文本覆盖 open 段兜底。

            # llm_client 内部只在 attempt==0 传回调，这里直接传（重试轮由其静默）；
            # 但首轮流中途异常重试时，已回调过的文本无法撤回 —— 用 emitted_any 检测
            # 并在结果返回后校正 trace 段为最终完整文本。
            result = call_llm_tools(
                messages, tools_schema(), temperature=0.2,
                reasoning_effort=os.getenv("OPENAI_EFFORT_SCORING", "high"),
                on_delta=on_delta,
                on_reasoning=on_reasoning,
            )
            # 收尾：以 result 的完整文本为准覆盖 open 段（消除流中途重发/碎片）
            final_text = (result.get("text") or "").strip()
            if final_text:
                trace_acc["answer"] = final_text
            _drain()
            _flush_open_segments()
            for s in segments:
                s.pop("_open", None)
            tool_calls = result.get("tool_calls") or []
            if not trace_acc["answer"] and not trace_acc["thinking"] and not tool_calls:
                # 空响应≠完成（正常收尾必须走 submit_scores）。多数是瞬时模型故障，
                # 催一次继续；连续 3 轮全空才判失败，防死循环。
                empty_rounds += 1
                if empty_rounds >= 3:
                    break
                messages.append({"role": "user", "content": (
                    "上一轮没有返回内容。请继续评审流程：读完剩余材料后"
                    "调用 submit_scores 提交评分。")})
                continue
            empty_rounds = 0
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
                emit("tool_start", {"call_id": tc["id"], "tool": tc["name"], "label": _TOOL_LABELS.get(tc["name"], tc["name"]), "args_summary": _brief(args)})
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
            # 接近预算：最后一轮注入强制收尾指令（对齐问答的 budget_exhausted 语义），
            # 让 agent 基于已收集信息立即提交评分，而不是戛然而止判失败
            if round_no >= max_rounds - 2 and ctx.final is None and not forced_final:
                forced_final = True
                ctx.force_submit = True
                unread = [m.filename for m in ctx.materials if m.id not in ctx.read_ids]
                note = "工具预算即将耗尽。请立即基于已收集的信息调用 submit_scores 提交评分，不要再调用任何其他工具。"
                if unread:
                    note += f"（未读材料：{('、'.join(unread[:5]))}{'等' if len(unread) > 5 else ''}，按已读内容评估并在理由中注明材料未读完）"
                messages.append({"role": "user", "content": note})
        if ctx.final is None:
            # 注入收尾指令后仍未提交 → 失败留痕（不发无效分）
            evaluation.status = "failed"
            evaluation.error_message = f"agent 未提交终态评分（{round_no + 1} 轮）"
            segments.append({"type": "text", "text": "⚠ 评分未完成：agent 未能在预算内提交评分。"})
            save_trace()
            return evaluation
        _finalize(evaluation, ctx, segments)
        app.status = "scored"  # 完成评分 → 状态机推进（旧管道有此步，agent 化时补回）
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
    spec_by_key = {d["key"]: d for d in DIMENSIONS}
    dims = []
    for d in final["dimensions"]:
        spec = spec_by_key.get(str(d.get("key")))
        if not spec:
            continue
        hi = float(spec["max_points"])
        dims.append({
            **spec,
            "score": max(0.0, min(hi, float(d.get("score") or 0))),
            "reason": str(d.get("reason") or ""),
            "evidence_level": str(d.get("evidence_level") or ""),
            "highlights": [str(x) for x in (d.get("highlights") or [])],
            "anomalies": [str(x) for x in (d.get("anomalies") or [])],
        })
    # v3 权重制：维度分即实得分（0..max_points），总分直接加总
    blind = round(sum(d["score"] for d in dims), 1)
    evaluation.dimensions = dims
    evaluation.blind_score = blind
    evaluation.highlights = final["highlights"]
    evaluation.risks = final["risks"]
    evaluation.verified_papers = final["verified_papers"]
    # agent 有时漏写特别栏目 title，兜底防止前端渲染空标题
    evaluation.special_sections = [
        {**s, "title": str(s.get("title") or "").strip() or "特别亮点"}
        for s in final["special_sections"]
    ]
    evaluation.fetched_pages = final["fetched_pages"]
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
        "text": f"评分完成：盲评 {blind} 分",
        "blind_score": blind,
        "reputation_findings": findings,
    })


_TOOL_LABELS = {
    "list_files": "盘点材料",
    "read_file": "读取材料",
    "verify_paper": "论文查证",
    "web_search": "全网检索",
    "web_fetch": "抓取网页",
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
