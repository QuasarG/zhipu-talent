"""人才问答 ReAct Agent（对话优先，替代旧 LangGraph 固定流水线）。

公共接口：
- run_agent / resume_agent：同步 Agent 循环（agent.py）
- ask_events / action_events：SSE 事件流（service.py）
"""
from __future__ import annotations

from agi_talent_radar.knowledge_agent.agent import resume_agent, run_agent
from agi_talent_radar.knowledge_agent.service import action_events, ask_events

__all__ = [
    "run_agent",
    "resume_agent",
    "ask_events",
    "action_events",
]
