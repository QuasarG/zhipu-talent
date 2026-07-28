"""人才知识 Agent 工作流（阶段 5）。

按计划 §阶段 5 + CONTEXT.md：
- 接收自由自然语言请求；
- 优先检索人才库已有内容；
- 库内不足时调用 AMiner / OpenAlex / 智谱 Web Search；
- 三条外部链路独立执行，部分失败不阻塞；
- 输出带来源、时间和核验状态的回答；
- 联网新事实只追加 pending，不覆盖已确认事实；
- 不得修改 HR 状态、合并人物、加入/删除 Candidate、确认事实或修改评分。

公共接口：
    ask_talent_knowledge(conversation_id, prompt) -> Iterator[AgentEvent]
"""
from __future__ import annotations

from agi_talent_radar.knowledge_agent.models import AgentEvent
from agi_talent_radar.knowledge_agent.service import ask_talent_knowledge

__all__ = [
    "AgentEvent",
    "ask_talent_knowledge",
]