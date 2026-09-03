"""人才材料包双 agent loop：评估 agent（小轮数）+ 观察 agent（每 turn 督导）。

回合结构（编排器是确定性代码，两个 LLM 互不直接对话）：
  while turn < MAX_TURNS:
      turn = 评估 agent ≤5 轮工具调用（工具按 stage 门控）
      若 submit_profile 受理 → 进档 → 结束
      decision = 观察 agent(过程台账)  → guide/phase/wrap/silent/flag
      指导作为 user input 注入（[督导] 前缀），silent 注入"继续。"
  硬护栏：MAX_TURNS / 预算耗尽 → 强制收尾 turn（只给 submit_profile）

trace 双泳道：评估段（thinking/text/tool）+ 督导段（type=observer），
segments 结构与奖学金评分一致，前端 AssistantMessage 直接渲染。
"""
from __future__ import annotations

import copy
import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Callable

from agi_talent_radar.core.db.orm import TalentBundleORM
from agi_talent_radar.talent_bundle.tools import BundleContext, execute_tool, tools_schema

logger = logging.getLogger(__name__)

Emit = Callable[[str, dict[str, Any]], None]

TURN_ROUNDS = 5                    # 评估 agent 每 turn 最大工具轮数（设计：故意很小）
MAX_TURNS = int(os.getenv("BUNDLE_MAX_TURNS", "12"))

TOOL_LABELS = {
    "list_files": "盘点文件",
    "read_text": "读取文本",
    "read_pages": "视觉转译",
    "search_text": "检索内容",
    "extract_archive": "解压内层包",
    "submit_profile": "提交档案",
}

_EVALUATOR_PROMPT = """你是人才库档案解析 agent。工作区里是一位申请人的全部材料（一人一包，
可能包含简历/论文/证明/推荐信/成绩单/图片/视频/嵌套压缩包，格式各异）。

# 任务
读取材料，提取结构化档案，调用 submit_profile 提交（直接入档，务必准确）。

# 工作方式
0. 每次调工具前先用一两句话说明意图（给评审老师看的，别沉默连调）。
1. 先 list_files 盘点；有 archive 就 extract_archive 解开再看。
2. 文本文档用 read_text 分段读；扫描件/图片用 read_pages 视觉转译；大文件先 search_text 定位再精读。
3. 材料没覆盖的字段留空，严禁编造；关键字段在 source 里写「文件名 第N页」。
4. 全部关键材料读完（或督导示意收尾）即 submit_profile。
5. 收到 [督导] 开头的 user 消息是评审督导的方向性指令，优先服从。

# 系统当前时间
{today}（stage 按此换算实际年级）"""

_OBSERVER_PROMPT = """你是人才档案解析的评审督导 agent。你看到的是评估 agent 的工作过程台账
（它读了什么、查了什么、说了什么），你看不到原始文件——你的职责是审慎观察、把控流程。

# 决策规则（默认 silent，不要话痨）
仅在以下情况出手：
- guide：重复读取已读内容 / 漏读必需证据类别（简历、代表作、推荐信、成绩单）/ 单文件过度逗留 / 前后矛盾
- phase：档案要素已齐，提示收尾提交
- wrap：剩余预算不多，要求基于已有信息立即提交
- flag：发现包级问题（如解压出另一位申请人的材料）→ 挂起转人工
- silent：一切正常

# 输出 JSON
{"action": "guide|phase|wrap|silent|flag", "guidance": "给评估 agent 的简短指令（silent 时留空）", "reason": "一句话依据"}
严禁在 guidance 中出现任何具体分数或评分倾向（这是档案解析，不是评分）。"""


def run_bundle_agent(session, bundle: TalentBundleORM, emit: Emit) -> TalentBundleORM:
    from agi_talent_radar.core.llm_client import call_llm_json, call_llm_tools

    ctx = BundleContext(bundle.id)
    today = datetime.now().strftime("%Y-%m-%d")
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": _EVALUATOR_PROMPT.format(today=today)},
        {"role": "user", "content": "开始解析。先盘点包内文件（注意先解开嵌套压缩包），再读取材料提取档案，最后 submit_profile。"},
    ]
    segments: list[dict[str, Any]] = []
    ledger: list[dict[str, str]] = []   # 观察者台账（紧凑结构化事件）

    def save_trace() -> None:
        bundle.trace = copy.deepcopy(segments)
        session.commit()

    def observe(event: dict[str, str]) -> None:
        ledger.append(event)
        if len(ledger) > 120:
            del ledger[:20]

    def note_observer(action: str, guidance: str, reason: str) -> None:
        segments.append({"type": "observer", "action": action, "text": guidance or reason or action})
        emit("observer", {"action": action, "text": guidance or reason})
        save_trace()

    try:
        bundle.status = "profiling"
        session.commit()
        forced_wrap = False
        submitted = False

        for turn_no in range(1, MAX_TURNS + 1):
            stage = "profiling"
            budget_note = f"（turn {turn_no}/{MAX_TURNS}）"
            for _round in range(TURN_ROUNDS):
                result = call_llm_tools(
                    messages, tools_schema(stage), temperature=0.2,
                    reasoning_effort=os.getenv("OPENAI_EFFORT_SCORING", "high"),
                    on_delta=lambda t: emit("answer_delta", {"text": t}),
                    on_reasoning=lambda t: emit("thinking_delta", {"text": t}),
                )
                text = (result.get("text") or "").strip()
                if text:
                    segments.append({"type": "text", "text": text})
                    observe({"kind": "evaluator_text", "text": text[:400]})
                tool_calls = result.get("tool_calls") or []
                if not tool_calls and not text:
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
                    label = TOOL_LABELS.get(tc["name"], tc["name"])
                    emit("tool_start", {"call_id": tc["id"], "tool": tc["name"], "label": label, "args_summary": _brief(args)})
                    output = execute_tool(ctx, stage, tc["name"], args)
                    summary = str(output.get("summary") or "完成")
                    detail = json.dumps(output.get("detail"), ensure_ascii=False, default=str)
                    segments.append({"type": "tool", "call_id": tc["id"], "tool": tc["name"],
                                     "label": label, "status": "ok", "summary": summary, "detail": detail})
                    emit("tool_end", {"call_id": tc["id"], "tool": tc["name"], "status": "ok", "summary": summary})
                    observe({"kind": "tool", "tool": tc["name"], "args": _brief(args), "summary": summary})
                    messages.append({"role": "tool", "tool_call_id": tc["id"], "content": detail[:6000]})
                    save_trace()
                    if ctx.profile is not None:
                        submitted = True
                        break
                if submitted:
                    break

            if submitted:
                break

            # ---- 观察 agent 决策 ----
            remaining = MAX_TURNS - turn_no
            prompt_payload = {
                "turn": f"{turn_no}/{MAX_TURNS}", "remaining_turns": remaining,
                "read_files": {k: sorted(v)[:20] for k, v in list(ctx.read_pages.items())[:40]},
                "extract_rounds": ctx.extract_rounds,
                "ledger": ledger[-80:],
            }
            try:
                decision = call_llm_json(_OBSERVER_PROMPT, prompt_payload, temperature=0.1)
            except Exception as exc:  # noqa: BLE001 — 观察者失败不阻断主流程，降级为继续
                logger.warning("观察 agent 失败：%s", exc)
                decision = {"action": "silent"}
            action = str(decision.get("action") or "silent")
            guidance = str(decision.get("guidance") or "").strip()
            reason = str(decision.get("reason") or "").strip()
            note_observer(action, guidance, reason)

            if action == "flag":
                bundle.status = "failed"
                bundle.error_message = f"督导挂起转人工：{reason or guidance}"[:500]
                segments.append({"type": "text", "text": f"⚠ 已挂起转人工：{reason or guidance}"})
                save_trace()
                return bundle
            if action == "wrap":
                forced_wrap = True

            if forced_wrap or turn_no >= MAX_TURNS - 1:
                messages.append({"role": "user",
                                 "content": "[系统] 预算即将耗尽。不要再调用其他工具，立即基于已收集信息调用 submit_profile 提交档案（未覆盖字段留空并在 notes 说明）。"})
                forced_wrap = True
            elif guidance:
                messages.append({"role": "user", "content": f"[督导] {guidance}"})
            else:
                messages.append({"role": "user", "content": "继续。"})

        if ctx.profile is None:
            bundle.status = "failed"
            bundle.error_message = f"agent 未能在预算内提交档案（{MAX_TURNS} turns）"
            segments.append({"type": "text", "text": "⚠ 解析未完成：未能在预算内提交档案。"})
            save_trace()
            return bundle

        _admit(session, bundle, ctx)
        segments.append({"type": "final", "text": f"档案已入档：{ctx.profile.get('name')}"})
        bundle.status = "profiled"
        save_trace()
        emit("done", {"bundle_id": bundle.id, "status": "profiled",
                      "person_id": bundle.person_id, "candidate_id": bundle.candidate_id})
        return bundle
    except Exception as exc:  # noqa: BLE001
        logger.exception("材料包解析 agent 失败")
        bundle.status = "failed"
        bundle.error_message = str(exc)[:500]
        segments.append({"type": "text", "text": f"⚠ 解析失败：{exc}"})
        try:
            save_trace()
        except Exception:  # noqa: BLE001
            session.rollback()
        return bundle


def _admit(session, bundle: TalentBundleORM, ctx: BundleContext) -> None:
    """submit_profile → CandidateResume → save_candidate → admit_candidate_from_import（与导入同路径）。"""
    from agi_talent_radar.core.database import save_candidate
    from agi_talent_radar.core.models import CandidateResume
    from agi_talent_radar.services import talent_service

    p = ctx.profile or {}
    resume = CandidateResume(
        id=f"bundle_{bundle.id}",
        name=str(p.get("name") or "").strip(),
        target_role=str(p.get("target_role") or ""),
        stage=str(p.get("stage") or ""),
        directions=[str(x) for x in (p.get("directions") or [])][:8],
        education=p.get("education") or [],
        experiences=p.get("experiences") or [],
        projects=p.get("projects") or [],
        publications=[str(x) for x in (p.get("publications") or [])][:30],
        skills=[str(x) for x in (p.get("skills") or [])][:40],
        raw_text=json.dumps(p.get("notes") or "", ensure_ascii=False),
        source_format="bundle",
    )
    saved = save_candidate(session, resume)
    saved.group = "pending"
    direction = resume.directions[0] if resume.directions else ""
    person_id = talent_service.admit_candidate_from_import(session, saved, direction)
    bundle.candidate_id = saved.id
    bundle.person_id = person_id
    bundle.profile = p
    session.commit()


def _brief(args: dict[str, Any]) -> str:
    return json.dumps(args, ensure_ascii=False, default=str)[:80]


def _parse_args(raw: str) -> dict[str, Any]:
    try:
        parsed = json.loads(raw or "{}")
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        return {}
