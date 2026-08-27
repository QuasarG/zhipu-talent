"""人才问答 Agent 的 SSE 事件类型与消息 segment 结构约定。

SSE 事件：``data: {"type": <EVENT_TYPES 之一>, "payload": {...}}``。
assistant 消息 content：``{segments: [{type:"thinking",text} | {type:"text",text} | {type:"tool",call_id,
tool,label,status,summary,detail} | {type:"action",action_id,kind,payload,decision}]}``。
"""
from __future__ import annotations

EVENT_TYPES = (
    "meta",             # {conversation_id, message_id}
    "thinking_delta",   # {text}
    "answer_delta",     # {text}
    "tool_start",       # {call_id, tool, label, args_summary}
    "tool_end",         # {call_id, tool, status(ok|error), summary, detail}
    "action_required",  # {action_id, kind, payload}
    "sources",          # {items: [{id, type, title, url, status}]}
    "message_done",     # {message_id}
    "error",            # {message}
    "done",             # {status: completed | awaiting_action}
)

ACTION_KINDS = ("select_person", "propose_add_person", "resolve_fact_conflict", "clarify")

MESSAGE_STATUS = ("completed", "awaiting_action")
