"""手写 ReAct 循环：call_llm_tools 流式输出 + 工具执行 + HITL 中断/续跑。

中断恢复机制：触发门控工具时，把完整 messages 快照（含 assistant 的 tool_calls、
已执行工具的 tool 响应）存入 ChatMessageORM.pending_action.llm_messages；
resume 时取出快照，先执行 execute_gated_action（真正写库），把结果作为该
tool_call 的 tool 响应追加，再继续循环。
"""
from __future__ import annotations

import copy
import os
import json
import logging
import time
import uuid
from typing import Any, Callable

from agi_talent_radar.core.db.orm import ChatMessageORM, ConversationORM
from agi_talent_radar.core.llm_client import call_llm_json, call_llm_tools
from agi_talent_radar.knowledge_agent.prompts import SYSTEM_PROMPT, SYSTEM_PROMPT_EN
from agi_talent_radar.knowledge_agent.tools import (
    TOOL_RESULT_MAX_CHARS,
    TOOLS_BY_NAME,
    ToolContext,
    execute_gated_action,
    tools_schema,
)

logger = logging.getLogger(__name__)

MAX_ROUNDS = 24  # 每次提问的循环预算：LLM 自由决策，这只是防跑飞的安全阀
HISTORY_MESSAGE_LIMIT = 60  # 约 30 轮对话，超出头部截断

Emit = Callable[[str, dict[str, Any]], None]

# 系统侧用户可见文案（错误提示 / 门控等待 / 预算耗尽），按界面语言输出
SYSTEM_TEXT = {
    "zh": {
        "conv_missing": "会话不存在",
        "agent_busy": "上一个回答还在进行中，请稍候",
        "no_pending": "该会话没有待处理的动作",
        "action_mismatch": "action_id 不匹配",
        "gated_waiting": "等待用户确认",
        "budget_exhausted": "工具预算已用完，请基于已收集的信息立即总结作答，不要再调用任何工具。",
        "skipped_tool": "该工具调用因等待用户确认被跳过。",
        "done_fallback": "执行完成",
        "tool_failed": "执行失败",
        "title_prompt": '你是会话标题生成器。根据用户首条问题生成不超过 15 字的中文标题，只输出 JSON：{"title": "..."}',
    },
    "en": {
        "conv_missing": "Conversation not found",
        "agent_busy": "The previous answer is still running, please wait",
        "no_pending": "No pending action in this conversation",
        "action_mismatch": "action_id mismatch",
        "gated_waiting": "Waiting for user confirmation",
        "budget_exhausted": "The tool budget is exhausted. Summarize and answer now based on the information collected; do not call any more tools.",
        "skipped_tool": "This tool call was skipped while awaiting user confirmation.",
        "done_fallback": "Done",
        "tool_failed": "Tool failed",
        "title_prompt": 'You are a conversation title generator. Generate an English title of at most 40 characters from the user first question. Output JSON only: {"title": "..."}',
    },
}


def _sys_text(lang: str, key: str) -> str:
    return SYSTEM_TEXT.get(lang, SYSTEM_TEXT["zh"]).get(key, SYSTEM_TEXT["zh"][key])


def run_agent(session, conversation_id: str, user_text: str, emit: Emit, lang: str = "zh") -> None:
    """一轮问答：落库 user 消息 → ReAct 循环 → assistant 消息落库。"""
    conv = session.get(ConversationORM, conversation_id)
    if conv is None:
        emit("error", {"message": _sys_text(lang, "conv_missing")})
        emit("done", {"status": "completed"})
        return
    running = (
        session.query(ChatMessageORM)
        .filter_by(conversation_id=conv.id, role="assistant", status="running")
        .first()
    )
    if running is not None:
        emit("error", {"message": _sys_text(lang, "agent_busy")})
        emit("done", {"status": "completed"})
        return

    messages = [{"role": "system", "content": SYSTEM_PROMPT_EN if lang == "en" else SYSTEM_PROMPT}]
    messages.extend(_history_messages(conv))
    session.add(
        ChatMessageORM(
            conversation_id=conv.id,
            role="user",
            content={"segments": [{"type": "text", "text": user_text}]},
        )
    )
    _maybe_generate_title(conv, user_text, lang)
    # running 状态：前端刷新/切换后靠它识别"还在跑"并轮询跟随
    message_rec = ChatMessageORM(
        conversation_id=conv.id, role="assistant", content={"segments": []}, status="running"
    )
    session.add(message_rec)
    session.commit()

    messages.append({"role": "user", "content": user_text})
    emit("meta", {"conversation_id": conv.id, "message_id": message_rec.id})
    _agent_loop(session, messages, emit, message_rec, lang)


def resume_agent(session, conversation_id: str, action_id: str, decision: dict, emit: Emit, lang: str = "zh") -> None:
    """HITL 决策后续跑：恢复快照 → 执行门控写入 → 回填 tool 响应 → 继续循环。"""
    conv = session.get(ConversationORM, conversation_id)
    if conv is None:
        emit("error", {"message": _sys_text(lang, "conv_missing")})
        emit("done", {"status": "completed"})
        return
    message_rec = (
        session.query(ChatMessageORM)
        .filter_by(conversation_id=conv.id, role="assistant", status="awaiting_action")
        .order_by(ChatMessageORM.created_at.desc())
        .first()
    )
    pending = dict(message_rec.pending_action or {}) if message_rec else {}
    if not pending:
        emit("error", {"message": _sys_text(lang, "no_pending")})
        emit("done", {"status": "completed"})
        return
    if pending.get("action_id") != action_id:
        emit("error", {"message": _sys_text(lang, "action_mismatch")})
        emit("done", {"status": "completed"})
        return

    messages = list(pending.get("llm_messages") or [])
    result_text = execute_gated_action(
        session, str(pending.get("kind") or ""), pending.get("payload") or {}, decision or {}
    )

    # 定格 action segment 的决策结果，消息恢复 completed（深拷贝避免 == 判等漏更新）
    segments = copy.deepcopy((message_rec.content or {}).get("segments") or [])
    for segment in segments:
        if segment.get("type") == "action" and segment.get("action_id") == action_id:
            segment["decision"] = decision
    message_rec.content = {"segments": segments}
    message_rec.status = "running"  # 续跑期间同样标记 running，主循环结束时转 completed
    message_rec.pending_action = None
    session.commit()

    # 门控结果回填后，补齐同一轮被中断跳过的其它 tool_call 响应
    messages.append(
        {"role": "tool", "tool_call_id": pending.get("tool_call_id"), "content": result_text}
    )
    _fill_missing_tool_responses(messages, lang)

    emit("meta", {"conversation_id": conv.id, "message_id": message_rec.id})
    _agent_loop(session, messages, emit, message_rec, lang)


def _agent_loop(session, messages: list[dict], emit: Emit, message_rec: ChatMessageORM, lang: str = "zh") -> None:
    """ReAct 主循环：LLM 流式 → 工具执行 → 回填，直到无 tool_calls 或触发门控。"""
    ctx = ToolContext(session, existing_sources=message_rec.citations or [])
    segments = list((message_rec.content or {}).get("segments") or [])
    last_flush = [0.0]

    def save_segments() -> None:
        # 深拷贝再赋值：就地改 list/dict 时 SQLAlchemy 按 == 判等会漏掉变更
        message_rec.content = {"segments": copy.deepcopy(segments)}
        message_rec.citations = copy.deepcopy(ctx.sources)
        session.commit()

    def on_delta(text: str) -> None:
        emit("answer_delta", {"text": text})
        if not segments or segments[-1].get("type") != "text":
            segments.append({"type": "text", "text": ""})
        segments[-1]["text"] += text
        # 文本流节流落库：刷新/切页后的轮询跟随能看到文字进度
        now = time.monotonic()
        if now - last_flush[0] > 0.8:
            last_flush[0] = now
            save_segments()

    def on_reasoning(text: str) -> None:
        # 思考流只发 SSE 不落库；正文出现后前端收起，纯工具轮由前端在 tool_start 时丢弃
        emit("thinking_delta", {"text": text})

    try:
        exhausted = True
        for _ in range(MAX_ROUNDS):
            result = call_llm_tools(
                messages, tools_schema(), on_delta=on_delta, on_reasoning=on_reasoning,
                reasoning_effort=os.getenv("OPENAI_EFFORT_CHAT", "max"),
            )
            tool_calls = result.get("tool_calls") or []
            if not tool_calls:
                exhausted = False
                break
            messages.append(
                {
                    "role": "assistant",
                    "content": result.get("text") or "",
                    "tool_calls": [
                        {
                            "id": tc["id"],
                            "type": "function",
                            "function": {"name": tc["name"], "arguments": tc["arguments"]},
                        }
                        for tc in tool_calls
                    ],
                }
            )
            for tc in tool_calls:
                tool = TOOLS_BY_NAME.get(tc["name"])
                if tool is None:
                    messages.append(
                        {"role": "tool", "tool_call_id": tc["id"], "content": f"未知工具：{tc['name']}"}
                    )
                    continue
                args = _parse_args(tc.get("arguments"))
                emit(
                    "tool_start",
                    {
                        "call_id": tc["id"],
                        "tool": tc["name"],
                        "label": _tool_label(tool, lang),
                        "label_zh": tool["label"],
                        "args_summary": _args_summary(args),
                    },
                )
                if tool.get("gated"):
                    output = tool["handler"](ctx, args)  # 不写库，只取 kind/payload
                    emit(
                        "tool_end",
                        {
                            "call_id": tc["id"],
                            "tool": tc["name"],
                            "status": "ok",
                            "summary": _sys_text(lang, "gated_waiting"),
                            "detail": "",
                        },
                    )
                    action_id = uuid.uuid4().hex
                    segments.append(
                        {
                            "type": "action",
                            "action_id": action_id,
                            "kind": output["kind"],
                            "payload": output["payload"],
                            "decision": None,
                        }
                    )
                    message_rec.status = "awaiting_action"
                    message_rec.pending_action = {
                        "action_id": action_id,
                        "kind": output["kind"],
                        "payload": output["payload"],
                        "tool_call_id": tc["id"],
                        "llm_messages": messages,
                    }
                    save_segments()
                    emit(
                        "action_required",
                        {"action_id": action_id, "kind": output["kind"], "payload": output["payload"]},
                    )
                    emit("done", {"status": "awaiting_action"})
                    return
                _execute_readonly_tool(tool, tc, args, ctx, segments, messages, emit, lang)
                save_segments()
        if exhausted:
            # 预算耗尽：强制无工具收尾，基于已收集信息总结，别戛然而止
            messages.append(
                {"role": "user", "content": _sys_text(lang, "budget_exhausted")}
            )
            call_llm_tools(
                messages, [], on_delta=on_delta, on_reasoning=on_reasoning,
                reasoning_effort=os.getenv("OPENAI_EFFORT_CHAT", "max"),
            )
        message_rec.status = "completed"
        save_segments()
        emit("sources", {"items": ctx.sources})
        emit("message_done", {"message_id": message_rec.id})
        emit("done", {"status": "completed"})
    except Exception as exc:  # noqa: BLE001
        logger.exception("agent 循环失败")
        message_rec.status = "completed"
        try:
            save_segments()
        except Exception:  # noqa: BLE001
            session.rollback()
        emit("error", {"message": str(exc)})
        emit("done", {"status": "completed"})


def _execute_readonly_tool(tool, tc, args, ctx, segments, messages, emit, lang: str = "zh") -> None:
    """执行只读工具：结果回填 messages，tool segment 落库，发 tool_end。"""
    try:
        output = tool["handler"](ctx, args)
        summary = str(output.get("summary") or _sys_text(lang, "done_fallback"))
        detail = json.dumps(output, ensure_ascii=False, default=str)
        status = "ok"
    except Exception as exc:  # noqa: BLE001
        summary = f'{_sys_text(lang, "tool_failed")}: {exc}'
        detail = ""
        status = "error"
    segments.append(
        {
            "type": "tool",
            "call_id": tc["id"],
            "tool": tc["name"],
            "label": _tool_label(tool, lang),
            "label_zh": tool["label"],
            "status": status,
            "summary": summary,
            "detail": detail,
        }
    )
    emit(
        "tool_end",
        {"call_id": tc["id"], "tool": tc["name"], "status": status, "summary": summary, "detail": detail},
    )
    content = detail[:TOOL_RESULT_MAX_CHARS] if status == "ok" else summary
    messages.append({"role": "tool", "tool_call_id": tc["id"], "content": content})


def _history_messages(conv: ConversationORM, limit: int = HISTORY_MESSAGE_LIMIT) -> list[dict]:
    """历史消息 → LLM messages：只拼 text segment，工具细节不喂回（省 token）。"""
    records = list(conv.messages)
    if len(records) > limit:
        records = records[-limit:]
    messages = []
    for record in records:
        segments = (record.content or {}).get("segments") or []
        text = "".join(
            str(seg.get("text") or "") for seg in segments if seg.get("type") == "text"
        )
        if text.strip():
            messages.append({"role": record.role, "content": text})
    return messages


def _fill_missing_tool_responses(messages: list[dict], lang: str = "zh") -> None:
    """assistant 的每个 tool_call 都必须有 tool 响应；被门控中断跳过的补占位。"""
    responded = {m.get("tool_call_id") for m in messages if m.get("role") == "tool"}
    for message in messages:
        if message.get("role") != "assistant":
            continue
        for tc in message.get("tool_calls") or []:
            if tc.get("id") not in responded:
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "content": _sys_text(lang, "skipped_tool"),
                    }
                )
                responded.add(tc["id"])


def _maybe_generate_title(conv: ConversationORM, user_text: str, lang: str = "zh") -> None:
    """首问后自动生成 ≤15 字标题；失败静默，fallback 截断 prompt。"""
    if conv.title != "新对话":
        return
    title = ""
    try:
        data = call_llm_json(
            _sys_text(lang, "title_prompt"),
            {"question": user_text},
        )
        title = str(data.get("title") or "").strip()
    except Exception:  # noqa: BLE001
        title = ""
    conv.title = (title or user_text.strip())[:15] or "新对话"


def _tool_label(tool: dict, lang: str) -> str:
    """工具名双语：英文界面取 label_en，缺省回退中文 label。"""
    if lang == "en":
        return str(tool.get("label_en") or tool["label"])
    return tool["label"]


def _parse_args(raw: str) -> dict[str, Any]:
    try:
        parsed = json.loads(raw or "{}")
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        return {}


def _args_summary(args: dict[str, Any]) -> str:
    text = json.dumps(args, ensure_ascii=False, default=str)
    return text[:80]
