"""Agent Track 的纯数据评分配置。"""

WEIGHTS = {
    "task_environment": 8,
    "agent_method": 14,
    "tool_action_loop": 10,
    "verification_reliability": 10,
    "agent_system": 8,
    "agent_research_impact": 10,
}

PORTFOLIO_FLOORS = {
    "task_environment": 3.5,
    "agent_method": 3.5,
    "tool_action_loop": 3.0,
    "verification_reliability": 2.5,
    "agent_system": 3.0,
    "agent_research_impact": 4.0,
}
