"""ReAct 主循环：call_llm_tools 流式 → 工具执行 → 结果回填，直到无 tool_calls。

移植自 grill/backend/agent/loop.py，保留 ask_question 本轮终点、裸问纠正等产品特色，
底层 call_llm_tools 换用 zhipu_talent 的实现。
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from agi_talent_radar.core.llm_client import call_llm_tools
from agi_talent_radar.grill import repository as state
from agi_talent_radar.grill.prompts import SYSTEM_PROMPT
from agi_talent_radar.grill.tools import (
    TOOL_RESULT_MAX_CHARS,
    TOOLS_BY_NAME,
    ToolContext,
    blueprint_section,
    state_snapshot,
    tools_schema,
)

logger = logging.getLogger(__name__)

MAX_ROUNDS = 10  # 每次提问的工具预算安全阀
HISTORY_LIMIT = 40
DETAIL_MAX_CHARS = 20000  # 工具 detail 截断上限（search_jobs 带完整 JD，放宽）

Emit = Callable[[str, dict[str, Any]], None]

_CST = timezone(timedelta(hours=8))


def _date_hint() -> str:
    """注入当前北京时间，让 LLM 据此判断届别等相对时间。"""
    now = datetime.now(_CST)
    return (
        f"# 当前时间\n今天是 {now.year} 年 {now.month} 月 {now.day} 日。"
        "判断校招届别等相对时间（今年/明年/后年毕业）时以此为准。"
    )


def run_agent(session_id: str, user_text: str, emit: Emit) -> None:
    sess = state.get_session_by_id(session_id)
    if sess is None:
        emit("error", {"message": "会话不存在"})
        emit("done", {"status": "error"})
        return

    history = sess["messages"]
    history.append({"role": "user", "text": user_text, "tools": []})
    state.save_session(session_id, messages=history)

    messages = [{"role": "system", "content": _date_hint() + "\n\n" + SYSTEM_PROMPT + blueprint_section(sess) + "\n\n" + state_snapshot(sess)}]
    for m in history[-HISTORY_LIMIT:]:
        if m["text"].strip():
            messages.append({"role": m["role"], "content": m["text"]})

    ctx = ToolContext(session_id, emit)
    full_text: list[str] = []
    tool_records: list[dict] = []

    def on_delta(text: str) -> None:
        full_text.append(text)
        emit("answer_delta", {"text": text})

    try:
        exhausted = True
        for _ in range(MAX_ROUNDS):
            result = call_llm_tools(messages, tools_schema(), on_delta=on_delta)
            tool_calls = result.get("tool_calls") or []
            if not tool_calls:
                exhausted = False
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
                _execute_tool(ctx, tc, messages, tool_records, emit)
            # ask_question 是本轮终点：执行完即收尾，防止 LLM 自问自答跑飞
            if any(tc["name"] == "ask_question" for tc in tool_calls):
                exhausted = False
                break
        if exhausted:
            messages.append({"role": "user", "content": "工具预算已用完，请基于已有信息立即给出本轮回复，不要再调用工具。"})
            call_llm_tools(messages, [], on_delta=on_delta)

        # 正文裸问兜底：没走 ask_question/finalize 却在正文提问 → 纠正一次补卡（最多 1 次，失败不卡死）
        called = {r["tool"] for r in tool_records}
        if (
            "ask_question" not in called
            and "finalize" not in called
            and _looks_like_naked_question("".join(full_text))
        ):
            logger.warning("正文裸问，触发纠正补卡: %s", session_id)
            messages.append({"role": "assistant", "content": "".join(full_text)})
            messages.append({
                "role": "user",
                "content": "你刚才在正文里直接提问了，违反纪律。请改用 ask_question 工具重新提问（带 options），正文不再重复问题。",
            })
            try:
                result = call_llm_tools(messages, tools_schema(), on_delta=on_delta)
                for tc in result.get("tool_calls") or []:
                    _execute_tool(ctx, tc, messages, tool_records, emit)
            except Exception:  # noqa: BLE001 纠正失败就把原正文发出
                logger.exception("裸问纠正失败")

        history.append({"role": "assistant", "text": "".join(full_text), "tools": tool_records})
        state.save_session(session_id, messages=history)
        emit("message_done", {})
        emit("done", {"status": "completed"})
    except Exception as exc:  # noqa: BLE001
        logger.exception("agent 循环失败")
        history.append({"role": "assistant", "text": "".join(full_text), "tools": tool_records})
        state.save_session(session_id, messages=history)
        emit("error", {"message": str(exc)})
        emit("done", {"status": "error"})


def _execute_tool(ctx: ToolContext, tc: dict, messages: list, tool_records: list, emit: Emit) -> None:
    tool = TOOLS_BY_NAME.get(tc["name"])
    if tool is None:
        messages.append({"role": "tool", "tool_call_id": tc["id"], "content": f"未知工具：{tc['name']}"})
        return
    args = _parse_args(tc.get("arguments"))
    emit("tool_start", {
        "call_id": tc["id"], "tool": tc["name"], "label": tool["label"],
        "args_summary": json.dumps(args, ensure_ascii=False, default=str)[:120],
    })
    try:
        output = tool["handler"](ctx, args)
        status = "ok" if output.get("ok", True) else "error"
        summary = _summarize(tc["name"], output)
        detail = json.dumps(output, ensure_ascii=False, default=str)
    except Exception as exc:  # noqa: BLE001 坏调用只回填错误，不污染状态
        status, summary, detail = "error", f"执行失败：{exc}", ""
        output = {"ok": False, "error": str(exc)}
    tool_records.append({
        "tool": tc["name"], "label": tool["label"], "status": status,
        "summary": summary, "detail": detail[:DETAIL_MAX_CHARS],
    })
    emit("tool_end", {
        "call_id": tc["id"], "tool": tc["name"], "status": status,
        "summary": summary, "detail": detail[:DETAIL_MAX_CHARS],
    })
    content = detail[:TOOL_RESULT_MAX_CHARS] if status == "ok" else summary
    messages.append({"role": "tool", "tool_call_id": tc["id"], "content": content})


def _summarize(name: str, output: dict) -> str:
    if not output.get("ok", True):
        return str(output.get("error") or "失败")[:80]
    if name == "ask_question":
        subs = output.get("questions") or []
        if subs:
            return "；".join(str(q.get("text") or "") for q in subs)[:200]
        return str(output.get("question") or "完成")[:200]
    if name == "finalize":
        return "需求包已生成"
    if name == "update_profile_card":
        return "已更新画像卡" + ("，必填字段全部达标" if output.get("converged") else "")
    if name == "search_jobs":
        return f"命中 {len(output.get('jobs') or [])} 个岗位"
    return "完成"


QUESTION_RE = re.compile(r"[吗呢？?]|什么|哪[里些个一]|怎么|如何|是否")


def _looks_like_naked_question(text: str) -> bool:
    """启发式：正文含疑问句判为裸问；画像总结确认/交付陈述场景不纠正。"""
    if not text.strip():
        return False
    if "确认" in text and ("画像" in text or "总结" in text):
        return False
    return bool(QUESTION_RE.search(text))


def _parse_args(raw: str) -> dict[str, Any]:
    try:
        parsed = json.loads(raw or "{}")
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        return {}
