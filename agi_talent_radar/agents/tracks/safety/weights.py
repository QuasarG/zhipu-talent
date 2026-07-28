"""Safety Track 的纯数据评分配置。"""

WEIGHTS = {
    "security_insight": 10,
    "method_innovation": 14,
    "validation_rigor": 12,
    "research_impact": 10,
    "security_engineering": 8,
    "ai_safety_transfer": 6,
}

PORTFOLIO_FLOORS = {
    "security_insight": 4.5,
    "method_innovation": 4.5,
    "validation_rigor": 4.0,
    "research_impact": 4.5,
    "security_engineering": 4.5,
}
